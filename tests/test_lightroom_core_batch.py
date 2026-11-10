"""Offline/MOCK workbench registration batching, durability and catalog guards."""
import importlib.util
import json
from pathlib import Path

import pytest

from cetacea import config, db
from cetacea.core import Workbench
from cetacea.lightroom import MockLightroomAdapter, RegisterResult


def planned_batch(env, count=4):
    workbench, card = env
    for index in range(count):
        (card / f'{index}.NEF').write_bytes(f'CETACEA-MOCK batch {index}'.encode())
    task = workbench.plan_import('order', 'p', 'card', stages=['ingest', 'lr_register'])
    workbench.approve(task['task_id'], task['plan_digest'])
    return workbench, task


def registration_steps(workbench, task):
    with db.connect(workbench.home) as conn:
        return [dict(row) for row in conn.execute(
            'SELECT * FROM task_steps WHERE task_id=? AND stage="lr_register" ORDER BY run',
            (task['task_id'],))]


def test_workbench_registers_all_pending_inputs_once_without_status_probe(env):
    workbench, task = planned_batch(env)
    original = workbench.adapter.register
    calls = []

    def register(files):
        calls.append([f.asset_id for f in files])
        return original(files)

    workbench.adapter.register = register
    workbench.adapter.status = lambda: pytest.fail('registration must not probe presets/status')
    assert workbench.execute(task['task_id'])['state'] == 'COMPLETED'
    expected = {f['asset_id'] for f in task['plan']['files']}
    assert len(calls) == 1 and set(calls[0]) == expected
    steps = registration_steps(workbench, task)
    assert (steps[0]['succeeded'], steps[0]['failed'], steps[0]['skipped']) == (4, 0, 0)
    assert all(item['mock'] and 'MOCK' in item['status'] for item in json.loads(steps[0]['detail_json']))


def test_workbench_partial_batch_retry_sends_only_failed_assets(env):
    workbench, task = planned_batch(env)
    failed_id = task['plan']['files'][1]['asset_id']
    workbench.adapter.failures['register'] = {failed_id}
    original = workbench.adapter.register
    calls = []

    def register(files):
        calls.append([f.asset_id for f in files])
        return original(files)

    workbench.adapter.register = register
    assert workbench.execute(task['task_id'])['state'] == 'FAILED'
    assert sum(bool(a['lr_photo_id']) for a in workbench.list_assets(task_id=task['task_id'])) == 3
    workbench.adapter.failures.clear()
    assert workbench.retry(task['task_id'])['state'] == 'COMPLETED'
    assert len(calls[0]) == 4 and calls[1] == [failed_id]
    assert [(row['succeeded'], row['failed'], row['skipped'])
            for row in registration_steps(workbench, task)] == [(3, 1, 0), (1, 0, 3)]


def test_workbench_marks_existing_catalog_photos_as_skipped(env):
    workbench, task = planned_batch(env, count=2)

    def register(files):
        return [RegisterResult(f.asset_id, 'MOCK-existing-photo-' + str(index), mock=True,
                               status='existing' if index == 0 else 'added')
                for index, f in enumerate(files)]

    workbench.adapter.register = register
    assert workbench.execute(task['task_id'])['state'] == 'COMPLETED'
    step = registration_steps(workbench, task)[0]
    assert (step['succeeded'], step['failed'], step['skipped']) == (1, 0, 1)
    assert [item['registration_status'] for item in json.loads(step['detail_json'])] == ['existing', 'added']
    assert all(asset['lr_photo_id'] for asset in workbench.list_assets(task_id=task['task_id']))


@pytest.mark.parametrize('mapping', ['duplicate', 'missing', 'unknown'])
def test_workbench_rejects_ambiguous_batch_results(env, mapping):
    workbench, task = planned_batch(env)

    def register(files):
        results = [RegisterResult(f.asset_id, 'MOCK-photo', mock=True) for f in files]
        if mapping == 'duplicate':
            results[-1] = results[0]
        elif mapping == 'missing':
            results.pop()
        else:
            results[-1].asset_id = 'not-in-this-plan'
        return results

    workbench.adapter.register = register
    assert workbench.execute(task['task_id'])['state'] == 'FAILED'
    assert all(a['lr_photo_id'] is None for a in workbench.list_assets(task_id=task['task_id']))
    step = registration_steps(workbench, task)[0]
    assert step['failed'] == 4
    assert all('mapping mismatch' in item['error'] for item in json.loads(step['detail_json']))


