"""Local interface fixture only; NOT real Lightroom."""
from pathlib import Path
from PIL import Image
from mcp.server.mcpserver import MCPServer
server = MCPServer('fake Lightroom')
@server.tool()
def import_photos(paths: list[str]):
    return {'imported':paths}
@server.tool()
def get_photo_metadata(photo_ids: list[str]):
    return {'photos':photo_ids}
@server.tool()
def apply_develop_preset(photo_ids: list[str], preset_id: str):
    return {'applied':photo_ids}
@server.tool()
def export_photos(photo_ids: list[str], destination: str, format: str, max_edge: int, quality: int, on_existing: str):
    assert on_existing == 'skip'
    path=Path(destination)/'export.jpg'
    with path.open('xb') as out: Image.new('RGB',(600,400)).save(out,'JPEG')
    return {'outputs':[str(path)]}
@server.tool()
def list_develop_presets(): return {'presets':[]}
@server.tool()
def search_photos(query: str): return {'photos':[]}
@server.tool()
def remove_photos_from_catalog(photo_ids: list[str]):
    raise AssertionError('FORBIDDEN tool invoked')
if __name__=='__main__':
    server.run()
