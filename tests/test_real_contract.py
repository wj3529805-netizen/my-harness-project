"""0.26.0 upstream contract regressions; fixtures are NOT real Lightroom."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from cetacea.lightroom import RealLightroomMcpAdapter, VerifiedFile


def fixture_adapter():
    return RealLightroomMcpAdapter(test_command=[sys.executable, str(Path(__file__).with_name('fake_lightroom_mcp.py'))])


def verified(tmp_path):
    path = tmp_path / 'test.NEF'
    path.write_bytes(b'test raw only')
    return VerifiedFile('ast_test', path, 'unused-in-contract-test', path.stat().st_size)


def test_upstream_json_text_and_business_errors():
    def response(payload, error=False):
        return SimpleNamespace(is_error=error, structured_content=None, content=[SimpleNamespace(type='text', text=json.dumps(payload))])
    assert RealLightroomMcpAdapter._payload(response({'success': True, 'imported': 1}))['imported'] == 1
    for payload in ({'success': False, 'message': 'failed'}, {'error': 'plugin failed'}):
        with pytest.raises(RuntimeError):
            RealLightroomMcpAdapter._payload(response(payload))
    with pytest.raises(RuntimeError):
        RealLightroomMcpAdapter._payload(response('plugin not connected', error=True))
    with pytest.raises(ValueError):
        RealLightroomMcpAdapter._payload(response([{'success': True}]))


def test_single_photo_batch_contract_and_existing_skip(tmp_path):
    adapter = fixture_adapter()
    f = verified(tmp_path)
    path = str(f.abs_path)
    present = False
    calls = []
    additions = 0

    def call(name, args):
        nonlocal present, additions
        calls.append((name, args))
        if name == 'get_photo_metadata':
            assert args == {'photo_ids': [path]}
            return {'photos': [{'id': 7, 'path': path, 'isVirtualCopy': False}] if present else [], 'missing': [] if present else [path]}
        assert name == 'import_photos_batch' and args == {'source_paths': [path]}
        status = 'existing' if present else 'added'
        additions += not present
        present = True
        return {'success': True, 'complete': True, 'results': [{'path': path, 'status': status}]}

    adapter.call_tool = call
    first = adapter.register([f])[0]
    second = adapter.register([f])[0]
    assert first.photo_id == second.photo_id == path
    assert first.status == 'added' and second.status == 'existing'
    assert additions == 1
    assert sum(name == 'import_photos_batch' for name, _ in calls) == 2
    assert [name for name, _ in calls] == ['import_photos_batch', 'get_photo_metadata'] * 2


@pytest.mark.parametrize('row', [None, {'id': 7, 'path': '/wrong.NEF', 'isVirtualCopy': False}, {'id': 7, 'path': 'actual', 'isVirtualCopy': True}])
def test_registration_requires_exact_metadata_identity(tmp_path, row):
    adapter = fixture_adapter()
    f = verified(tmp_path)
    if row and row['path'] == 'actual':
        row['path'] = str(f.abs_path)
    calls = []

    def call(name, args):
        calls.append(name)
        if name == 'import_photos_batch':
            return {'success': True, 'complete': True, 'results': [{'path': str(f.abs_path), 'status': 'added'}]}
        return {'photos': [] if row is None else [row], 'missing': [str(f.abs_path)] if row is None else []}

    adapter.call_tool = call
    assert adapter.register([f])[0].error
    assert calls.count('import_photos_batch') == 1


@pytest.mark.parametrize('override', [{'success': False}, {'complete': False}, {'results': []}, {'results': [{'path': '/unexpected.NEF', 'status': 'added'}]}])
def test_import_incomplete_or_absent_readback_is_not_registered(tmp_path, override):
    adapter = fixture_adapter()
    f = verified(tmp_path)

    def call(name, args):
        if name == 'get_photo_metadata':
            return {'photos': [], 'missing': [str(f.abs_path)]}
        assert name == 'import_photos_batch'
        return {'success': True, 'complete': True, 'results': [{'path': str(f.abs_path), 'status': 'added'}], **override}

    adapter.call_tool = call
    result = adapter.register([f])[0]
    assert result.error and result.photo_id is None


@pytest.mark.parametrize('override', [{'applied': 0}, {'missing': ['1']}, {'ai_update_failed': ['1']}, {'uuid': 'wrong-uuid'}])
def test_preset_result_must_confirm_exact_target_and_identity(tmp_path, override):
    adapter = fixture_adapter()
    f = verified(tmp_path)
    def call(name, args):
        assert name == 'apply_develop_preset'
        assert args == {'photo_ids': [str(f.abs_path)], 'preset_uuid': 'test-uuid'}
        return {'success': True, 'applied': 1, 'uuid': 'test-uuid', 'missing': [], 'ai_update_failed': [], **override}
    adapter.call_tool = call
    assert adapter.apply_preset([f], {'lightroom_uuid': 'test-uuid'})[0].error


@pytest.mark.parametrize('override', [{'exported': 0}, {'complete': False}, {'remaining_ids': ['1']}, {'destination': '/unexpected'}])
def test_export_counts_and_completion_are_checked_even_with_file(tmp_path, override):
    adapter = fixture_adapter()
    f = verified(tmp_path)
    out = tmp_path / 'output'
    out.mkdir()
    def call(name, args):
        assert name == 'export_photos'
        assert args['width'] == args['height'] == 1600 and 'max_edge' not in args
        (Path(args['destination']) / 'test.jpg').write_bytes(b'file must not imply success')
        return {'success': True, 'exported': 1, 'complete': True, 'destination': args['destination'], **override}
    adapter.call_tool = call
    result = adapter.export_jpeg([f], out, 1600, 85)[0]
    assert result.error and result.output_path is None


def test_status_probes_and_does_not_claim_connection_on_failure():
    adapter = fixture_adapter()
    adapter.testing = False
    def unavailable(name, args):
        assert name == 'list_develop_presets' and args == {'limit': 0}
        raise RuntimeError('plugin offline')
    adapter.call_tool = unavailable
    assert 'disconnected or probe failed' in adapter.status()
    adapter.call_tool = lambda name, args: {'success': True, 'presets': []}
    assert 'real read-only preset probe' in adapter.status()


def test_stdio_fixture_accepts_upstream_import_schema(tmp_path):
    adapter = fixture_adapter()
    f = verified(tmp_path)
    result = adapter.call_tool('import_photos', {'source_path': str(f.abs_path)})
    assert result == {'success': True, 'imported': 1, 'complete': True, 'skipped': 0}



def test_nested_async_taskgroup_errors_retain_plugin_failure(tmp_path):
    adapter = fixture_adapter()
    f = verified(tmp_path)
    underlying = 'canReadFile:<AgErrorID>dng_error_unsupported_raw</AgErrorID>'
    grouped = ExceptionGroup('unhandled errors in a TaskGroup', [
        ExceptionGroup('unhandled errors in a TaskGroup', [RuntimeError(underlying)])
    ])
    def call(name, args):
        raise grouped
    adapter.call_tool = call
    result = adapter.register([f])[0]
    assert result.error == underlying
    adapter.testing = False
    assert underlying in adapter.status()
    assert 'TaskGroup' not in adapter.status()


def test_stdio_schema_failure_retains_underlying_message():
    adapter = fixture_adapter()
    with pytest.raises(RuntimeError) as error:
        adapter.call_tool('import_photos', {'paths': ['/synthetic-test-only.dng']})
    assert 'source_path' in str(error.value)
    assert 'TaskGroup' not in str(error.value)
