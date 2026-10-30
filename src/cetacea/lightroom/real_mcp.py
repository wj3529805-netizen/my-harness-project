import asyncio
import json
import sys
from pathlib import Path
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from .base import LightroomAdapter, RegisterResult, PresetResult, ExportResult

class RealLightroomMcpAdapter(LightroomAdapter):
    ALLOWED_TOOLS = frozenset({'import_photos', 'get_photo_metadata', 'apply_develop_preset', 'export_photos', 'list_develop_presets', 'search_photos'})
    def __init__(self, command=None, test_command=None):
        if sys.platform != 'darwin' and not (test_command or command):
            raise RuntimeError('requires macOS Lightroom Classic; explicit test command required')
        self.command = test_command or command or ['npx', '-y', '@mskalski/lightroom-mcp@0.26.0']
        self.testing = bool(test_command) or sys.platform != 'darwin'
    def status(self):
        return 'interface-level only, NOT real Lightroom' if self.testing else 'Lightroom MCP configured; awaiting real Lightroom verification'
    def call_tool(self, name, arguments):
        if name not in self.ALLOWED_TOOLS: raise ValueError('Forbidden Lightroom tool: '+name)
        if name == 'export_photos' and arguments.get('on_existing') != 'skip': raise ValueError('on_existing must be skip')
        if name == 'import_photos' and 'copy_to' in arguments: raise ValueError('copy_to forbidden')
        async def invoke():
            params = StdioServerParameters(command=self.command[0], args=self.command[1:], env={'LIGHTROOM_MCP_TOOLSETS':'develop'})
            async with stdio_client(params) as streams:
                async with ClientSession(*streams, read_timeout_seconds=10) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
                    if result.is_error: raise RuntimeError(str(result.content))
                    if result.structured_content is not None: return result.structured_content
                    return [json.loads(c.text) for c in result.content if c.type == 'text']
        return asyncio.run(invoke())
    def register(self, files):
        results = []
        for f in files:
            try:
                self.call_tool('import_photos', {'paths':[str(f.abs_path)]})
                self.call_tool('get_photo_metadata', {'photo_ids':[str(f.abs_path)]})
                results.append(RegisterResult(f.asset_id, str(f.abs_path)))
            except Exception as exc: results.append(RegisterResult(f.asset_id, error=str(exc)))
        return results
    def apply_preset(self, photo_refs, preset):
        results = []
        for f in photo_refs:
            try:
                self.call_tool('apply_develop_preset', {'photo_ids':[str(f.abs_path)], 'preset_id':preset.get('lightroom_uuid') or preset['lightroom_name']})
                results.append(PresetResult(f.asset_id))
            except Exception as exc: results.append(PresetResult(f.asset_id, str(exc)))
        return results
    def export_jpeg(self, photo_refs, dest_dir, max_edge, quality):
        results = []
        for f in photo_refs:
            try:
                sub = Path(dest_dir)/f.asset_id; sub.mkdir()
                self.call_tool('export_photos', {'photo_ids':[str(f.abs_path)], 'destination':str(sub), 'format':'jpeg', 'max_edge':max_edge, 'quality':quality, 'on_existing':'skip'})
                files = list(sub.iterdir())
                if len(files) != 1 or not files[0].is_file() or files[0].is_symlink(): raise ValueError('expected one regular exported file')
                results.append(ExportResult(f.asset_id, files[0]))
            except Exception as exc: results.append(ExportResult(f.asset_id, error=str(exc)))
        return results
