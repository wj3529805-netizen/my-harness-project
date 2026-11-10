"""MOCK contract checks for batch registration; no running Lightroom is used."""
import hashlib
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from cetacea.lightroom import RealLightroomMcpAdapter, VerifiedFile


def photos(tmp_path, count):
    result = []
    for index in range(count):
        path = tmp_path / f'{index}.NEF'
        content = f'MOCK raw {index}'.encode()
        path.write_bytes(content)
        result.append(VerifiedFile(f'asset-{index}', path, hashlib.sha256(content).hexdigest(), len(content)))
    return result


class MockBridge:
    """MOCK stdio/session pair with catalog state shared across reconnects."""
    def __init__(self, monkeypatch):
        self.sessions = self.initializations = self.closed_sessions = self.processes = 0
        self.calls = []
        self.present = set()
        self.failed = set()
        self.additions = []
        self.transform_import = lambda response: response
        self.transform_metadata = lambda response: response
        self.lose_import_reply = False
        self.disconnect_after = None
        self.environments = []
        self.session_timeouts = []
        self.tool_timeouts = []
        bridge = self

        class Stdio:
            def __init__(self, params):
                bridge.environments.append(dict(params.env))
            async def __aenter__(self):
                bridge.processes += 1
                return object(), object()
            async def __aexit__(self, *args):
                return False

        class Session:
            def __init__(self, *args, **kwargs):
                bridge.sessions += 1
                bridge.session_timeouts.append(kwargs.get('read_timeout_seconds'))
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                bridge.closed_sessions += 1
                return False
            async def initialize(self):
                bridge.initializations += 1
            async def call_tool(self, name, arguments, **kwargs):
                bridge.tool_timeouts.append(kwargs.get('read_timeout_seconds'))
                response = bridge.call(name, arguments)
                return SimpleNamespace(is_error=False, structured_content=response, content=[])

        monkeypatch.setattr('cetacea.lightroom.real_mcp.stdio_client', Stdio)
        monkeypatch.setattr('cetacea.lightroom.real_mcp.ClientSession', Session)

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        assert name in {'import_photos_batch', 'get_photo_metadata'}, name
        if name == 'import_photos_batch':
            assert set(arguments) == {'source_paths'}
            rows = []
            for index, path in enumerate(arguments['source_paths']):
                if self.disconnect_after is not None and index == self.disconnect_after:
                    self.disconnect_after = None
                    raise ConnectionResetError('MOCK subprocess connection reset')
                if path in self.failed:
                    rows.append({'path': path, 'status': 'failed', 'error': 'MOCK addPhoto failed'})
                elif path in self.present:
                    rows.append({'path': path, 'status': 'existing'})
                else:
                    self.present.add(path)
                    self.additions.append(path)
                    rows.append({'path': path, 'status': 'added'})
            if self.lose_import_reply:
                self.lose_import_reply = False
                raise ConnectionResetError('MOCK subprocess connection reset')
            return self.transform_import({'success': True, 'complete': not any(row['status'] == 'failed' for row in rows), 'results': rows})
        assert set(arguments) == {'photo_ids'}
        requested = arguments['photo_ids']
        assert len(requested) <= 100
        return self.transform_metadata({
            'photos': [{'path': path, 'id': f'MOCK-{path}', 'isVirtualCopy': False} for path in requested if path in self.present],
            'missing': [path for path in requested if path not in self.present],
        })


@pytest.fixture
def bridge(monkeypatch):
    return MockBridge(monkeypatch)


@pytest.mark.parametrize('count,batch_size,expected_sizes', [(1, 100, [1]), (5, 2, [2, 2, 1]), (201, 100, [100, 100, 1])])
def test_registration_uses_one_connection_for_all_batches(tmp_path, bridge, count, batch_size, expected_sizes):
    files = photos(tmp_path, count)
    adapter = RealLightroomMcpAdapter(test_command=['MOCK'], batch_size=batch_size)
    result = adapter.register(files)
    assert [r.asset_id for r in result] == [f.asset_id for f in files]
    assert [r.photo_id for r in result] == [str(f.abs_path) for f in files]
    assert [r.status for r in result] == ['added'] * count
    assert all(r.error is None for r in result)
    assert bridge.processes == bridge.sessions == bridge.initializations == bridge.closed_sessions == 1
    assert [len(args['source_paths']) for name, args in bridge.calls if name == 'import_photos_batch'] == expected_sizes
    assert [len(args['photo_ids']) for name, args in bridge.calls if name == 'get_photo_metadata'] == expected_sizes
    assert [name for name, _ in bridge.calls] == ['import_photos_batch', 'get_photo_metadata'] * len(expected_sizes)
    assert bridge.environments[0]['LIGHTROOM_MCP_TOOLSETS'] == 'develop'


