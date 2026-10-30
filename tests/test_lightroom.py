import json
import sys
from pathlib import Path
import pytest
from PIL import Image
from cetacea import db, preview
from cetacea.lightroom import MockLightroomAdapter, RealLightroomMcpAdapter, VerifiedFile
from cetacea.ingest.pathsafe import read_hash
from conftest import run

STAGES=['ingest','lr_register','lr_preset','lr_export','preview_verify']
def setup(env):
    w,c=env
    for n in range(4): (c/f'{n}.RAF').write_bytes(bytes([n])*50)
    w.add_preset('p','Mock preset')
    t=w.plan_import('order','p','card',preset_id='p',stages=STAGES)
    return w,c,t

@pytest.mark.parametrize('stage',['register','preset','export'])
def test_13_partial_failure(env,stage):
    w,c,t=setup(env); aid=t['plan']['files'][1]['asset_id']
    w.adapter.failures[stage]={aid}
    assert run(w,t)['state']=='FAILED'
    with db.connect(w.home) as conn:
        step=conn.execute('SELECT * FROM task_steps WHERE stage=?',('lr_'+stage,)).fetchone()
        assert (step['succeeded'],step['failed'],step['skipped'])==(3,1,0)
        assert conn.execute('SELECT count(*) FROM approvals WHERE revoked_at IS NULL').fetchone()[0]==1
    assert len(w.adapter.ids)==(3 if stage=='register' else 4)
    w.adapter.failures.clear()
    assert w.retry(t['task_id'])['state']=='COMPLETED'
    assert len(w.adapter.ids)==4
    if stage!='export':
        calls=[a for s,a in w.adapter.calls if s==stage]
        assert calls.count(aid)==2
        assert all(calls.count(a['asset_id'])==1 for a in w.list_assets() if a['asset_id']!=aid)
    assert w.verify_preview(t['task_id'])['status']=='OK'

def test_14_preview_mismatch_and_new_run(env):
    w,c,t=setup(env); assert run(w,t)['state']=='COMPLETED'
    with db.connect(w.home) as conn: rows=[dict(r) for r in conn.execute('SELECT * FROM previews ORDER BY asset_id')]
    Path(rows[0]['path']).unlink()
    Path(rows[1]['path']).write_bytes(b'corrupt')
    Image.new('RGB',(2000,100)).save(rows[2]['path'],'JPEG')
    directory=Path(rows[3]['path']).parent
    orphan=directory/'orphan.jpg'; Image.new('RGB',(10,10)).save(orphan)
    v=w.verify_preview(t['task_id'])
    assert v['missing']==[rows[0]['asset_id']]
    assert v['failed']==sorted([rows[1]['asset_id'],rows[2]['asset_id']])
    assert v['size_violations']==[rows[2]['asset_id']]
    assert v['orphans']==[str(orphan)] and v['status']=='FAILED'
    before={p.name:p.read_bytes() for p in directory.iterdir()}
    counts,_=w._lightroom_stage(w.get_task(t['task_id']),'lr_export')
    assert counts==(4,0,0)
    assert (directory.parent/'run-2').exists()
    assert before=={p.name:p.read_bytes() for p in directory.iterdir()}
    assert w.verify_preview(t['task_id'])['status']=='OK'

def test_full_pipeline_mock_banner_pairs_and_untouched(env):
    w,c,t=setup(env)
    (c/'0.JPG').write_bytes(b'camera jpeg')
    (c/'old.XMP').write_bytes(b'sidecar')
    t=w.plan_import('order','p','card',preset_id='p',stages=STAGES)
    before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in c.iterdir()}
    # Capture library immediately after ingest, before any Lightroom operation.
    original=w._lightroom_stage; snapshots={}
    def capture(task,stage):
        if not snapshots:
            snapshots.update({str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in Path(w.config['library_root']).rglob('*') if p.is_file()})
        return original(task,stage)
    w._lightroom_stage=capture
    assert run(w,t)['state']=='COMPLETED'
    assert before=={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in c.iterdir()}
    assert all((Path(p).read_bytes(),Path(p).stat().st_mtime_ns)==v for p,v in snapshots.items())
    assert not list(Path(w.config['preview_root']).rglob('*.xmp'))
    assert not list(Path(w.config['preview_root']).rglob('*.lrcat'))
    assert 'MOCK' in w.lightroom_status()['status']
    assert 'MOCK' in w.report(t['task_id'])['markdown']
    manifests=list(Path(w.config['preview_root']).rglob('preview-manifest.json'))
    entries=json.loads(manifests[0].read_text())['previews']
    assert len(entries)==4 and sum(bool(e['paired_jpg_asset_id']) for e in entries)==1
    for e in entries:
        assert e['mock']==1 and e['marker']=='CETACEA-MOCK'
        with Image.open(e['path']) as im:
            im.load(); assert b'CETACEA-MOCK' in im.info['comment']
    calls=list(w.adapter.calls)
    assert w.execute(t['task_id'])['state']=='COMPLETED' and calls==w.adapter.calls

def test_real_mcp_interface_only(tmp_path):
    if sys.platform!='darwin':
        with pytest.raises(RuntimeError,match='requires macOS Lightroom Classic'): RealLightroomMcpAdapter()
    adapter=RealLightroomMcpAdapter(test_command=[sys.executable,str(Path(__file__).with_name('fake_lightroom_mcp.py'))])
    assert 'NOT real Lightroom' in adapter.status()
    for name in ['remove_photos_from_catalog','reset','set_develop_settings','get_selected_photos']:
        with pytest.raises(ValueError,match='Forbidden'): adapter.call_tool(name,{})
    with pytest.raises(ValueError): adapter.call_tool('export_photos',{'on_existing':'overwrite'})
    file=tmp_path/'raw.RAF'; file.write_bytes(b'raw')
    f=VerifiedFile('ast_test',file,read_hash(file),3)
    assert adapter.register([f])[0].photo_id==str(file)
    assert adapter.apply_preset([f],{'lightroom_name':'preset'})[0].error is None
    out=tmp_path/'out'; out.mkdir()
    result=adapter.export_jpeg([f],out,1600,85)[0]
    assert result.error is None
    with Image.open(result.output_path) as im: im.load(); assert im.format=='JPEG'

def test_library_rehash_refuses_tamper(env):
    w,c,t=setup(env)
    original=w._lightroom_stage
    def tamper(task,stage):
        if stage=='lr_register':
            a=w.list_assets(task_id=task['task_id'])[0]
            Path(w.config['library_root'],a['dest_rel_path']).write_bytes(b'tampered')
        return original(task,stage)
    w._lightroom_stage=tamper
    assert run(w,t)['state']=='FAILED'
    assert len(w.adapter.ids)==3
