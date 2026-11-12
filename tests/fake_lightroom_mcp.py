"""MOCK local batch/0.26.0 contract fixture; NOT real Lightroom."""
from pathlib import Path
import argparse
import os
import sqlite3
import threading
from PIL import Image
from mcp.server.mcpserver import MCPServer
server = MCPServer('MOCK fake Lightroom')
registered = set()
catalog = None
crash_batch = None
crash_after = None
catalog_lock = threading.Lock()


def open_mock_catalog(path):
    """Persist only synthetic MOCK state so a killed bridge can be restarted."""
    # MCP dispatches synchronous tools to worker threads; serialize their use
    # of this process-local connection while catalog state survives restarts.
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS mock_photos (
            id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS mock_batches (
            id INTEGER PRIMARY KEY, requested INTEGER NOT NULL,
            complete INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS mock_control (
            name TEXT PRIMARY KEY, value TEXT NOT NULL
        );
    ''')
    connection.execute("INSERT OR IGNORE INTO mock_control VALUES ('marker', 'CETACEA-MOCK')")
    connection.commit()
    return connection


@server.tool()
def import_photos(source_path: str):
    return {'success': True, 'imported': 1, 'complete': True, 'skipped': 0}


@server.tool()
def import_photos_batch(source_paths: list[str]):
    with catalog_lock:
        return _import_photos_batch(source_paths)


def _import_photos_batch(source_paths):
    assert 1 <= len(source_paths) <= 200
    results = []
    batch_id = None
    if catalog is not None:
        cursor = catalog.execute('INSERT INTO mock_batches(requested) VALUES (?)', (len(source_paths),))
        batch_id = cursor.lastrowid
        catalog.commit()
    for index, path in enumerate(source_paths, 1):
        if catalog is None:
            status = 'existing' if path in registered else 'added'
            registered.add(path)
        else:
            present = catalog.execute('SELECT id FROM mock_photos WHERE path = ?', (path,)).fetchone()
            status = 'existing' if present else 'added'
            if not present:
                catalog.execute('INSERT INTO mock_photos(path) VALUES (?)', (path,))
            # Deliberately persist individual additions before killing the
            # process: a dropped reply must not erase catalog membership.
            catalog.commit()
        results.append({'path': path, 'status': status})
        if batch_id == crash_batch and index == crash_after:
            crashed = catalog.execute("SELECT value FROM mock_control WHERE name = 'crashed'").fetchone()
            if not crashed:
                catalog.execute("INSERT INTO mock_control VALUES ('crashed', 'CETACEA-MOCK')")
                catalog.commit()
                os._exit(86)  # MOCK abrupt plug-in/bridge death; no MCP reply.
    if catalog is not None:
        catalog.execute('UPDATE mock_batches SET complete = 1 WHERE id = ?', (batch_id,))
        catalog.commit()
    return {'success': True, 'complete': True, 'results': results, 'marker': 'CETACEA-MOCK', 'mock_process_id': os.getpid()}


@server.tool()
def get_photo_metadata(photo_ids: list[str]):
    with catalog_lock:
        return _get_photo_metadata(photo_ids)


def _get_photo_metadata(photo_ids):
    if catalog is not None:
        photos, missing = [], []
        for path in photo_ids:
            row = catalog.execute('SELECT id FROM mock_photos WHERE path = ?', (path,)).fetchone()
            if row:
                photos.append({'id': row[0], 'path': path, 'isVirtualCopy': False})
            else:
                missing.append(path)
        return {'photos': photos, 'missing': missing, 'marker': 'CETACEA-MOCK', 'mock_process_id': os.getpid()}
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog-state', type=Path)
    parser.add_argument('--crash-batch', type=int)
    parser.add_argument('--crash-after', type=int)
    args = parser.parse_args()
    if args.crash_batch is not None or args.crash_after is not None:
        if (args.catalog_state is None or args.crash_batch is None or args.crash_batch < 1
                or args.crash_after is None or args.crash_after < 1):
            parser.error('MOCK crash requires catalog-state and positive crash-batch/crash-after')
    if args.catalog_state is not None:
        catalog = open_mock_catalog(args.catalog_state)
    crash_batch, crash_after = args.crash_batch, args.crash_after
    server.run()
