import json
import subprocess
import sys

from cetacea.harness_guard import assess_turn, format_warning, preflight
from cetacea.harness_client import TurnResult, redact, write_transcript


def test_error_filter_hides_key_and_credential_fields(monkeypatch):
    from cetacea.harness_guard import safe_error_line
    secret = 'test-secret-with-special+/characters'
    monkeypatch.setenv('DEEPSEEK_API_KEY', secret)
    from urllib.parse import quote
    line = 'ERROR failed: ' + secret + ' ' + quote(secret, safe='') + ' Authorization: Bearer anothercredential x-api-key=thirdcredential'
    safe = safe_error_line(line)
    assert safe and 'failed' in safe
    for value in [secret, quote(secret, safe=''), 'anothercredential', 'thirdcredential']:
        assert value not in safe
    assert safe_error_line('startup profile activated') is None
    assert 'ECONNRESET' in safe_error_line('Error: socket closed ECONNRESET')


def test_error_filter_cli_outputs_only_redacted_errors(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake-credential-for-test')
    p = subprocess.run([sys.executable, '-m', 'cetacea.harness_guard', 'filter-stderr'],
                       input='ordinary startup\nERROR fake-credential-for-test ECONNRESET\n',
                       text=True, capture_output=True, check=True)
    assert p.stdout == ''
    assert 'ordinary startup' not in p.stderr and 'fake-credential-for-test' not in p.stderr
    assert 'ECONNRESET' in p.stderr and '[REDACTED]' in p.stderr


def codes(warnings):
    return {w.code for w in warnings}


def call(name='mcp__cetacea__photo_get_task'):
    return {'type': 'session_event', 'event': {'type': 'tool/call', 'data': {'callId': '1', 'name': name, 'arguments': '{}'}}}


def test_preflight(monkeypatch):
    monkeypatch.delenv('CETACEA_NO_TOOL_CALLING_MODELS', raising=False)
    assert preflight('cetacea-mock', 'cetacea-mock', ['mcp__cetacea__ok', 'get_goal']) == []
    assert codes(preflight('other', 'model', [])) == {'TOOL_CALLING_UNVERIFIED', 'NO_TOOLS_OFFERED'}
    assert codes(preflight('cetacea-mock', 'cetacea-mock', ['bash'])) == {'UNEXPECTED_TOOL_SURFACE'}
    monkeypatch.setenv('CETACEA_NO_TOOL_CALLING_MODELS', 'other/x, cetacea-mock/cetacea-mock')
    assert codes(preflight('cetacea-mock', 'cetacea-mock', ['get_goal'])) == {'MODEL_NO_TOOL_CALLING'}


def test_assess():
    warning, = assess_turn([])
    assert warning.code == 'NO_TOOL_CALLS' and warning.severity == 'error'
    assert 'no CETACEA action' in warning.message and 'unverified' in warning.message and 'may not support' in warning.message
    assert assess_turn([], False) == []
    result = {'type': 'tool/result', 'data': {'message': {'toolCallId': '1', 'isError': True, 'content': [{'text': 'Error: {"code":"NOT_APPROVED"}'}]}}}
    warnings = assess_turn([call('bash'), result], offered=['get_goal'])
    assert codes(warnings) == {'TOOL_CALL_FAILED', 'UNKNOWN_TOOL_CALLED'}
    assert 'NOT_APPROVED' in next(w.message for w in warnings if w.code == 'TOOL_CALL_FAILED')
    assert format_warning(warnings[0]).startswith('WARNING [')


def test_cli(tmp_path):
    cmd = [sys.executable, '-m', 'cetacea.harness_guard']
    r = subprocess.run(cmd + ['preflight', '--provider', 'x', '--model', 'y', '--tools', 'get_goal'], capture_output=True, text=True)
    assert r.returncode == 0 and 'TOOL_CALLING_UNVERIFIED' in r.stderr
    r = subprocess.run(cmd + ['preflight', '--provider', 'x', '--model', 'y', '--tools', 'bash'], capture_output=True, text=True)
    assert r.returncode == 2 and 'UNEXPECTED_TOOL_SURFACE' in r.stderr
    path = tmp_path / 'events.jsonl'; path.write_text('')
    r = subprocess.run(cmd + ['assess', str(path), '--require-tools'], capture_output=True, text=True)
    assert r.returncode == 2 and 'NO_TOOL_CALLS' in r.stderr


def test_redaction_transcript(tmp_path, monkeypatch):
    key = 'sk-FAKE-0123456789abcdef0123'
    monkeypatch.setenv('DEEPSEEK_API_KEY', key)
    assert redact(key + ' sk-abcdefghijklmnop extra-secret', ['extra-secret']) == '[REDACTED] [REDACTED] [REDACTED]'
    turn = TurnResult(key, [('tool', {'secret': key})], [('tool', key, True)], 1, [], [], False, key)
    path = tmp_path / 'transcript.json'
    summary = write_transcript(path, key, 'mock', key, [turn], {'note': key})
    assert key not in path.read_text() and key not in summary
    assert json.loads(path.read_text())['turns'][0]['task'] == '[REDACTED]'


def test_surface_preflight_unknown_and_unexpected(monkeypatch):
    monkeypatch.delenv('CETACEA_NO_TOOL_CALLING_MODELS', raising=False)
    warnings = preflight('deepseek-official', 'deepseek-flash', ['get_goal', 'bash'], surface_checked=True)
    assert codes(warnings) == {'UNEXPECTED_TOOL_SURFACE'}
    assert warnings[0].severity == 'error'
    warnings = preflight('deepseek-official', 'deepseek-flash', None, surface_checked=True)
    assert codes(warnings) == {'TOOL_SURFACE_UNKNOWN'} and warnings[0].severity == 'warning'
    assert preflight('cetacea-mock', 'cetacea-mock', None, surface_checked=True) == []
