import threading
from pathlib import Path
import pytest
from cetacea.core import Workbench
from cetacea.perms import Principal, PermissionDenied
from cetacea.tasks import InvalidTransition, TRANSITIONS, transition
from cetacea.db import connect
from conftest import run

def test_11_idempotency_and_concurrency(planned):
    w,t=planned; assert w.plan_import('order','p','card')['task_id']==t['task_id']; w.approve(t['task_id'],t['plan_digest'])
    entered=threading.Event(); release=threading.Event(); results=[]
    def hook(s,r):
        if s=='after_temp_write': entered.set(); assert release.wait(10)
    w.engine.fault_hook=hook
    th=threading.Thread(target=lambda:results.append(w.execute(t['task_id']))); th.start(); assert entered.wait(10)
    try:
        with pytest.raises(InvalidTransition): w.execute(t['task_id'])
    finally: release.set(); th.join(10)
    assert results[0]['state']=='COMPLETED'; assert len(w.list_tasks())==1 and len(w.list_assets())==1
    assert w.execute(t['task_id'])['state']=='COMPLETED'

def test_12_cancel_retry(env):
    w,c=env
    for n in range(3): (c/f'{n}.RAF').write_bytes(bytes([n])*10)
    t=w.plan_import('order','p','card')
    def hook(stage,rel):
        if stage=='after_commit': w.cancel(t['task_id'])
    w.engine.fault_hook=hook; assert run(w,t)['state']=='CANCELLED'; assert len(list(Path(w.config['library_root']).rglob('*.RAF')))==1
    assert w.retry(t['task_id'])['state']=='WAITING_APPROVAL'
    with pytest.raises(PermissionDenied): w.execute(t['task_id'])
    w.engine.fault_hook=lambda *args:None; assert run(w,w.get_task(t['task_id']))['state']=='COMPLETED'
    assert len(list(Path(w.config['library_root']).rglob('*.RAF')))==3

def test_approve_keeps_waiting_approval_until_execute(planned):
    w, t = planned
    approved = w.approve(t['task_id'], t['plan_digest'])
    assert approved['state'] == 'WAITING_APPROVAL'
    assert approved['run_count'] == 0
    with connect(w.home) as c:
        row = c.execute('SELECT plan_digest, revoked_at FROM approvals WHERE task_id=?', (t['task_id'],)).fetchone()
    assert row['plan_digest'] == t['plan_digest'] and row['revoked_at'] is None
    assert w.execute(t['task_id'])['state'] == 'COMPLETED'
    assert w.get_task(t['task_id'])['run_count'] == 1


def test_16_permissions(planned):
    w,t=planned; ai=Workbench(w.home,Principal('ai','agent',frozenset({'read','plan','execute','approve'})))
    with pytest.raises(PermissionDenied): ai.approve(t['task_id'],t['plan_digest'])
    with pytest.raises(PermissionDenied): ai.execute(t['task_id'])
    assert not list(Path(w.config['library_root']).iterdir())
    readonly=Workbench(w.home,Principal('ai','reader',frozenset({'read'})))
    with pytest.raises(PermissionDenied): readonly.plan_import('order','p','card')
    with pytest.raises(PermissionDenied): w.approve(t['task_id'],'stale')
    w.approve(t['task_id'],t['plan_digest'])
    with pytest.raises(PermissionDenied): ai.execute(t['task_id'],plan_digest='stale')
    assert not list(Path(w.config['library_root']).iterdir())

@pytest.mark.parametrize('state,target',[(s,t) for s in TRANSITIONS for t in TRANSITIONS if t not in TRANSITIONS[s]])
def test_illegal_transitions(planned,state,target):
    w,t=planned
    with connect(w.home) as c:
        c.execute('UPDATE tasks SET state=? WHERE task_id=?',(state,t['task_id']))
        with pytest.raises(InvalidTransition): transition(c,w.principal,t['task_id'],target)
    with connect(w.home) as c:
        assert c.execute('SELECT state FROM tasks').fetchone()[0]==state
        assert c.execute('SELECT count(*) FROM audit_log WHERE action="illegal_transition"').fetchone()[0]==1

def test_recovery(planned):
    w,t=planned; w.approve(t['task_id'],t['plan_digest'])
    with connect(w.home) as c:
        c.execute('UPDATE tasks SET state="RUNNING",lease_until=0 WHERE task_id=?',(t['task_id'],))
    assert w.recover()==[t['task_id']]; assert w.get_task(t['task_id'])['state']=='PAUSED'
    assert w.execute(t['task_id'])['state']=='COMPLETED'

def test_cli_shared_state(env,capsys):
    import json
    from cetacea.cli import main
    w,c=env; (c/'a.RAF').write_bytes(b'raw')
    main(['--home',str(w.home),'plan','order','p','card','--json'])
    t=json.loads(capsys.readouterr().out); assert w.get_task(t['task_id'])['plan_digest']==t['plan_digest']
    main(['--home',str(w.home),'approve',t['task_id'],t['plan_digest'],'--json']); capsys.readouterr()
    main(['--home',str(w.home),'execute',t['task_id'],'--json']); assert json.loads(capsys.readouterr().out)['state']=='COMPLETED'
    main(['--home',str(w.home),'task','show',t['task_id'],'--json']); assert json.loads(capsys.readouterr().out)['state']=='COMPLETED'

def test_requested_stub(planned):
    w,t=planned; t=w.plan_import('order','p','card',stages=['lr_register']); w.approve(t['task_id'],t['plan_digest'])
    with pytest.raises(NotImplementedError): w.execute(t['task_id'])
    assert w.get_task(t['task_id'])['state']=='FAILED'
    with connect(w.home) as c: assert c.execute('SELECT state FROM task_steps').fetchone()[0]=='FAILED'
