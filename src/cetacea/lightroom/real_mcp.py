import asyncio
import json
import os
import sys
import time
import re
import math
from contextlib import contextmanager
from PIL import Image
from pathlib import Path
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.exceptions import MCPError
from mcp_types import CONNECTION_CLOSED, REQUEST_TIMEOUT
from .base import LightroomAdapter, RegisterResult, PresetResult, ExportResult
from ..appledouble import is_ignorable_macos_metadata


class _McpConnection:
    """One synchronous caller, with async contexts owned by one lifetime task.

    Keeping the context owner alive across Runner.run calls matters: MCP uses
    AnyIO cancel scopes which must be exited in the task that entered them.
    A connection is opened lazily, and replaced only after transport failure.
    """
    def __init__(self, adapter):
        self.adapter = adapter
        self.runner = asyncio.Runner()
        self.task = None
        self.session = None

    async def _lifetime(self):
        try:
            params = StdioServerParameters(command=self.adapter.command[0], args=self.adapter.command[1:],
                                           env=bridge_env(testing=self.adapter.testing))
            async with stdio_client(params) as streams:
                async with ClientSession(*streams, read_timeout_seconds=self.initial_timeout) as session:
                    await session.initialize()
                    self.session = session
                    self.ready.set_result(None)
                    await self.stop.wait()
        except BaseException as exc:
            if not self.ready.done():
                self.ready.set_exception(exc)
            raise
        finally:
            self.session = None

    async def _close(self):
        if self.task is not None:
            self.stop.set()
            task, self.task = self.task, None
            try:
                await task
            except asyncio.CancelledError:
                if not task.cancelled():
                    raise

    async def _invoke(self, name, arguments):
        try:
            timeout = 310 if name in {'import_photos', 'import_photos_batch', 'export_photos'} else 30
            if self.task is None:
                self.initial_timeout = timeout
                self.ready = asyncio.get_running_loop().create_future()
                self.stop = asyncio.Event()
                self.task = asyncio.create_task(self._lifetime())
            await self.ready
            if self.task.done():
                try:
                    self.task.result()
                except BaseException as exc:
                    raise EOFError('Lightroom bridge session ended') from exc
                raise EOFError('Lightroom bridge session ended')
            return self.adapter._payload(await self.session.call_tool(name, arguments, read_timeout_seconds=timeout))
        except Exception as exc:
            if self.adapter._transient(exc):
                try:
                    await self._close()
                except Exception:
                    pass  # Retain the original transport error for retry classification.
            raise

    def call(self, name, arguments):
        try:
            return self.runner.run(self._invoke(name, arguments))
        except ExceptionGroup as exc:
            raise RuntimeError(self.adapter._error_summary(exc)) from exc

    def close(self):
        try:
            self.runner.run(self._close())
        finally:
            self.runner.close()


def bridge_env(environ=None, *, testing=False):
    """Environment for the Lightroom bridge process.

    The harness session runner isolates its own HOME. The bridge token and
    port lock live in the operator account home, so that home has to be
    restored for this child only. The token file is never opened or copied.
    """
    source = os.environ if environ is None else environ
    env = {'LIGHTROOM_MCP_TOOLSETS': 'develop'}
    bridge = str(source.get('CETACEA_BRIDGE_HOME', '')).strip()
    if not bridge:
        return env
    path = Path(bridge)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError('CETACEA_BRIDGE_HOME must be an existing absolute directory and not a symlink')
    env['HOME'] = str(path)
    if testing:
        return env
    token = path / '.config' / 'lightroom-mcp' / 'token'
    try:
        present = token.is_file() and not token.is_symlink() and token.stat().st_size > 0
    except OSError:
        present = False
    if not present:
        raise RuntimeError(
            'Lightroom bridge token is absent from CETACEA_BRIDGE_HOME. '
            'A harness session isolates HOME, so the bridge cannot see the plug-in token and '
            'reports an unresponsive port. The token value was not read. Restarting Lightroom does not fix this.'
        )
    return env


