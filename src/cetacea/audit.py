import json
from datetime import datetime, timezone

def now(): return datetime.now(timezone.utc).isoformat()
def record(db, principal, action, task_id=None, detail=None):
    db.execute('INSERT INTO audit_log VALUES(?,?,?,?,?)', (f'{principal.actor_type}:{principal.actor_id}', action, task_id, json.dumps(detail), now()))