def test_workbench_batch_callback_renews_lease_across_long_registration(env, monkeypatch):
    workbench, task = planned_batch(env)
    clock = [10_000.0]
    monkeypatch.setattr('cetacea.core.time.time', lambda: clock[0])
    contender = Workbench(workbench.home)
    workbench.adapter.supports_batch_hook = True
    original = workbench.adapter.register
    batches = []

    def register(files, *, before_batch):
        results = []
        for index in range(0, len(files), 2):
            before_batch()
            clock[0] += 810
            assert contender.recover() == []
            assert contender.get_task(task['task_id'])['state'] == 'RUNNING'
            batch = files[index:index + 2]
            batches.append([f.asset_id for f in batch])
            results.extend(original(batch))
        return results

    workbench.adapter.register = register
    assert workbench.execute(task['task_id'])['state'] == 'COMPLETED'
    assert [len(batch) for batch in batches] == [2, 2]


def test_workbench_batch_callback_blocks_next_batch_after_cancel(env):
    workbench, task = planned_batch(env)
    workbench.adapter.supports_batch_hook = True
    original = workbench.adapter.register
    added = []

    def register(files, *, before_batch):
        before_batch()
        added.extend(f.asset_id for f in files[:2])
        results = original(files[:2])
        workbench.cancel(task['task_id'])
        with pytest.raises(RuntimeError, match='cancelled') as caught:
            before_batch()
        return results + [RegisterResult(f.asset_id, error=str(caught.value), mock=True)
                          for f in files[2:]]

    workbench.adapter.register = register
    assert workbench.execute(task['task_id'])['state'] == 'CANCELLED'
    assert len(added) == 2
    assets = workbench.list_assets(task_id=task['task_id'])
    assert {a['asset_id'] for a in assets if a['lr_photo_id']} == set(added)


def test_workbench_passes_batch_size_configuration(env, monkeypatch):
    workbench, _ = env
    captured = []

    def adapter(**kwargs):
        captured.append(kwargs)
        return MockLightroomAdapter()

    monkeypatch.setattr('cetacea.lightroom.RealLightroomMcpAdapter', adapter)
    workbench.config['lightroom'] = {'adapter': 'real_mcp', 'command': ['MOCK-runtime']}
    config.save(workbench.home, workbench.config)
    Workbench(workbench.home)
    assert captured[-1]['batch_size'] == 100
    workbench.config['lightroom']['batch_size'] = 64
    config.save(workbench.home, workbench.config)
    Workbench(workbench.home)
    assert captured[-1]['batch_size'] == 64


@pytest.mark.parametrize('production_open', [False, True])
def test_blank_window_title_does_not_override_open_test_catalog(production_open):
    script = Path(__file__).resolve().parents[1] / 'scripts/mac/r6_lightroom.py'
    spec = importlib.util.spec_from_file_location('r6_batch_catalog_guard', script)
    r6 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r6)
    calls = []
    test_catalog = '/MOCK/Cetacea-Phase1-Test.lrcat'
    production = str(Path.home() / 'Pictures/Lightroom/Lightroom Catalog.lrcat')

    def runner(args):
        calls.append(args)
        if args[0] == 'pgrep':
            return '4321\n'
        if args[0] == 'lsof':
            return 'n' + test_catalog + '\n' + ('n' + production + '\n' if production_open else '')
        if args[0] == 'osascript':
            return ''  # A blank window title must not veto the catalog evidence.
        raise AssertionError(args)

    guard = r6.catalog_guard(test_catalog, runner=runner)
    assert guard['matches_expected'] is (not production_open)
    assert [args[0] for args in calls] == ['pgrep', 'lsof']
