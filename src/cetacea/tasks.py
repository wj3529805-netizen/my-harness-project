from .audit import record, now
class InvalidTransition(Exception): pass
TRANSITIONS = {'PENDING': {'WAITING_APPROVAL','CANCELLED'}, 'WAITING_APPROVAL': {'RUNNING','CANCELLED'}, 'RUNNING': {'COMPLETED','FAILED','CANCELLED','PAUSED'}, 'PAUSED': {'RUNNING','CANCELLED'}, 'FAILED': {'RUNNING'}, 'CANCELLED': {'WAITING_APPROVAL'}, 'COMPLETED': set()}
def transition(db, principal, task_id, target):
    state = db.execute('SELECT state FROM tasks WHERE task_id=?',(task_id,)).fetchone()['state']
    if target not in TRANSITIONS[state]:
        record(db, principal, 'illegal_transition', task_id, [state,target])
        db.commit()
        raise InvalidTransition(f'{state} -> {target}')
    db.execute('UPDATE tasks SET state=?,updated_at=? WHERE task_id=?',(target,now(),task_id))
    record(db,principal,'state_change',task_id,[state,target])
