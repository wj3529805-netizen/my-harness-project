import json
from . import db

def build(w, task_id):
    task = w.get_task(task_id)
    with db.connect(w.home) as c: steps = [dict(r) for r in c.execute('SELECT * FROM task_steps WHERE task_id=? ORDER BY run,rowid',(task_id,))]
    result = {'task':task,'steps':steps,'assets':w.list_assets(task_id=task_id),'mock':bool(w.adapter.mock),'marker':w.adapter.status(),'preview':w.verify_preview(task_id)}
    result['markdown'] = f"# CETACEA report\n\n{result['marker']}\n\nTask {task_id}: {task['state']}\n\nPreview: {result['preview']['status']}\n"
    return result
