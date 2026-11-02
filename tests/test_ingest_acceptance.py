import errno
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from cetacea.core import Workbench
from cetacea.ingest.pathsafe import relative, safe, disjoint
from conftest import run

def test_01_normal(env):
    w,card=env
    for n in range(10):
        p=card/str(n%2)/f'DSC{n:04}.{ "RAF" if n%2 else "JPG"}'; p.parent.mkdir(exist_ok=True); p.write_bytes(os.urandom(100))
    before={str(p.relative_to(card)):(p.read_bytes(),p.stat().st_mtime_ns) for p in card.rglob('*') if p.is_file()}
    t=run(w,w.plan_import('order','p','card')); assert t['state']=='COMPLETED'
    assets=w.list_assets(t['task_id']); assert len(assets)==10 and all(a['status']=='VERIFIED' for a in assets)
    for a in assets: assert (Path(w.config['library_root'])/a['dest_rel_path']).read_bytes()==before[a['rel_path']][0]
    assert list(Path(w.config['library_root']).rglob('import-manifest-run1.json'))
    assert before=={str(p.relative_to(card)):(p.read_bytes(),p.stat().st_mtime_ns) for p in card.rglob('*') if p.is_file()}

def test_02_subdirs(env):
    w,c=env
    for d in ['a','b']: (c/d).mkdir(); (c/d/'same.RAF').write_bytes(os.urandom(20))
    t=run(w,w.plan_import('order','p','card')); assert len(w.list_assets(t['task_id']))==2
    assert len(list(Path(w.config['library_root']).rglob('same.RAF')))==2

def test_03_photographers(planned):
    w,t=planned; run(w,t); w.add_photographer('q','Q'); Path(w.config['sources']['card']['path'],'DSC0001.RAF').write_bytes(b'other')
    q=run(w,w.plan_import('order','q','card')); a=w.list_assets(t['task_id'])[0]; b=w.list_assets(q['task_id'])[0]
    assert a['asset_id']!=b['asset_id'] and a['dest_rel_path']!=b['dest_rel_path']

def test_04_identity(planned):
    w,t=planned; t=w.plan_import('order','p','card',batch_label='fixed'); run(w,t)
    a=w.list_assets(t['task_id'])[0]; dest=Path(w.config['library_root'])/a['dest_rel_path']; original=dest.read_bytes()
    Path(w.config['sources']['card']['path'],'DSC0001.RAF').write_bytes(b'changed')
    other=run(w,w.plan_import('order','p','card',batch_label='fixed')); assert other['state']=='FAILED' and 'IDENTITY_CONFLICT' in other['error']; assert dest.read_bytes()==original

def existing_destination(planned,correct):
    w,t=planned; item=t['plan']['files'][0]; dest=Path(w.config['library_root'])/item['dest_rel_path']; dest.parent.mkdir(parents=True)
    content=Path(w.config['sources']['card']['path'],item['rel_path']).read_bytes(); dest.write_bytes(content if correct else bytes(x^255 for x in content)); stat=dest.stat()
    result=run(w,t); assert result['state']==('COMPLETED' if correct else 'FAILED'); assert dest.stat().st_ino==stat.st_ino and dest.stat().st_mtime_ns==stat.st_mtime_ns
    assert w.list_assets(t['task_id'])[0]['status']==('VERIFIED' if correct else 'CONFLICT')
    if correct:
        from cetacea.db import connect
        with connect(w.home) as c: assert c.execute('SELECT skipped FROM task_steps').fetchone()[0]==1

@pytest.mark.parametrize('stage',['after_temp_write','before_commit'])
def test_07_interrupt(planned,stage):
    w,t=planned
    def fault(s,r):
        if s==stage: raise RuntimeError('interrupt')
    w.engine.fault_hook=fault; assert run(w,t)['state']=='FAILED'; assert not list(Path(w.config['library_root']).rglob('*.RAF'))
    w.engine.fault_hook=lambda *a:None; assert w.retry(t['task_id'])['state']=='COMPLETED'; assert len(list(Path(w.config['library_root']).rglob('*.RAF')))==1; assert not list(Path(w.config['library_root']).rglob('*.part'))

@pytest.mark.parametrize('preflight',[True,False])
def test_08_space(planned,preflight):
    w,t=planned
    if preflight: w.disk_usage=lambda p:SimpleNamespace(free=0)
    else:
        def fault(s,r):
            if s=='after_temp_write': raise OSError(errno.ENOSPC,'full')
        w.engine.fault_hook=fault
    result=run(w,t); assert result['state']=='FAILED' and ('INSUFFICIENT_SPACE' if preflight else 'ENOSPC') in result['error']; assert not list(Path(w.config['library_root']).rglob('*.RAF')); assert not list(Path(w.config['library_root']).rglob('*.part'))