class RealLightroomMcpAdapter(LightroomAdapter):
    ALLOWED_TOOLS = frozenset({'import_photos', 'import_photos_batch', 'get_photo_metadata', 'apply_develop_preset', 'export_photos', 'list_develop_presets', 'search_photos'})
    supports_batch_hook = True

    def __init__(self, command=None, test_command=None, backoff_schedule=None, max_retry_sleep=180, sleep=time.sleep, activate_hook=None, batch_size=100):
        if sys.platform != 'darwin' and not (test_command or command):
            raise RuntimeError('requires macOS Lightroom Classic; explicit test command required')
        self.command = test_command or command or ['npx', '-y', '@mskalski/lightroom-mcp@0.26.0']
        self.testing = bool(test_command) or sys.platform != 'darwin'
        if type(batch_size) is not int or not 1 <= batch_size <= 200:
            raise ValueError('batch_size must be an integer between 1 and 200')
        self.batch_size = batch_size
        self._active_connection = None
        schedule = list([2, 4, 8, 16, 30, 30, 30, 60] if backoff_schedule is None else backoff_schedule)
        if (not math.isfinite(max_retry_sleep) or not 0 <= max_retry_sleep <= 600
                or any(not math.isfinite(delay) or delay < 0 for delay in schedule)):
            raise ValueError('invalid retry configuration')
        self.backoff_schedule = schedule
        self.max_attempts = len(schedule) + 1
        self.max_retry_sleep, self.sleep, self.activate_hook = max_retry_sleep, sleep, activate_hook
        self.retry_events = []

    def status(self):
        if self.testing:
            return 'interface-level only, NOT real Lightroom'
        try:
            result = self.call_tool('list_develop_presets', {'limit': 0})
            self._require_success(result)
            if not isinstance(result.get('presets'), list):
                raise ValueError('invalid preset probe response')
            return 'Lightroom MCP connected (real read-only preset probe; catalog identity unverified)'
        except Exception as exc:
            return 'Lightroom MCP disconnected or probe failed: ' + self._error_summary(exc)

    @staticmethod
    def _error_summary(exc):
        """Keep actionable MCP errors when async contexts wrap them in groups."""
        messages = []
        def visit(error):
            if isinstance(error, BaseExceptionGroup):
                for child in error.exceptions:
                    visit(child)
            else:
                message = str(error) or type(error).__name__
                if message not in messages:
                    messages.append(message)
        visit(exc)
        return '; '.join(messages)

    @staticmethod
    def _payload(result):
        if result.is_error:
            raise RuntimeError('; '.join(c.text for c in result.content if c.type == 'text'))
        if result.structured_content is not None:
            payload = result.structured_content
        else:
            blocks = [json.loads(c.text) for c in result.content if c.type == 'text']
            if len(blocks) != 1:
                raise ValueError('expected one Lightroom JSON response')
            payload = blocks[0]
        if not isinstance(payload, dict):
            raise ValueError('expected Lightroom response object')
        if payload.get('success') is False or payload.get('error'):
            raise RuntimeError(str(payload))
        return payload

    def call_tool(self, name, arguments):
        if name not in self.ALLOWED_TOOLS:
            raise ValueError('Forbidden Lightroom tool: ' + name)
        if name == 'export_photos' and arguments.get('on_existing') != 'skip':
            raise ValueError('on_existing must be skip')
        if name in {'import_photos', 'import_photos_batch'} and 'copy_to' in arguments:
            raise ValueError('copy_to forbidden')
        if name == 'import_photos_batch':
            paths = arguments.get('source_paths')
            if set(arguments) != {'source_paths'} or not isinstance(paths, list) or not 1 <= len(paths) <= 200:
                raise ValueError('batch import accepts only 1..200 source_paths')
            if any(not isinstance(p, str) or not Path(p).is_absolute() or '\x00' in p for p in paths) or len(set(paths)) != len(paths):
                raise ValueError('batch source_paths must be unique absolute file paths')
        with self._connection():
            return self._active_connection.call(name, arguments)

    @contextmanager
    def _connection(self):
        if self._active_connection is not None:
            yield
            return
        connection = self._active_connection = _McpConnection(self)
        try:
            yield
        finally:
            self._active_connection = None
            connection.close()

    @staticmethod
    def _require_success(result):
        if not isinstance(result, dict) or result.get('success') is not True:
            raise ValueError('Lightroom did not confirm success: ' + str(result))
        for key in ('missing', 'remaining_paths', 'remaining_ids', 'ai_update_failed'):
            if result.get(key):
                raise ValueError('Lightroom reported ' + key + ': ' + str(result[key]))
        if result.get('complete') is False:
            raise ValueError('Lightroom operation incomplete')

    def _lookup(self, path):
        result = self.call_tool('get_photo_metadata', {'photo_ids': [path]})
        photos, missing = result.get('photos'), result.get('missing')
        if not isinstance(photos, list) or not isinstance(missing, list):
            raise ValueError('invalid Lightroom metadata response')
        if not photos and missing == [path]:
            return None
        if missing or len(photos) != 1 or not isinstance(photos[0], dict):
            raise ValueError('Lightroom metadata did not resolve exactly one photo')
        photo = photos[0]
        if photo.get('path') != path or photo.get('id') in (None, '') or photo.get('isVirtualCopy') is not False:
            raise ValueError('Lightroom photo identity mismatch or virtual copy')
        return photo

    @staticmethod
    def _transient(exc):
        if isinstance(exc, BaseExceptionGroup):
            return any(RealLightroomMcpAdapter._transient(child) for child in exc.exceptions)
        if exc.__cause__ is not None and RealLightroomMcpAdapter._transient(exc.__cause__):
            return True
        if isinstance(exc, MCPError) and exc.code in {CONNECTION_CLOSED, REQUEST_TIMEOUT}:
            return True
        message = RealLightroomMcpAdapter._error_summary(exc).lower()
        return isinstance(exc, (BrokenPipeError, ConnectionResetError, EOFError)) or type(exc).__name__ in {'BrokenResourceError', 'ClosedResourceError', 'EndOfStream'} or bool(re.search(
            r'plugin not connected|econnreset|broken pipe|subprocess.*(exit|closed|terminated)|bridge.*(exit|closed|terminated)|tools/call.*(timed? out|timeout)', message))

    def _retry(self, stage, asset_id, operation, idempotency=None):
        slept = 0
        pending = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                if pending is not None and idempotency is not None:
                    done, value = idempotency()
                    pending['idempotency_check'] = 'completed' if done else 'not_completed'
                    if done:
                        pending['outcome'] = 'already_completed'
                        return value
                value = operation()
                if pending is not None:
                    pending['outcome'] = 'succeeded'
                return value
            except Exception as exc:
                if pending is not None and pending['outcome'] == 'pending':
                    pending['outcome'] = 'failed'
                    if pending['idempotency_check'] == 'pending':
                        pending['idempotency_check'] = 'error'
                if not self._transient(exc) or attempt >= self.max_attempts:
                    raise
                delay = min(self.backoff_schedule[attempt - 1], max(0, self.max_retry_sleep - slept))
                # Error text may contain private paths or identifiers. Record a safe class and category only.
                pending = {'stage': stage, 'asset_id': asset_id, 'attempt': attempt,
                           'error_class': type(exc).__name__, 'error_msg': 'transient Lightroom connection error',
                           'backoff_s': delay, 'cumulative_sleep_s': slept + delay, 'activate': 'skipped', 'outcome': 'pending',
                           'idempotency_check': 'pending' if idempotency else 'not_applicable'}
                self.retry_events.append(pending)
                self.sleep(delay)
                slept += delay
                if attempt >= 2 and self.activate_hook is not None:
                    try:
                        self.activate_hook()
                        pending['activate'] = 'ok'
                    except Exception:
                        pending['activate'] = 'error'
        raise AssertionError('unreachable')

    def readback(self, asset_id, path):
        return self._retry('readback', asset_id, lambda: self.call_tool(
            'get_photo_metadata', {'photo_ids': [str(path)], 'sections': ['developSettings']}))

    @staticmethod
    def _export_file(sub):
        files = [p for p in sub.iterdir() if not is_ignorable_macos_metadata(p)]
        if len(files) != 1 or not files[0].is_file() or files[0].is_symlink():
            raise ValueError('expected one regular exported file')
        with Image.open(files[0]) as image:
            if image.format != 'JPEG':
                raise ValueError('export is not JPEG')
            image.verify()
        return files[0]

    def _lookup_many(self, paths):
        """Check catalog membership in bounded metadata calls, never per photo."""
        present = set()
        for start in range(0, len(paths), 100):
            chunk = paths[start:start + 100]
            result = self.call_tool('get_photo_metadata', {'photo_ids': chunk})
            photos, missing = result.get('photos'), result.get('missing')
            if not isinstance(photos, list) or not isinstance(missing, list):
                raise ValueError('invalid Lightroom metadata response')
            seen, ids = set(), set()
            for photo in photos:
                if not isinstance(photo, dict):
                    raise ValueError('invalid Lightroom photo identity')
                path, identity = photo.get('path'), photo.get('id')
                if (not isinstance(path, str) or path not in chunk or path in seen
                        or type(identity) not in (str, int) or identity == '' or identity in ids
                        or photo.get('isVirtualCopy') is not False):
                    raise ValueError('Lightroom photo identity mismatch or virtual copy')
                seen.add(path)
                ids.add(identity)
            if (any(not isinstance(path, str) or path not in chunk for path in missing)
                    or len(set(missing)) != len(missing) or seen.intersection(missing)
                    or seen.union(missing) != set(chunk)):
                raise ValueError('Lightroom metadata result mapping mismatch')
            present.update(seen)
        return present

    @staticmethod
    def _import_outcomes(result, paths):
        if (not isinstance(result, dict) or result.get('success') is not True
                or type(result.get('complete')) is not bool or not isinstance(result.get('results'), list)):
            raise ValueError('invalid batch import response; install the CETACEA batch plug-in and bridge')
        outcomes = {}
        for row in result['results']:
            if not isinstance(row, dict):
                raise ValueError('invalid batch import result')
            path, status = row.get('path'), row.get('status')
            if not isinstance(path, str) or path not in paths or path in outcomes or not isinstance(status, str) or status not in {'added', 'existing', 'failed'}:
                raise ValueError('batch import result mapping mismatch')
            if status == 'failed' and (not isinstance(row.get('error'), str) or not row['error']):
                raise ValueError('batch import failure missing error')
            if status != 'failed' and row.get('error'):
                raise ValueError('batch import success carries an error')
            outcomes[path] = row
        if (set(outcomes) != set(paths)
                or result['complete'] != all(row['status'] != 'failed' for row in outcomes.values())):
            raise ValueError('incomplete batch import result mapping')
        return outcomes

    def register(self, files, *, before_batch=None):
        """Add exact verified paths, one transaction and one readback per batch.

        The patched local bridge is required; there is no single-photo fallback.
        A dropped reply is reconciled in bulk before retrying only absent paths.
        """
        files = list(files)
        if not files:
            return []
        paths = [str(f.abs_path) for f in files]
        if (len({f.asset_id for f in files}) != len(files) or len(set(paths)) != len(paths)
                or any(not Path(path).is_absolute() or '\x00' in path for path in paths)):
            return [RegisterResult(f.asset_id, error='batch requires unique asset IDs and absolute file paths', status='failed') for f in files]
        results = []
        try:
            with self._connection():
                for start in range(0, len(files), self.batch_size):
                    batch = files[start:start + self.batch_size]
                    batch_paths = [str(f.abs_path) for f in batch]
                    pending_paths = list(batch_paths)
                    outcomes, confirmed = {}, {}

                    # A safety/lease hook failure must halt subsequent batches,
                    # including reconnect attempts, rather than become a retry.
                    hook_error = None
                    def guard():
                        nonlocal hook_error
                        if before_batch is not None:
                            try:
                                before_batch()
                            except Exception as exc:
                                hook_error = exc
                                raise ValueError('Lightroom batch safety check failed') from None

                    def reconcile():
                        nonlocal pending_paths
                        guard()
                        present = self._lookup_many(batch_paths)
                        for path in list(confirmed):
                            if path not in present:
                                confirmed.pop(path)
                        for path in present:
                            row = outcomes.get(path, {'path': path, 'status': 'existing'})
                            if row['status'] == 'failed':
                                row = {'path': path, 'status': 'existing'}
                            confirmed[path] = row
                        pending_paths = [path for path in batch_paths if path not in present]
                        return not pending_paths, dict(confirmed)

                    def operation():
                        guard()
                        imported = self.call_tool('import_photos_batch', {'source_paths': pending_paths})
                        outcomes.update(self._import_outcomes(imported, pending_paths))
                        present = self._lookup_many(batch_paths)
                        for path in batch_paths:
                            row = outcomes.get(path) or confirmed.get(path)
                            if row is None:
                                row = {'path': path, 'status': 'existing'}
                            if row['status'] == 'failed':
                                continue
                            if path in present:
                                confirmed[path] = row
                            else:
                                confirmed.pop(path, None)
                                outcomes[path] = {'path': path, 'status': 'failed', 'error': 'imported photo absent from Lightroom'}
                        return outcomes | confirmed

                    try:
                        rows = self._retry('lr_register', batch[0].asset_id, operation, reconcile)
                        for f in batch:
                            row = rows[str(f.abs_path)]
                            results.append(RegisterResult(f.asset_id, str(f.abs_path) if row['status'] != 'failed' else None,
                                                          error=row.get('error'), status=row['status']))
                    except Exception as exc:
                        if hook_error is not None:
                            raise hook_error
                        for f in batch:
                            row = confirmed.get(str(f.abs_path))
                            results.append(RegisterResult(f.asset_id, str(f.abs_path) if row else None,
                                                          error=None if row else self._error_summary(exc),
                                                          status=row['status'] if row else 'failed'))
        except Exception as exc:
            results.extend(RegisterResult(f.asset_id, error=self._error_summary(exc), status='failed') for f in files[len(results):])
        return results

    def apply_preset(self, photo_refs, preset):
        results = []
        for f in photo_refs:
            path = str(f.abs_path)
            def operation():
                key = 'preset_uuid' if preset.get('lightroom_uuid') else 'preset_name'
                selector = preset.get('lightroom_uuid') or preset['lightroom_name']
                result = self.call_tool('apply_develop_preset', {'photo_ids': [path], key: selector})
                self._require_success(result)
                if type(result.get('applied')) is not int or result['applied'] != 1 or result.get('uuid' if key == 'preset_uuid' else 'preset') != selector:
                    raise ValueError('Lightroom did not apply the expected preset to exactly one photo')
            def already_applied():
                response = self.call_tool('get_photo_metadata', {'photo_ids': [path], 'sections': ['developSettings']})
                photos = response.get('photos')
                if not isinstance(photos, list) or len(photos) != 1 or response.get('missing') != []:
                    raise ValueError('preset idempotency readback failed')
                return photos[0].get('developSettings', {}).get('exposure') == 0.5, None
            try:
                self._retry('lr_preset', f.asset_id, operation, already_applied)
                results.append(PresetResult(f.asset_id))
            except Exception as exc:
                results.append(PresetResult(f.asset_id, self._error_summary(exc)))
        return results

    def export_jpeg(self, photo_refs, dest_dir, max_edge, quality):
        results = []
        for f in photo_refs:
            sub = Path(dest_dir) / f.asset_id
            try:
                sub.mkdir()
                def operation():
                    result = self.call_tool('export_photos', {'photo_ids': [str(f.abs_path)], 'destination': str(sub), 'format': 'jpeg', 'width': max_edge, 'height': max_edge, 'quality': quality, 'on_existing': 'skip'})
                    self._require_success(result)
                    if result.get('complete') is not True or type(result.get('exported')) is not int or result['exported'] != 1 or result.get('destination') != str(sub):
                        raise ValueError('unexpected single-photo export result')
                    return self._export_file(sub)
                def already_exported():
                    if not list(sub.iterdir()):
                        return False, None
                    return True, self._export_file(sub)
                output = self._retry('lr_export', f.asset_id, operation, already_exported)
                results.append(ExportResult(f.asset_id, output))
            except Exception as exc:
                results.append(ExportResult(f.asset_id, error=self._error_summary(exc)))
        return results
