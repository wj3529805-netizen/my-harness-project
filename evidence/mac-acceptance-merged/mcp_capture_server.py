"""Acceptance-only stdio server with transparent real-Lightroom call evidence.

Launch with this repository's Python interpreter (e.g. ``sys.executable``):
  CETACEA_ACCEPTANCE_HOME=/absolute/repo/acceptance-data/merged-test/home
  CETACEA_ACCEPTANCE_LOG=/absolute/repo/evidence/mac-acceptance-merged/calls.jsonl
  python /absolute/repo/evidence/mac-acceptance-merged/mcp_capture_server.py

Optional one-shot control gate, immediately BEFORE the selected real call:
  CETACEA_ACCEPTANCE_GATE_TOOL=import_photos
  CETACEA_ACCEPTANCE_GATE_OCCURRENCE=2
  CETACEA_ACCEPTANCE_GATE_READY=/absolute/repo/evidence/mac-acceptance-merged/gate.ready.json
  CETACEA_ACCEPTANCE_GATE_RELEASE=/absolute/repo/evidence/mac-acceptance-merged/gate.release
  CETACEA_ACCEPTANCE_GATE_TIMEOUT_SECONDS=120  # >0 and <=300; default 120

The launcher owns these test directories and creates the release file when ready.
Both control files must be absent at startup. A gate is acceptance-harness
behavior, not product behavior. Its timeout aborts the attempted call with an
explicit AcceptanceGateTimeout; it never invents a Lightroom response.

No tools are added: the normal create_server(home).run() stdio path is used.
Arguments, results, exceptions, product databases and clocks are not replaced.
SQLite snapshots use mode=ro, not the product's DB helper (which sets WAL).
JSONL has session_started/tool_call_started/tool_call_finished/control events.
Only tool_call_finished contains the actual result or error; delegated=false
means the harness gate stopped the call before the original implementation.
"""
import functools
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import sys
import threading
import time
import traceback
import uuid


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = ROOT / 'evidence' / 'mac-acceptance-merged'
DATA_ROOT = ROOT / 'acceptance-data'


class AcceptanceGateTimeout(TimeoutError):
    """The optional acceptance-only control gate was not released in time."""


def _test_path(value, allowed_root, label):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(label + ' must be an absolute path')
    resolved = path.resolve()
    if resolved == allowed_root or not resolved.is_relative_to(allowed_root):
        raise ValueError(label + ' must be a descendant of ' + str(allowed_root))
    # Reject aliases even if they happen to resolve back inside the allowed root.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(label + ' contains a symlink: ' + str(part))
    return resolved


def _error(exc):
    result = {'type': type(exc).__name__, 'message': str(exc)}
    if isinstance(exc, BaseExceptionGroup):
        result['exceptions'] = [_error(child) for child in exc.exceptions]
    return result


