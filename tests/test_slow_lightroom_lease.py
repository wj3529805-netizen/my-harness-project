"""Virtual-clock lease regressions; mock adapters never connect Lightroom."""
import pytest

from cetacea import db
from cetacea.core import Workbench
from cetacea.lightroom import MockLightroomAdapter
from cetacea.tasks import InvalidTransition


def plan(env):
    workbench, card = env
    (card / 'synthetic.NEF').write_bytes(b'CETACEA-MOCK lease fixture')
    task = workbench.plan_import('order', 'p', 'card', stages=['ingest', 'lr_register'])
    workbench.approve(task['task_id'], task['plan_digest'])
    return workbench, task


def test_slow_live_lightroom_runner_keeps_lease_and_excludes_second_executor(env, monkeypatch):
    workbench, task = plan(env)
    clock = [10_000.0]
    monkeypatch.setattr('cetacea.core.time.time', lambda: clock[0])
    contender = Workbench(workbench.home)

    class SlowLightroom(MockLightroomAdapter):
        def register(self, files):
            # Both MCP initialization and tool-response waits may consume their
            # budgets: 2 * (metadata 30 + import 310 + readback 30 + status 30).
            # 810s exceeds the old 300s lease while fitting the legal LR budget.
            clock[0] += 810
            assert contender.recover() == []
            assert contender.get_task(task['task_id'])['state'] == 'RUNNING'
            with pytest.raises(InvalidTransition, match='live runner'):
                contender.execute(task['task_id'])
            return super().register(files)

    adapter = SlowLightroom()
    workbench.adapter = adapter
    completed = workbench.execute(task['task_id'])
    assert completed['state'] == 'COMPLETED'
    assert len([call for call in adapter.calls if call[0] == 'register']) == 1
    assert len(contender.list_assets(task_id=task['task_id'])) == 1


def test_expired_lightroom_runner_is_still_recoverable_after_process_exit(env, monkeypatch):
    workbench, task = plan(env)
    clock = [20_000.0]
    monkeypatch.setattr('cetacea.core.time.time', lambda: clock[0])

    class SimulatedProcessExit(BaseException):
        pass

    class ExitedLightroom(MockLightroomAdapter):
        def register(self, files):
            # A process exit bypasses Exception handlers and leaves its lease,
            # just as an interrupted real runner would.
            raise SimulatedProcessExit

    workbench.adapter = ExitedLightroom()
    with pytest.raises(SimulatedProcessExit):
        workbench.execute(task['task_id'])
    with db.connect(workbench.home) as conn:
        saved = dict(conn.execute('SELECT state,lease_until FROM tasks WHERE task_id=?', (task['task_id'],)).fetchone())
    assert saved['state'] == 'RUNNING'
    assert saved['lease_until'] > clock[0] + 800

    recovered = Workbench(workbench.home)
    clock[0] = saved['lease_until'] + 1
    assert recovered.recover() == [task['task_id']]
    assert recovered.get_task(task['task_id'])['state'] == 'PAUSED'
    assert recovered.execute(task['task_id'])['state'] == 'COMPLETED'
    assert len(recovered.list_assets(task_id=task['task_id'])) == 1
