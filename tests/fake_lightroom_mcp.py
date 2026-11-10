"""MOCK local batch/0.26.0 contract fixture; NOT real Lightroom."""
from pathlib import Path
import os
from PIL import Image
from mcp.server.mcpserver import MCPServer
server = MCPServer('MOCK fake Lightroom')
registered = set()


@server.tool()
def import_photos(source_path: str):
    return {'success': True, 'imported': 1, 'complete': True, 'skipped': 0}


@server.tool()
def import_photos_batch(source_paths: list[str]):
    assert 1 <= len(source_paths) <= 200
    results = []
    for path in source_paths:
        status = 'existing' if path in registered else 'added'
        registered.add(path)
        results.append({'path': path, 'status': status})
    return {'success': True, 'complete': True, 'results': results, 'marker': 'CETACEA-MOCK', 'mock_process_id': os.getpid()}


@server.tool()
def get_photo_metadata(photo_ids: list[str]):
    return {'photos': [{'id': n + 1, 'path': p, 'isVirtualCopy': False} for n, p in enumerate(photo_ids)], 'missing': [], 'marker': 'CETACEA-MOCK', 'mock_process_id': os.getpid()}


@server.tool()
def apply_develop_preset(photo_ids: list[str], preset_name: str | None = None, preset_uuid: str | None = None):
    assert bool(preset_name) != bool(preset_uuid)
    return {'success': True, 'applied': len(photo_ids), 'preset': preset_name or 'fixture', 'uuid': preset_uuid or 'fixture-uuid', 'missing': [], 'ai_update_failed': []}


@server.tool()
def export_photos(photo_ids: list[str], destination: str, format: str, width: int, height: int, quality: int, on_existing: str):
    assert on_existing == 'skip' and format == 'jpeg'
    path = Path(destination) / 'export.jpg'
    with path.open('xb') as out:
        Image.new('RGB', (min(width, 600), min(height, 400))).save(out, 'JPEG')
    return {'success': True, 'exported': len(photo_ids), 'complete': True, 'destination': destination}


@server.tool()
def list_develop_presets(limit: int = 100):
    return {'success': True, 'presets': [], 'count': 0, 'has_more': False}


@server.tool()
def search_photos(filename: str, include_path: bool = False, limit: int = 100):
    return {'photos': [], 'count': 0}


@server.tool()
def remove_photos_from_catalog(photo_ids: list[str]):
    raise AssertionError('FORBIDDEN tool invoked')


if __name__ == '__main__':
    server.run()
