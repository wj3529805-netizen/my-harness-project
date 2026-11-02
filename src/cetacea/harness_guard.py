"""Warnings for the restricted Harness model and tool surface."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import re
import sys
from typing import Any, Iterable


@dataclass(frozen=True)
class Warn:
    code: str
    severity: str
    message: str


CAPABILITY = {('deepseek-official', 'deepseek-flash'): True,
              ('deepseek-official', 'deepseek-v4-pro'): True,
              ('cetacea-mock', 'cetacea-mock'): True}
ALLOWED = {'create_goal', 'get_goal', 'update_goal', 'todo_write',
           'list_mcp_resources', 'list_mcp_resource_templates', 'read_mcp_resource'}


def preflight(provider: str, model: str, tool_names: Iterable[str] | None, *, unsupported_models: str | None = None, surface_checked: bool = False) -> list[Warn]:
    warnings = []
    unsupported = {x.strip() for x in (os.environ.get('CETACEA_NO_TOOL_CALLING_MODELS', '') if unsupported_models is None else unsupported_models).split(',')}
    if f'{provider}/{model}' in unsupported:
        warnings.append(Warn('MODEL_NO_TOOL_CALLING', 'error', f'{provider}/{model} is marked as not supporting tool calling.'))
    elif not CAPABILITY.get((provider, model), False):
        warnings.append(Warn('TOOL_CALLING_UNVERIFIED', 'warning', f'Tool calling for {provider}/{model} is unverified.'))
    # None means the driver did not expose a tool list; an empty list is known empty.
    if tool_names is None and surface_checked and provider == 'deepseek-official':
        warnings.append(Warn('TOOL_SURFACE_UNKNOWN', 'warning', 'The offered tool surface could not be determined.'))
    if tool_names is not None:
        names = list(tool_names)
        if not names:
            warnings.append(Warn('NO_TOOLS_OFFERED', 'error', 'No tools were offered to the model.'))
        unexpected = sorted({n for n in names if not n.startswith('mcp__cetacea__') and n not in ALLOWED})
        if unexpected:
            warnings.append(Warn('UNEXPECTED_TOOL_SURFACE', 'error', 'Unexpected tools offered: ' + ', '.join(unexpected)))
    return warnings


def unpack(events: Iterable[dict[str, Any]]) -> tuple[list[tuple[str, Any]], list[tuple[str, str, bool]]]:
    calls, results, names = [], [], {}
    for item in events:
        event = item.get('event', {}) if item.get('type') == 'session_event' else item
        data = event.get('data')
        if not isinstance(data, dict):
            continue
        if event.get('type') == 'tool/call':
            name = data.get('name', '')
            args = data.get('arguments', {})
            if isinstance(args, str):
                try: args = json.loads(args)
                except ValueError: pass
            calls.append((name, args))
            names[data.get('callId')] = name
        elif event.get('type') == 'tool/result':
            message = data.get('message', {})
            if not isinstance(message, dict): continue
            source = message.get('source') or {}
            call_id = message.get('toolCallId') or source.get('callId')
            name = names.get(call_id, message.get('name', 'unknown'))
            text = ''.join(b.get('text', '') for b in message.get('content', []) if isinstance(b, dict) and isinstance(b.get('text', ''), str))
            results.append((name, text, bool(message.get('isError'))))
    return calls, results


def offered_tools(events: Iterable[dict[str, Any]]) -> list[str] | None:
    for item in events:
        event = item.get('event', {}) if item.get('type') == 'session_event' else item
        data = event.get('data')
        if event.get('type') == 'request/header' and isinstance(data, dict) and isinstance(data.get('tools'), list):
            tools = data['tools']
            return [t if isinstance(t, str) else t.get('name', '') for t in tools if isinstance(t, (str, dict))]
    return None


def assess_turn(events: Iterable[dict[str, Any]], require_tools: bool = True, offered: Iterable[str] | None = None) -> list[Warn]:
    events = list(events)
    calls, results = unpack(events)
    warnings = []
    if require_tools and not calls:
        warnings.append(Warn('NO_TOOL_CALLS', 'error', 'The model made no tool call, so no CETACEA action was performed; any success claim in its text is unverified. The model/provider may not support tool calling.'))
    failed = []
    for name, text, is_error in results:
        if is_error:
            body = text.removeprefix('Error: ')
            try:
                parsed = json.loads(body)
                code = parsed.get('code') if isinstance(parsed, dict) else None
            except ValueError: code = None
            failed.append(f'{name} ({code})' if code else name)
    if failed:
        warnings.append(Warn('TOOL_CALL_FAILED', 'warning', 'Tool calls failed: ' + ', '.join(failed)))
    known = list(offered) if offered is not None else offered_tools(events)
    if known is not None:
        unknown = sorted({name for name, _ in calls if name not in known})
        if unknown:
            warnings.append(Warn('UNKNOWN_TOOL_CALLED', 'error', 'Tools called but not offered: ' + ', '.join(unknown)))
    return warnings


def format_warning(w: Warn) -> str:
    return f'WARNING [{w.code}] {w.message}'


def safe_error_line(line: str) -> str | None:
    """Filter child stderr before it can reach terminal or evidence files."""
    line = re.sub(r'\x1b\[[0-9;]*m', '', line)
    if not re.search(r'error|fail|exception|timeout|timed out|ECONN|ENOTFOUND|CERT_', line, re.I):
        return None
    secret = os.environ.get('DEEPSEEK_API_KEY', '')
    if secret:
        from urllib.parse import quote
        for value in (secret, quote(secret, safe=''), json.dumps(secret)[1:-1]):
            line = line.replace(value, '[REDACTED]')
    line = re.sub(r'sk-[A-Za-z0-9_-]{16,}', '[REDACTED]', line)
    line = re.sub(r'(?i)\b(Bearer|Basic)\s+[^\s"\x27,}]+', r'\1 [REDACTED]', line)
    line = re.sub(r'(?i)((?:x-api-key|api_key|apikey|authorization|password)\s*["\x27]?\s*[:=]\s*["\x27]?)[^\s"\x27,}]+', r'\1[REDACTED]', line)
    line = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@', line)
    return re.sub(r'[\x00-\x1f\x7f]', ' ', line).strip()[:4096]


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('filter-stderr')
    pre = sub.add_parser('preflight')
    pre.add_argument('--provider', required=True); pre.add_argument('--model', required=True); pre.add_argument('--tools', required=True)
    assess = sub.add_parser('assess')
    assess.add_argument('file'); assess.add_argument('--require-tools', action='store_true')
    args = parser.parse_args()
    if args.command == 'filter-stderr':
        for line in sys.stdin:
            safe = safe_error_line(line)
            if safe is not None:
                print(safe, file=sys.stderr, flush=True)
        return 0
    if args.command == 'preflight':
        warnings = preflight(args.provider, args.model, [x.strip() for x in args.tools.split(',') if x.strip()])
    else:
        with open(args.file, encoding='utf-8') as f:
            warnings = assess_turn([json.loads(line) for line in f if line.strip()], args.require_tools)
    for warning in warnings: print(format_warning(warning), file=sys.stderr)
    return 2 if any(w.severity == 'error' for w in warnings) else 0


if __name__ == '__main__':
    raise SystemExit(main())