def test_large_batch_splits_metadata_only_at_upstream_limit(tmp_path, bridge):
    files = photos(tmp_path, 200)
    result = RealLightroomMcpAdapter(test_command=['MOCK'], batch_size=200).register(files)
    assert all(r.error is None for r in result)
    assert [len(args['source_paths']) for name, args in bridge.calls if name == 'import_photos_batch'] == [200]
    assert [len(args['photo_ids']) for name, args in bridge.calls if name == 'get_photo_metadata'] == [100, 100]
    assert bridge.processes == 1


def test_existing_photos_are_reported_without_duplicate_additions(tmp_path, bridge):
    files = photos(tmp_path, 3)
    bridge.present.add(str(files[1].abs_path))
    adapter = RealLightroomMcpAdapter(test_command=['MOCK'])
    first = adapter.register(files)
    assert [r.status for r in first] == ['added', 'existing', 'added']
    second = adapter.register(files)
    assert [r.status for r in second] == ['existing'] * 3
    assert all(r.error is None for r in first + second)
    assert bridge.additions == [str(files[0].abs_path), str(files[2].abs_path)]
    assert bridge.processes == 2  # one child per register(), not per photo


def test_partial_failure_reports_per_asset_and_can_resume_only_failed_paths(tmp_path, bridge):
    files = photos(tmp_path, 5)
    bridge.failed = {str(files[1].abs_path), str(files[4].abs_path)}
    adapter = RealLightroomMcpAdapter(test_command=['MOCK'], batch_size=3)
    first = adapter.register(files)
    failed = [f for f, result in zip(files, first) if result.error]
    assert [f.asset_id for f in failed] == [files[1].asset_id, files[4].asset_id]
    assert all(r.photo_id is None and 'MOCK addPhoto failed' in r.error for r in first if r.error)
    assert all(r.photo_id == str(f.abs_path) for f, r in zip(files, first) if not r.error)
    bridge.failed.clear()
    before = len(bridge.calls)
    resumed = adapter.register(failed)
    assert all(r.error is None and r.status == 'added' for r in resumed)
    imports = [args['source_paths'] for name, args in bridge.calls[before:] if name == 'import_photos_batch']
    assert imports == [[str(f.abs_path) for f in failed]]
    assert len(bridge.additions) == len(set(bridge.additions)) == len(files)


def test_lost_reply_recovers_with_one_bulk_check_and_no_duplicate_import(tmp_path, bridge):
    files = photos(tmp_path, 5)
    bridge.lose_import_reply = True
    adapter = RealLightroomMcpAdapter(test_command=['MOCK'], backoff_schedule=[0], sleep=lambda _: None)
    result = adapter.register(files)
    assert all(r.error is None and r.status == 'existing' for r in result)
    assert [name for name, _ in bridge.calls].count('import_photos_batch') == 1
    assert [len(args['photo_ids']) for name, args in bridge.calls if name == 'get_photo_metadata'] == [5]
    assert bridge.processes == bridge.sessions == bridge.initializations == 2
    assert len(bridge.additions) == 5
    assert adapter.retry_events[0]['outcome'] == 'already_completed'


def test_disconnect_mid_batch_retries_without_duplicate_additions(tmp_path, bridge):
    files = photos(tmp_path, 4)
    bridge.disconnect_after = 2
    adapter = RealLightroomMcpAdapter(test_command=['MOCK'], backoff_schedule=[0], sleep=lambda _: None)
    result = adapter.register(files)
    assert all(r.error is None for r in result)
    assert len(bridge.additions) == len(set(bridge.additions)) == 4
    assert bridge.processes == 2
    assert len([args for name, args in bridge.calls if name == 'import_photos_batch']) == 2
    assert any(len(args['photo_ids']) == 4 for name, args in bridge.calls if name == 'get_photo_metadata')


@pytest.mark.parametrize('mutation', [
    lambda response: {**response, 'results': response['results'][:-1]},
    lambda response: {**response, 'results': [response['results'][0]] * 2},
    lambda response: {**response, 'results': [{'path': '/unexpected.NEF', 'status': 'added'}, response['results'][1]]},
    lambda response: {**response, 'results': [{**row, 'status': 'copied'} for row in response['results']]},
    lambda response: {**response, 'success': False},
])
def test_malformed_batch_reply_cannot_claim_success(tmp_path, bridge, mutation):
    files = photos(tmp_path, 2)
    bridge.transform_import = mutation
    result = RealLightroomMcpAdapter(test_command=['MOCK'], backoff_schedule=[]).register(files)
    assert len(result) == 2
    assert all(r.error and r.photo_id is None for r in result)


