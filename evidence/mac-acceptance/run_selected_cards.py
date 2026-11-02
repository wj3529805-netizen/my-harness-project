"""Physical card read-only selected-file ingest; never scan other card photos."""
import hashlib,json,os,plistlib,subprocess
from pathlib import Path
from cetacea.core import Workbench
from cetacea.ingest.pathsafe import read_hash
from cetacea.perms import NotApproved
ROOT=Path(__file__).resolve().parents[2]
META=json.loads((ROOT/'acceptance-data/device-active.json').read_text())
OUT=Path(META['evidence_root']); STATE=Path(META['local_state_root'])

def snap(p):
 s=p.stat(); return {'size':s.st_size,'mtime_ns':s.st_mtime_ns,'inode':s.st_ino,'sha256':read_hash(p)}
def main():
 target=STATE/'local-card-ingest'
 w=Workbench.init(target/'home',target/'library',target/'preview')
 w.create_order('physical','Read-only physical card samples');w.add_photographer('tester','Test operator')
 results=[]
 for src in META['selected_sources']:
  info=plistlib.loads(subprocess.check_output(['diskutil','info','-plist',src['volume']['MountPoint']]))
  assert info['VolumeUUID']==src['volume']['VolumeUUID'] and Path(info['MountPoint']).is_mount()
  p=Path(src['path']); before=snap(p); w.add_source(src['source_id'],p.parent)
  item={'rel_path':p.name,'size':before['size'],'sha256':before['sha256'],'kind':'raw'}
  # Workbench supports a precomputed scan. Bound this real read/hash to the
  # explicitly chosen file; do not hash every other photo in its DCIM folder.
  scan={'files':[item],'skipped':[],'digest':hashlib.sha256(json.dumps([(item['rel_path'],item['size'],item['sha256'])],separators=(',',':')).encode()).hexdigest()}
  t=w.plan_import('physical','tester',src['source_id'],batch_label=src['source_id'],scan_result=scan)
  existing={str(p.relative_to(target/'library')):snap(p) for p in (target/'library').rglob('*') if p.is_file()}
  try: w.execute(t['task_id']); raise AssertionError('Unapproved execution succeeded')
  except NotApproved: pass
  assert existing=={str(p.relative_to(target/'library')):snap(p) for p in (target/'library').rglob('*') if p.is_file()}
  w.approve(t['task_id'],t['plan_digest'])
  r=w.execute(t['task_id']); assert r['state']=='COMPLETED',r['error']
  a=w.list_assets(task_id=t['task_id'])[0]; dest=target/'library'/a['dest_rel_path']
  first=snap(dest); assert first['sha256']==before['sha256'] and a['status']=='VERIFIED'
  assert w.execute(t['task_id'])['state']=='COMPLETED' and snap(dest)==first
  after=snap(p);assert before==after
  results.append({'source_id':src['source_id'],'source_volume':src['volume'],'source_selected':str(p),'scan_scope':'bounded precomputed scan of one selected file; full-card recursive scan NOT_RUN','task_id':t['task_id'],'state':r['state'],'before':before,'after':after,'destination':str(dest),'destination_readback':first,'repeat_unchanged':True,'unapproved_rejected':True})
 (OUT/'physical-to-local-apfs.json').write_text(json.dumps({'result':'PASS','ingest_uses_real_devices':True,'lightroom':'NOT_RUN','results':results},indent=2))
 print(json.dumps({'result':'PASS','selected_cards':len(results),'source_unchanged':True,'destination_sha256_readback':True,'full_card_scan':'NOT_RUN'}))
if __name__=='__main__': main()
