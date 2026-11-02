"""Local, long-lived client for the CETACEA Harness session runner."""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from typing import Any, Iterable, Mapping

from . import harness_guard as guard


class HarnessError(RuntimeError):
    pass


class BudgetExceeded(HarnessError):
    pass


@dataclass
class TurnResult:
    output: str
    tool_calls: list[tuple[str, Any]]
    tool_results: list[tuple[str, str, bool]]
    requests: int
    warnings: list[guard.Warn]
    events: list[dict[str, Any]]
    success: bool
    task: str = ''
    tool_surface: list[str] | None = None


def redact(text: str, extra_secrets: Iterable[str] = ()) -> str:
    secrets = [os.environ.get('DEEPSEEK_API_KEY', ''), *extra_secrets]
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, '[REDACTED]')
    return re.sub(r'sk-[A-Za-z0-9_-]{16,}', '[REDACTED]', text)


def _redact_value(value: Any, secrets: Iterable[str]) -> Any:
    if is_dataclass(value) and not isinstance(value, type): value = asdict(value)
    if isinstance(value, str): return redact(value, secrets)
    if isinstance(value, dict): return {redact(str(k), secrets): _redact_value(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_redact_value(v, secrets) for v in value]
    return value


def write_transcript(path: str | Path, title: str, mode: str, model: str,
                     turns: Iterable[TurnResult], notes: Any = '', *, extra_secrets: Iterable[str] = ()) -> str:
    turns = list(turns)
    summary = f'{title}: {len(turns)} turn(s), {sum(t.requests for t in turns)} request(s), {sum(t.success for t in turns)} successful'
    document = _redact_value({'title': title, 'mode': mode, 'model': model, 'summary': summary,
                              'notes': notes, 'turns': turns}, tuple(extra_secrets))
    Path(path).write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return document['summary']


class HarnessSession:
    def __init__(self, mode: str, cetacea_home: str | Path, env: Mapping[str, str] | None = None,
                 ledger_path: str | Path | None = None, max_requests: int | None = None,
                 model: str | None = None, work_path: str | Path | None = None,
                 script_path: str | Path | None = None):
        if mode not in ('mock', 'deepseek'): raise ValueError('mode must be mock or deepseek')
        self.mode, self.home = mode, Path(cetacea_home)
        self.env = dict(os.environ)
        if env: self.env.update(env)
        self.model = model or (self.env.get('CETACEA_MODEL', 'deepseek-flash') if mode == 'deepseek' else 'cetacea-mock')
        self.provider = 'cetacea-mock' if mode == 'mock' else 'deepseek-official'
        self.env['CETACEA_HOME'] = str(self.home)
        if ledger_path is not None: self.env['CETACEA_REQUEST_LEDGER'] = str(ledger_path)
        if max_requests is not None: self.env['CETACEA_MAX_MODEL_REQUESTS'] = str(max_requests)
        if model is not None: self.env['CETACEA_MODEL'] = model
        if work_path is not None: self.env['CETACEA_AGENT_CWD'] = str(work_path)
        if script_path is not None: self.env['CETACEA_MOCK_SCRIPT'] = str(script_path)
        self.warnings: list[guard.Warn] = []
        self.process: subprocess.Popen[str] | None = None
        self._queue: queue.Queue[str | None] = queue.Queue()

    def _warn(self, warnings: Iterable[guard.Warn]) -> list[guard.Warn]:
        result = list(warnings)
        for warning in result:
            self.warnings.append(warning)
            print(redact(guard.format_warning(warning)), file=sys.stderr)
        return result

    def __enter__(self) -> HarnessSession:
        self._warn(guard.preflight(self.provider, self.model, None, unsupported_models=self.env.get('CETACEA_NO_TOOL_CALLING_MODELS', '')))
        # Fail before starting the runner when its required credential is absent.
        if self.mode == 'deepseek' and not self.env.get('DEEPSEEK_API_KEY'):
            raise HarnessError('deepseek session exited with code 5: required credential is absent')
        if self.mode == 'mock':
            # Mock sessions must not inherit unrelated credentials.
            self.env = {k: v for k, v in self.env.items() if not any(s in k.upper() for s in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL'))}
        runner = Path(__file__).resolve().parents[2] / 'harness' / 'run_session.sh'
        try:
            self.process = subprocess.Popen(['bash', str(runner), self.mode], stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                            encoding='utf-8', env=self.env, bufsize=1)
        except OSError as exc:
            self.__exit__(None, None, None)
            raise HarnessError('Unable to start Harness session') from exc
        def read() -> None:
            assert self.process and self.process.stdout
            try:
                for line in self.process.stdout: self._queue.put(line)
            finally: self._queue.put(None)
        threading.Thread(target=read, daemon=True).start()
        return self

    def send(self, task: str, require_tools: bool = True, timeout: float = 180) -> TurnResult:
        if not self.process or not self.process.stdin: raise HarnessError('Session is not running')
        try:
            self.process.stdin.write(json.dumps({'task': task}) + '\n'); self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            code = self.process.wait()
            if code == 4: raise BudgetExceeded('Harness request budget exceeded') from exc
            raise HarnessError(f'Harness session exited with code {code}') from exc
        deadline = time.monotonic() + timeout
        events: list[dict[str, Any]] = []
        surfaces: list[list[str] | None] = []
        while True:
            try: line = self._queue.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                self.process.kill()
                raise HarnessError('Harness session timed out') from exc
            if line is None:
                code = self.process.wait()
                if code == 4: raise BudgetExceeded('Harness request budget exceeded')
                raise HarnessError(f'Harness session exited with code {code}')
            try: message = json.loads(line)
            except ValueError as exc: raise HarnessError('Invalid Harness session output') from exc
            kind = message.get('type')
            if kind == 'session_event': events.append(message)
            elif kind == 'tool_surface':
                tools = message.get('tools')
                surfaces.append(tools if isinstance(tools, list) and all(isinstance(name, str) for name in tools) else None)
            elif kind == 'budget_exceeded': raise BudgetExceeded('Harness request budget exceeded')
            elif kind == 'error': raise HarnessError('Harness session failed')
            elif kind == 'turn_done':
                new_warnings = []
                if not surfaces: surfaces.append(None)
                for offered in surfaces:
                    for w in guard.preflight(self.provider, self.model, offered, unsupported_models=self.env.get('CETACEA_NO_TOOL_CALLING_MODELS', ''), surface_checked=True):
                        if w.code in ('NO_TOOLS_OFFERED', 'UNEXPECTED_TOOL_SURFACE', 'TOOL_SURFACE_UNKNOWN') and w not in new_warnings:
                            new_warnings.append(w)
                surface = None if any(s is None for s in surfaces) else sorted({name for s in surfaces for name in s})
                new_warnings.extend(guard.assess_turn(events, require_tools, surface))
                self._warn(new_warnings)
                calls, results = guard.unpack(events)
                return TurnResult(message.get('output', ''), calls, results, message.get('requests', 0),
                                  list(self.warnings), events, not any(w.severity == 'error' for w in self.warnings), task, surface)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.process:
            if self.process.stdin:
                try: self.process.stdin.close()
                except OSError: pass
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait()
            if self.process.stdout: self.process.stdout.close()
            self.process = None