@pytest.mark.parametrize('mutation', [
    lambda response: {**response, 'photos': [{**row, 'isVirtualCopy': True} for row in response['photos']]},
    lambda response: {**response, 'photos': [{**row, 'id': None} for row in response['photos']]},
    lambda response: {**response, 'photos': [{**row, 'path': '/unexpected.NEF'} for row in response['photos']]},
    lambda response: {**response, 'photos': response['photos'] + response['photos']},
])
def test_bulk_readback_rejects_identity_mismatch(tmp_path, bridge, mutation):
    bridge.transform_metadata = mutation
    result = RealLightroomMcpAdapter(test_command=['MOCK'], backoff_schedule=[]).register(photos(tmp_path, 2))
    assert all(r.error and r.photo_id is None for r in result)


def test_missing_photo_after_batch_is_a_per_asset_error(tmp_path, bridge):
    files = photos(tmp_path, 3)
    missing_path = str(files[1].abs_path)
    def hide(response):
        return {'photos': [row for row in response['photos'] if row['path'] != missing_path], 'missing': [missing_path]}
    bridge.transform_metadata = hide
    result = RealLightroomMcpAdapter(test_command=['MOCK'], backoff_schedule=[]).register(files)
    assert result[1].error and result[1].photo_id is None
    assert result[0].error is result[2].error is None


@pytest.mark.parametrize('value', [0, -1, 201, True, 1.5, '100', None, math.nan])
def test_invalid_batch_size_fails_before_any_process(value, bridge):
    with pytest.raises(ValueError):
        RealLightroomMcpAdapter(test_command=['MOCK'], batch_size=value)
    assert bridge.processes == 0


def test_empty_register_does_not_start_bridge(bridge):
    assert RealLightroomMcpAdapter(test_command=['MOCK']).register([]) == []
    assert bridge.processes == bridge.sessions == 0


def test_batch_tool_forbids_copy_destination_before_launch(bridge):
    adapter = RealLightroomMcpAdapter(test_command=['MOCK'])
    with pytest.raises(ValueError, match='copy_to'):
        adapter.call_tool('import_photos_batch', {'source_paths': ['/MOCK.NEF'], 'copy_to': '/elsewhere'})
    assert bridge.processes == 0


def test_before_batch_guard_runs_for_each_batch_and_blocks_remaining_work(tmp_path, bridge):
    files = photos(tmp_path, 5)
    calls = []
    def guard():
        calls.append(True)
        if len(calls) == 2:
            raise RuntimeError('MOCK formal catalog opened')
    adapter = RealLightroomMcpAdapter(test_command=['MOCK'], batch_size=2)
    result = adapter.register(files, before_batch=guard)
    assert len(calls) == 2
    assert all(r.error is None for r in result[:2])
    assert all(r.error and 'formal catalog' in r.error for r in result[2:])
    assert len(bridge.additions) == 2


def test_real_stdio_mock_process_is_reused_across_batches(tmp_path):
    files = photos(tmp_path, 5)
    adapter = RealLightroomMcpAdapter(
        test_command=[sys.executable, str(Path(__file__).with_name('fake_lightroom_mcp.py'))], batch_size=2)
    process_ids = []
    actual_call = adapter.call_tool
    def call(name, arguments):
        payload = actual_call(name, arguments)
        assert payload['marker'] == 'CETACEA-MOCK'
        process_ids.append(payload['mock_process_id'])
        return payload
    adapter.call_tool = call
    result = adapter.register(files)
    assert all(r.error is None for r in result)
    assert len(process_ids) == 6
    assert len(set(process_ids)) == 1


@pytest.mark.parametrize('mode', ['finished', 'cancelled'])
def test_background_connection_lifetime_exit_reconnects_instead_of_none_session(tmp_path, bridge, mode):
    files = photos(tmp_path, 4)
    adapter = RealLightroomMcpAdapter(test_command=['MOCK'], batch_size=2,
                                      backoff_schedule=[0], sleep=lambda _: None)
    original_call = adapter.call_tool
    ended = []
    def call(name, arguments):
        payload = original_call(name, arguments)
        if name == 'get_photo_metadata' and not ended:
            ended.append(True)
            connection = adapter._active_connection
            async def end_lifetime():
                if mode == 'finished':
                    connection.stop.set()
                else:
                    connection.task.cancel()
                try:
                    await connection.task
                except BaseException as exc:
                    # Simulate the context owner dying independently of the
                    # caller; leave the done task for the next call to detect.
                    import asyncio
                    assert mode == 'cancelled' and isinstance(exc, asyncio.CancelledError)
            connection.runner.run(end_lifetime())
        return payload
    adapter.call_tool = call
    result = adapter.register(files)
    assert all(row.error is None for row in result)
    assert bridge.processes == bridge.sessions == 2
    assert len(bridge.additions) == len(set(bridge.additions)) == 4
    assert adapter.retry_events[0]['outcome'] == 'succeeded'