def test_09_read_error(env,monkeypatch):
    w,c=env
    for name in ['a.RAF','b.RAF']: (c/name).write_bytes(os.urandom(20))
    t=w.plan_import('order','p','card'); original=os.open
    def opened(path,flags,*args,**kwargs):
        if Path(path)==c/'a.RAF': raise OSError(errno.EIO,'read failure')
        return original(path,flags,*args,**kwargs)
    monkeypatch.setattr(os,'open',opened); result=run(w,t); assert result['state']=='FAILED'
    assert sorted(a['status'] for a in w.list_assets(t['task_id']))==['FAILED','VERIFIED']; assert len(list(c.iterdir()))==2

def test_10_paths(env,tmp_path):
    w,c=env; outside=tmp_path/'out'; outside.write_bytes(b'secret'); (c/'link').symlink_to(outside); (c/'dir').symlink_to(tmp_path,target_is_directory=True)
    scan=w.scan_source('card'); assert not scan['files'] and len(scan['skipped'])==2
    for p in ['../x','/x','a/../x']:
        with pytest.raises(ValueError): relative(p)
    for a,b in [(c,c/'child'),(c/'child',c)]:
        with pytest.raises(ValueError): disjoint(a,b)
    library=Path(w.config['library_root']); (library/'link').symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError): safe(library,'link/file')
    for field in ['order_id','photographer_id','batch_label']:
        args={'order_id':'order','photographer_id':'p','source_id':'card','batch_label':'batch'}; args[field]='../bad'
        with pytest.raises(ValueError): w.plan_import(**args)

def test_08_mid_write(planned,monkeypatch):
    w,t=planned; original=os.fdopen
    class Full:
        def __init__(self,f): self.f=f
        def __enter__(self): return self
        def __exit__(self,*args): self.f.close()
        def write(self,block): self.f.write(block[:2]); raise OSError(errno.ENOSPC,'mid write')
    def opened(fd,mode):
        f=original(fd,mode)
        return Full(f) if mode=='wb' else f
    monkeypatch.setattr(os,'fdopen',opened)
    assert run(w,t)['state']=='FAILED'; assert w.list_assets(t['task_id'])[0]['status']=='FAILED'
    assert not list(Path(w.config['library_root']).rglob('*.part')); assert not list(Path(w.config['library_root']).rglob('*.RAF'))

def test_hardlink_fallback(planned,monkeypatch):
    w,t=planned; original=os.link
    def link(a,b):
        if str(b).endswith('.RAF'): raise OSError(errno.EOPNOTSUPP,'unsupported')
        return original(a,b)
    monkeypatch.setattr(os,'link',link); assert run(w,t)['state']=='COMPLETED'
    assert not list(Path(w.config['library_root']).rglob('*.cetacea-lock'))

@pytest.mark.parametrize('correct', [True, False])
def test_existing_destination_without_hardlinks(planned, monkeypatch, correct):
    def unsupported_link(source, destination):
        raise OSError(errno.EOPNOTSUPP, 'filesystem has no hard links')
    monkeypatch.setattr(os, 'link', unsupported_link)
    existing_destination(planned, correct)
    assert not list(Path(planned[0].config['library_root']).rglob('*.cetacea-lock'))


def test_05_existing_correct(planned): existing_destination(planned,True)

def test_06_existing_conflict(planned): existing_destination(planned,False)

def test_source_changed(planned):
    w,t=planned; Path(w.config['sources']['card']['path'],'DSC0001.RAF').write_bytes(b'changed after plan')
    result=run(w,t); assert result['state']=='FAILED' and 'SOURCE_CHANGED' in result['error']
    assert not list(Path(w.config['library_root']).rglob('*.RAF'))

def test_resume_rehashes_existing(planned):
    w,t=planned
    def fault(stage,rel):
        if stage=='after_commit': raise RuntimeError('crash after commit')
    w.engine.fault_hook=fault; assert run(w,t)['state']=='FAILED'
    dest=Path(w.config['library_root'])/t['plan']['files'][0]['dest_rel_path']; dest.write_bytes(b'corrupt')
    w.engine.fault_hook=lambda *a:None; result=w.retry(t['task_id'])
    assert result['state']=='FAILED' and 'CONFLICT' in result['error']; assert dest.read_bytes()==b'corrupt'
