import asyncio
import json
import sys
import time
import re
from PIL import Image
from pathlib import Path
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from .base import LightroomAdapter, RegisterResult, PresetResult, ExportResult
from ..appledouble import is_ignorable_macos_metadata


class RealLightroomMcpAdapter(LightroomAdapter):
    ALLOWED_TOOLS = frozenset({'import_photos', 'get_photo_metadata', 'apply_develop_preset', 'export_photos', 'list_develop_presets', 'search_photos'})

    def __init__(self, command=None, test_command=None, max_attempts=4, backoff_base=2, max_retry_sleep=14, sleep=time.sleep):
        if sys.platform != 'darwin' and not (test_command or command):
            raise RuntimeError('requires macOS Lightroom Classic; explicit test command required')
        self.command = test_command or command or ['npx', '-y', '@mskalski/lightroom-mcp@0.26.0']
        self.testing = bool(test_command) or sys.platform != 'darwin'
        if max_attempts < 1 or backoff_base < 0 or max_retry_sleep < 0:
            raise ValueError('invalid retry configuration')
        self.max_attempts, self.backoff_base = max_attempts, backoff_base
        self.max_retry_sleep, self.sleep = max_retry_sleep, sleep
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
        if name == 'import_photos' and 'copy_to' in arguments:
            raise ValueError('copy_to forbidden')

        async def invoke():
            # Upstream always includes core when develop is selected. Keep masks
            # and all out of this process; CETACEA still enforces its own allowlist.
            params = StdioServerParameters(command=self.command[0], args=self.command[1:], env={'LIGHTROOM_MCP_TOOLSETS': 'develop'})
            timeout = 310 if name in {'import_photos', 'export_photos'} else 30
            async with stdio_client(params) as streams:
                async with ClientSession(*streams, read_timeout_seconds=timeout) as session:
                    await session.initialize()
                    return self._payload(await session.call_tool(name, arguments))
        try:
            return asyncio.run(invoke())
        except ExceptionGroup as exc:
            raise RuntimeError(self._error_summary(exc)) from exc

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
                delay = min(self.backoff_base * (2 ** (attempt - 1)), max(0, self.max_retry_sleep - slept))
                # Error text may contain private paths or identifiers. Record a safe class and category only.
                pending = {'stage': stage, 'asset_id': asset_id, 'attempt': attempt,
                           'error_class': type(exc).__name__, 'error_msg': 'transient Lightroom connection error',
                           'backoff_s': delay, 'outcome': 'pending',
                           'idempotency_check': 'pending' if idempotency else 'not_applicable'}
                self.retry_events.append(pending)
                self.sleep(delay)
                slept += delay
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

    def register(self, files):
        results = []
        for f in files:
            path = str(f.abs_path)
            def operation():
                if self._lookup(path) is None:
                    imported = self.call_tool('import_photos', {'source_path': path})
                    self._require_success(imported)
                    if imported.get('complete') is not True or type(imported.get('imported')) is not int or imported['imported'] not in (0, 1) or imported.get('skipped', 0) != 0:
                        raise ValueError('unexpected single-photo import result')
                    if self._lookup(path) is None:
                        raise ValueError('imported photo absent from Lightroom')
                return path
            try:
                value = self._retry('lr_register', f.asset_id, operation, lambda: (self._lookup(path) is not None, path))
                results.append(RegisterResult(f.asset_id, value))
            except Exception as exc:
                results.append(RegisterResult(f.asset_id, error=self._error_summary(exc)))
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