@pytest.mark.parametrize('status', ['added', 'existing'])
def test_successful_batch_rows_carrying_error_are_rejected(tmp_path, bridge, status):
    files = photos(tmp_path, 2)
    bridge.transform_import = lambda response: {
        **response, 'results': [{**row, 'status': status, 'error': 'MOCK contradictory failure'} for row in response['results']]}
    result = RealLightroomMcpAdapter(test_command=['MOCK']).register(files)
    assert all(row.error and row.photo_id is None for row in result)


def test_transient_looking_guard_failure_is_never_retried(tmp_path, bridge):
    adapter = RealLightroomMcpAdapter(test_command=['MOCK'], sleep=lambda _: None)
    calls = []
    def guard():
        calls.append(True)
        raise RuntimeError('MOCK plugin not connected; catalog guard rejected')
    result = adapter.register(photos(tmp_path, 3), before_batch=guard)
    assert all(row.error and row.photo_id is None for row in result)
    assert len(calls) == 1
    assert adapter.retry_events == []
    assert bridge.processes == 0


@pytest.mark.parametrize('code_name', ['CONNECTION_CLOSED', 'REQUEST_TIMEOUT'])
def test_sdk_transport_error_recovers_lost_batch_reply(tmp_path, bridge, code_name):
    from mcp.shared.exceptions import MCPError
    import mcp_types
    code = getattr(mcp_types, code_name)
    original_call = bridge.call
    lost = []
    def call(name, arguments):
        payload = original_call(name, arguments)
        if name == 'import_photos_batch' and not lost:
            lost.append(True)
            raise MCPError(code, 'MOCK protocol transport failure')
        return payload
    bridge.call = call
    adapter = RealLightroomMcpAdapter(test_command=['MOCK'], backoff_schedule=[0], sleep=lambda _: None)
    result = adapter.register(photos(tmp_path, 3))
    assert all(row.error is None and row.status == 'existing' for row in result)
    assert bridge.processes == 2
    assert len(bridge.additions) == 3
    assert [name for name, _ in bridge.calls] == ['import_photos_batch', 'get_photo_metadata']
    assert adapter.retry_events[0]['outcome'] == 'already_completed'


def test_sdk_invalid_params_error_is_not_retried(tmp_path, bridge):
    from mcp.shared.exceptions import MCPError
    from mcp_types import INVALID_PARAMS
    calls = []
    def invalid(name, arguments):
        calls.append(name)
        raise MCPError(INVALID_PARAMS, 'MOCK invalid arguments')
    bridge.call = invalid
    adapter = RealLightroomMcpAdapter(test_command=['MOCK'], sleep=lambda _: None)
    result = adapter.register(photos(tmp_path, 2))
    assert all(row.error == 'MOCK invalid arguments' and row.photo_id is None for row in result)
    assert calls == ['import_photos_batch']
    assert bridge.processes == 1
    assert adapter.retry_events == []


def test_singleton_probe_and_batch_keep_separate_initialize_timeouts(tmp_path, bridge):
    adapter = RealLightroomMcpAdapter(test_command=['MOCK'])
    assert adapter.call_tool('get_photo_metadata', {'photo_ids': []}) == {'photos': [], 'missing': []}
    result = adapter.register(photos(tmp_path, 2))
    assert all(row.error is None for row in result)
    assert bridge.session_timeouts == [30, 310]
    # A shared session gets a long import timeout and a short readback timeout.
    assert bridge.tool_timeouts == [30, 310, 30]
    assert bridge.processes == 2


def test_latest_reconciliation_clears_no_longer_present_confirmation(tmp_path, bridge):
    files = photos(tmp_path, 2)
    first_path = str(files[0].abs_path)
    bridge.disconnect_after = 1
    original_call = bridge.call
    attempts = []
    def call(name, arguments):
        if name == 'import_photos_batch':
            attempts.append(arguments['source_paths'])
            if len(attempts) == 2:
                # First reconciliation saw the committed first file. Before
                # another lost request, simulate another actor removing it.
                bridge.present.remove(first_path)
                bridge.calls.append((name, arguments))
                raise ConnectionResetError('MOCK subprocess connection reset')
            if len(attempts) == 3:
                bridge.calls.append((name, arguments))
                raise ValueError('MOCK final import failure')
        return original_call(name, arguments)
    bridge.call = call
    adapter = RealLightroomMcpAdapter(test_command=['MOCK'], backoff_schedule=[0, 0], sleep=lambda _: None)
    result = adapter.register(files)
    assert all(row.error == 'MOCK final import failure' and row.photo_id is None for row in result)
    assert attempts == [[str(f.abs_path) for f in files], [str(files[1].abs_path)], [str(f.abs_path) for f in files]]
    assert [name for name, _ in bridge.calls].count('get_photo_metadata') == 2
    assert bridge.present == set()
