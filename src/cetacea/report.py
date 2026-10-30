import json
from . import db

def build(w, task_id):
    task = w.get_task(task_id)
    with db.connect(w.home) as c: steps = [dict(r) for r in c.execute('SELECT * FROM task_steps WHERE task_id=? ORDER BY run,rowid',(task_id,))]
    result = {'task':task,'steps':steps,'assets':w.list_assets(task_id=task_id),'mock':bool(w.adapter.mock),'marker':w.adapter.status(),'preview':w.verify_preview(task_id)}
    lines = [f"# CETACEA 任务报告", "", f"**{result['marker']}**", "", f"- 任务: `{task_id}`  状态: **{task['state']}**  运行次数: {task.get('run_count')}",
             f"- 订单/摄影师/批次: {task['order_id']} / {task['photographer_id']} / {task['batch_id']}", f"- 文件总数: {len(result['assets'])}",
             "", "## 阶段（每次运行）", "", "| run | 阶段 | 状态 | 成功 | 失败 | 跳过 |", "|---|---|---|---|---|---|"]
    for st in steps: lines.append(f"| {st['run']} | {st['stage']} | {st['state']} | {st['succeeded']} | {st['failed']} | {st['skipped']} |")
    pv = result['preview']
    lines += ["", "## 预览核验", "", f"- 状态: **{pv['status']}**"] + [f"- {k}: {pv[k]}" for k in ('expected_count','missing','failed','orphans','size_violations') if k in pv]
    bad = [a for a in result['assets'] if a['status'] != 'VERIFIED']
    lines += ["", "## 异常", ""] + ([f"- {a['rel_path']}: {a['status']} {a.get('error') or ''}" for a in bad] or ["- 无"])
    result['markdown'] = "\n".join(lines) + "\n"
    return result
