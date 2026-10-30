"""Preview mappings use asset IDs; names are never used to recover identity."""
import json
import os
import uuid
from pathlib import Path
from PIL import Image
from . import db
from .ingest.pathsafe import safe, read_hash

def expected(assets):
    photos = [a for a in assets if a['status']=='VERIFIED' and a['kind'] in {'raw','jpeg'}]
    raws = {str(Path(a['rel_path']).with_suffix('')):a for a in photos if a['kind']=='raw'}
    pairs = {}
    result = []
    for a in photos:
        raw = raws.get(str(Path(a['rel_path']).with_suffix('')))
        if a['kind']=='jpeg' and raw:
            pairs[raw['asset_id']] = a['asset_id']
        else: result.append(a)
    return result, pairs

def new_run(w, t):
    base = safe(w.config['preview_root'], f"{t['order_id']}/{t['photographer_id']}/{t['batch_id']}/{t['task_id']}")
    base.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        path = safe(w.config['preview_root'], str((base/f'run-{n}').relative_to(w.config['preview_root'])))
        try: path.mkdir(); return n, path
        except FileExistsError: n += 1

def persist(w, t, run, result):
    path = Path(result.output_path)
    with Image.open(path) as im:
        im.load()
        if im.format != 'JPEG': raise ValueError('not JPEG')
        width, height = im.size
    sha = read_hash(path)
    with db.connect(w.home) as c:
        c.execute('INSERT INTO previews VALUES(?,?,?,?,?,?,?,?,?,?)', ('prv_'+uuid.uuid4().hex,t['task_id'],run,result.asset_id,str(path),sha,width,height,'EXPORTED',int(result.mock)))

def manifest(w, t, run, directory, pairs):
    assets = {a['asset_id']:a for a in w.list_assets(task_id=t['task_id'])}
    with db.connect(w.home) as c: rows = [dict(r) for r in c.execute('SELECT * FROM previews WHERE task_id=? AND run=?',(t['task_id'],run))]
    for r in rows:
        a = assets[r['asset_id']]
        r.update(source_rel_path=a['rel_path'],raw_sha256=a['sha256'],paired_jpg_asset_id=pairs.get(a['asset_id']),marker='CETACEA-MOCK' if r['mock'] else 'Lightroom MCP')
    # Exclusive publication; no existing manifest is replaced.
    temp = directory/('.manifest-'+uuid.uuid4().hex)
    with temp.open('x') as f:
        json.dump({'task_id':t['task_id'],'run':run,'mock':bool(w.adapter.mock),'previews':rows},f,indent=2)
        f.flush(); os.fsync(f.fileno())
    try: os.link(temp, directory/'preview-manifest.json')
    finally: temp.unlink()

def verify(w, task_id):
    t = w.get_task(task_id)
    assets, pairs = expected(w.list_assets(task_id=task_id))
    base = safe(w.config['preview_root'], f"{t['order_id']}/{t['photographer_id']}/{t['batch_id']}/{task_id}")
    runs = [p for p in base.glob('run-*') if p.name[4:].isdigit() and not p.is_symlink()]
    directory = max(runs,key=lambda p:int(p.name[4:])) if runs else None
    run = int(directory.name[4:]) if directory else 0
    with db.connect(w.home) as c: rows = [dict(r) for r in c.execute('SELECT * FROM previews WHERE task_id=? AND run=?',(task_id,run))]
    result = dict(status='OK',mock=bool(w.adapter.mock),marker=w.adapter.status(),run=run,missing=[],failed=[],orphans=[],size_violations=[])
    cfg = w.config.get('preview', {})
    mapped = {}
    for r in rows: mapped.setdefault(r['asset_id'],[]).append(r)
    known = set()
    for a in assets:
        aid = a['asset_id']; refs = mapped.get(aid,[])
        if not refs: result['missing'].append(aid); continue
        if len(refs)!=1: result['failed'].append(aid)
        for r in refs:
            path = Path(r['path']); known.add(str(path))
            if not path.exists(): result['missing'].append(aid); continue
            try:
                if directory is None or not path.is_relative_to(directory): raise ValueError('outside preview run')
                safe(w.config['preview_root'],str(path.relative_to(w.config['preview_root'])))
                sha = read_hash(path)
                with Image.open(path) as im:
                    im.load()
                    if im.format!='JPEG': raise ValueError('not JPEG')
                    if not cfg.get('min_edge', 1) <= max(im.size) <= cfg.get('max_edge',1600): result['size_violations'].append(aid)
                if sha != r['sha256']: raise ValueError('hash mismatch')
            except Exception: result['failed'].append(aid)
    if directory:
        result['orphans'] = sorted(str(p) for p in directory.rglob('*') if p.suffix.lower() in {'.jpg','.jpeg'} and str(p) not in known)
    for key in ['missing','failed','orphans','size_violations']: result[key] = sorted(set(result[key]))
    if any(result[k] for k in ['missing','failed','orphans','size_violations']): result['status']='FAILED'
    result['expected_count']=len(assets); result['mapped_count']=len(rows)
    if len(rows)!=len(assets): result['status']='FAILED'
    return result
