import fnmatch
from pathlib import Path
from PIL import Image, ImageDraw
from .base import LightroomAdapter, RegisterResult, PresetResult, ExportResult

class MockLightroomAdapter(LightroomAdapter):
    mock = True
    def __init__(self, failures=None, size=(1200, 800)):
        self.failures = failures or {}
        self.size = size
        self.files = {}
        self.ids = {}
        self.calls = []
    def status(self): return 'MOCK — not real Lightroom'
    def _fail(self, stage, f):
        self.calls.append((stage, f.asset_id))
        return any(p == f.asset_id or fnmatch.fnmatch(f.rel_path, p) for p in self.failures.get(stage, set()))
    def register(self, files):
        results = []
        for f in files:
            if self._fail('register', f):
                results.append(RegisterResult(f.asset_id, error='MOCK injected register failure', mock=True)); continue
            self.files[f.asset_id] = f
            self.ids.setdefault(f.asset_id, f'mock-lr-{len(self.ids)+1}')
            results.append(RegisterResult(f.asset_id, self.ids[f.asset_id], mock=True))
        return results
    def apply_preset(self, photo_refs, preset):
        return [PresetResult(f.asset_id, 'MOCK injected preset failure' if self._fail('preset', f) else None, True) for f in photo_refs]
    def export_jpeg(self, photo_refs, dest_dir, max_edge=1600, quality=85):
        results = []
        for f in photo_refs:
            if self._fail('export', f):
                results.append(ExportResult(f.asset_id, error='MOCK injected export failure', mock=True)); continue
            try:
                path = Path(dest_dir)/f'{f.order}_{f.photographer}_{Path(f.rel_path).stem}_{f.asset_id[4:12]}.jpg'
                im = Image.new('RGB', self.size, tuple(bytes.fromhex(f.sha256[:6])))
                im.thumbnail((max_edge, max_edge))
                marker = f'CETACEA-MOCK asset_id={f.asset_id}'
                ImageDraw.Draw(im).text((10, 10), marker, fill='white')
                with path.open('xb') as out: im.save(out, 'JPEG', quality=quality, comment=marker.encode())
                results.append(ExportResult(f.asset_id, path, mock=True))
            except Exception as exc: results.append(ExportResult(f.asset_id, error=f'MOCK {exc}', mock=True))
        return results