def main():
    home = _test_path(os.environ['CETACEA_ACCEPTANCE_HOME'], DATA_ROOT, 'home')
    log = _test_path(os.environ['CETACEA_ACCEPTANCE_LOG'], EVIDENCE_ROOT, 'log')
    if not home.is_dir() or not (home / 'config.json').is_file():
        raise ValueError('The launcher must initialize the isolated test home first')
    if log.exists() and not log.is_file():
        raise ValueError('log must be a regular file')
    log.parent.mkdir(parents=True, exist_ok=True)

    # The test executable may have an editable installation of another checkout.
    sys.path.insert(0, str(ROOT / 'src'))
    import cetacea
    from cetacea import core
    from cetacea.lightroom import RealLightroomMcpAdapter
    from cetacea.mcp_server import create_server
    if not Path(cetacea.__file__).resolve().is_relative_to(ROOT / 'src'):
        raise RuntimeError('Wrong product checkout imported')

    gate_tool = os.environ.get('CETACEA_ACCEPTANCE_GATE_TOOL')
    gate = None
    gate_envs = ('CETACEA_ACCEPTANCE_GATE_OCCURRENCE', 'CETACEA_ACCEPTANCE_GATE_READY',
                 'CETACEA_ACCEPTANCE_GATE_RELEASE', 'CETACEA_ACCEPTANCE_GATE_TIMEOUT_SECONDS')
    if gate_tool:
        if gate_tool not in RealLightroomMcpAdapter.ALLOWED_TOOLS:
            raise ValueError('Gate tool is outside the real adapter allowlist')
        occurrence = int(os.environ.get('CETACEA_ACCEPTANCE_GATE_OCCURRENCE', '1'))
        timeout = float(os.environ.get('CETACEA_ACCEPTANCE_GATE_TIMEOUT_SECONDS', '120'))
        if occurrence < 1 or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError('Gate occurrence must be positive and timeout must be >0 and <=300 seconds')
        ready = _test_path(os.environ['CETACEA_ACCEPTANCE_GATE_READY'], EVIDENCE_ROOT, 'gate ready')
        release = _test_path(os.environ['CETACEA_ACCEPTANCE_GATE_RELEASE'], EVIDENCE_ROOT, 'gate release')
        if len({ready, release, log}) != 3:
            raise ValueError('Log, gate ready and gate release paths must be distinct')
        if ready.exists() or release.exists():
            raise ValueError('Use fresh gate paths; stale ready/release files are refused')
        ready.parent.mkdir(parents=True, exist_ok=True)
        release.parent.mkdir(parents=True, exist_ok=True)
        gate = {'tool': gate_tool, 'occurrence': occurrence, 'timeout_seconds': timeout,
                'ready': ready, 'release': release}
    elif any(name in os.environ for name in gate_envs):
        raise ValueError('Gate settings require CETACEA_ACCEPTANCE_GATE_TOOL')

    wall_clock, monotonic_clock = time.time, time.monotonic
    session_id = uuid.uuid4().hex
    lock = threading.Lock()
    counts = {}
    lease_seconds = core.LIGHTROOM_ASSET_LEASE_SECONDS

    def db_snapshot():
        observed = wall_clock()
        path = home / 'state.sqlite3'
        result = {'read_only': True, 'database': str(path), 'observed_at_epoch_seconds': observed}
        if not path.is_file():
            return {**result, 'available': False, 'tasks': []}
        try:
            conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
            try:
                conn.row_factory = sqlite3.Row
                rows = [dict(row) for row in conn.execute(
                    'SELECT task_id,state,lease_until,run_count,updated_at FROM tasks ORDER BY created_at,task_id')]
            finally:
                conn.close()
            for row in rows:
                row['lease_remaining_seconds'] = None if row['lease_until'] is None else row['lease_until'] - observed
            return {**result, 'available': True, 'tasks': rows}
        except Exception as exc:
            return {**result, 'available': False, 'error': _error(exc)}

    def append_event(event, required=False):
        payload = {'session_id': session_id, 'recorded_at_epoch_seconds': wall_clock(),
                   'core_lightroom_asset_lease_seconds': lease_seconds, **event}
        try:
            line = json.dumps(payload, ensure_ascii=False, default=str) + '\n'
            with lock:
                fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'a', encoding='utf-8') as stream:
                    stream.write(line)
                    stream.flush()
        except Exception as exc:
            # Evidence failure must not change a delegated product result/error.
            print('ACCEPTANCE_CAPTURE_LOG_ERROR: ' + str(exc), file=sys.stderr, flush=True)
            if required:
                raise

    def control_gate(call_id, name, occurrence):
        if not gate or (name, occurrence) != (gate['tool'], gate['occurrence']):
            return 0.0
        started = monotonic_clock()
        control = {'event': 'acceptance_gate_ready', 'call_id': call_id, 'tool': name,
                   'tool_occurrence': occurrence, 'gate_is_product_behavior': False,
                   'note': 'Acceptance-only pause before delegation; no Lightroom result has been supplied.',
                   'timeout_seconds': gate['timeout_seconds'], 'ready_file': str(gate['ready']),
                   'release_file': str(gate['release']), 'database': db_snapshot()}
        fd = os.open(gate['ready'], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'session_id': session_id, 'core_lightroom_asset_lease_seconds': lease_seconds, **control}, stream, indent=2)
            stream.write('\n')
        append_event(control)
        deadline = started + gate['timeout_seconds']
        while True:
            try:
                release_mode = gate['release'].lstat().st_mode
            except FileNotFoundError:
                pass
            else:
                if not stat.S_ISREG(release_mode):
                    raise ValueError('Gate release must be a regular file, never a symlink')
                waited = monotonic_clock() - started
                append_event({'event': 'acceptance_gate_released', 'call_id': call_id,
                              'gate_is_product_behavior': False, 'gate_wait_seconds': waited})
                return waited
            remaining = deadline - monotonic_clock()
            if remaining <= 0:
                raise AcceptanceGateTimeout('Acceptance-only gate timed out before delegation; this is not a Lightroom/product failure')
            time.sleep(min(0.1, remaining))

    original = RealLightroomMcpAdapter.call_tool

    @functools.wraps(original)
    def captured(self, name, arguments):
        with lock:
            counts[name] = counts.get(name, 0) + 1
            occurrence = counts[name]
        call_id = uuid.uuid4().hex
        started_wall, started = wall_clock(), monotonic_clock()
        before = db_snapshot()
        # Snapshot only for evidence; delegate the original arguments object.
        recorded_arguments = json.loads(json.dumps(arguments, default=str))
        common = {'call_id': call_id, 'tool': name, 'tool_occurrence': occurrence,
                  'arguments': recorded_arguments, 'started_at_epoch_seconds': started_wall}
        append_event({**common, 'event': 'tool_call_started', 'database_before': before})
        result = None
        error = None
        delegated = False
        delegated_at = None
        gate_wait = 0.0
        try:
            gate_wait = control_gate(call_id, name, occurrence)
            delegated_at = monotonic_clock()
            delegated = True
            result = original(self, name, arguments)
            return result
        except BaseException as exc:
            error = _error(exc)
            raise
        finally:
            ended = monotonic_clock()
            event = {**common, 'event': 'tool_call_finished', 'delegated': delegated,
                     'finished_at_epoch_seconds': wall_clock(), 'total_seconds': ended - started,
                     'gate_wait_seconds': gate_wait,
                     'delegated_seconds': None if delegated_at is None else ended - delegated_at,
                     'database_before': before, 'database_after': db_snapshot()}
            if error is not None:
                event['error'] = error
                event['error_origin'] = 'delegated_product_call' if delegated else 'acceptance_harness_before_delegation'
            elif name == 'list_develop_presets' and isinstance(result, dict):
                # The read-only probe may enumerate personal presets. Summarize
                # only its evidence; the actual result returned above is intact.
                presets = result.get('presets')
                event['result'] = {'success': result.get('success'),
                                   'total': result.get('total', result.get('count')),
                                   'returned_count': len(presets) if isinstance(presets, list) else None,
                                   'has_more': result.get('has_more')}
                event['result_recording'] = 'Redacted read-only preset probe summary; presets list omitted; delegated result unchanged.'
            else:
                event['result'] = result
            append_event(event)

    append_event({'event': 'session_started', 'home': str(home), 'log': str(log),
                  'product_source': cetacea.__file__, 'python_executable': sys.executable,
                  'lease_constant_is_920': lease_seconds == 920,
                  'gate': None if gate is None else {**gate, 'gate_is_product_behavior': False},
                  'database': db_snapshot()}, required=True)
    RealLightroomMcpAdapter.call_tool = captured
    try:
        create_server(str(home)).run()
    finally:
        RealLightroomMcpAdapter.call_tool = original
        append_event({'event': 'session_finished', 'database': db_snapshot()})


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # stderr only: stdout belongs exclusively to the normal MCP transport.
        traceback.print_exc(file=sys.stderr)
        raise SystemExit(1)
