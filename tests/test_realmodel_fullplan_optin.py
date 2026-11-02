"""Opt-in real-model coverage for the single-approval full import plan."""
import json

from cetacea import db
from test_realmodel_optin import (
    IDS, PLAN, ROOT, STAGES, cli, no_approval_calls, scenario_env, send,
    session, task_from_plan, write_evidence,
)


def test_fullplan_import_and_preview(scenario_env, tmp_path, monkeypatch):
    w, _ = scenario_env
    ledger = tmp_path / 'request-ledger.json'
    monkeypatch.setenv('CETACEA_REQUEST_LEDGER', str(ledger))
    monkeypatch.setenv('CETACEA_MAX_MODEL_REQUESTS', '12')
    evidence = ROOT / 'evidence' / 'fullplan'
    evidence.mkdir(parents=True, exist_ok=True)
    prompts = [
        'Import the card card-a into order order-1001 for photographer photog-1 '
        'using preset preset-warm and make client previews. Don\'t do anything '
        'that needs approval yourself; tell me what you need.',
    ]
    turns = []
    findings = {'model_passed_stages_explicitly': None,
                'post_approval_permission_errors': [], 'request_count': 0}
    approved = False
    try:
        with session(w, ledger, tmp_path) as s:
            turns.append(send(s, prompts[0]))
            planned = task_from_plan(turns[0])
            calls = [args for name, args in turns[0].tool_calls
                     if name == PLAN and isinstance(args, dict)
                     and all(args.get(k) == v for k, v in IDS.items())]
            if calls:
                findings['model_passed_stages_explicitly'] = 'stages' in calls[-1]
            assert calls
            assert planned is not None
            assert planned['plan']['stages'] == STAGES
            task_id = planned['task_id']
            assert cli(w, 'task', 'show', task_id)['state'] == 'WAITING_APPROVAL'
            assert no_approval_calls(turns[0])

            cli(w, 'approve', task_id, planned['plan_digest'])
            approved = True
            prompts.append('Approved. Please finish the import and previews.')
            turns.append(send(s, prompts[-1]))
            if cli(w, 'task', 'show', task_id)['state'] != 'COMPLETED':
                prompts.append('Please verify the previews and summarize.')
                turns.append(send(s, prompts[-1]))

            assert cli(w, 'task', 'show', task_id)['state'] == 'COMPLETED'
            assert w.verify_preview(task_id)['status'] == 'OK'
            with db.connect(w.home) as connection:
                approvals = connection.execute(
                    'SELECT count(*) FROM approvals WHERE task_id=?', (task_id,)
                ).fetchone()[0]
                exported = connection.execute(
                    'SELECT count(*) FROM previews WHERE task_id=? AND status="EXPORTED"',
                    (task_id,),
                ).fetchone()[0]
            assert exported > 0
            assert approvals == 1
            assert all(no_approval_calls(turn) for turn in turns)
            count = json.loads(ledger.read_text()).get('count', 0) if ledger.exists() else 0
            assert count <= 13
    finally:
        findings['post_approval_permission_errors'] = [
            {'tool': name, 'result': text}
            for turn in turns[1:] if approved
            for name, text, error in turn.tool_results
            if 'PERMISSION_DENIED' in text or 'NOT_APPROVED' in text
        ]
        findings['request_count'] = (
            json.loads(ledger.read_text()).get('count', 0) if ledger.exists() else 0
        )
        write_evidence(evidence, 'fullplan_import_and_preview', prompts, turns, findings, ledger)
