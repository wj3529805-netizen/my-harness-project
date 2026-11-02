"""Use only already-ingested test copies on external APFS; do not alter cards.
Requires the same dedicated test Lightroom catalog. Store only reduced photo
metadata in evidence; no GPS/contact/caption fields or photo bytes in Git.
"""
import hashlib,json,subprocess
from pathlib import Path
from cetacea.core import Workbench
from cetacea import config
from cetacea.ingest.pathsafe import read_hash
from cetacea.lightroom import RealLightroomMcpAdapter
from run_device_filesystem import validate_volume,snapshot_file
from run_real_validation import workbench as validate_catalog
ROOT=Path(__file__).resolve().parents[2]
META=json.loads((ROOT/'acceptance-data/device-active.json').read_text());OUT=Path(META['evidence_root'])
class Capture(RealLightroomMcpAdapter):
 def call_tool(self,name,args):
  entry={'tool':name,'arguments':args}
  try:
   r=super().call_tool(name,args)
   if name=='get_photo_metadata':
    entry['result']={'missing':r.get('missing'),'photos':[{k:p.get(k) for k in ['id','path','isVirtualCopy','cameraModel','dimensions','fileFormat','filename','developSettings'] if k in p} for p in r.get('photos',[])]}
   else:entry['result']=r
   return r
  except Exception as exc:entry['error']=self._error_summary(exc);raise
  finally:
   with (OUT/'physical-lightroom-calls.jsonl').open('a') as f:f.write(json.dumps(entry)+'\n')

def main():
 validate_catalog() # no photo operation: confirms exact lsof catalog identity
 validate_volume(META['external_volume'],'apfs')
 ingest=json.loads(sorted(OUT.glob('apfs-ingest-*.json'))[-1].read_text());assert ingest['status']=='PASS'
 home=Path(ingest['local_state'])/'home';cfg=config.load(home)
 cmd=['/opt/homebrew/bin/node',str(ROOT.parent/'cetacea-workbench/.lightroom-runtime/node_modules/@mskalski/lightroom-mcp/dist/index.js')]
 cfg['lightroom']={'adapter':'real_mcp','command':cmd};config.save(home,cfg)
 w=Workbench(home,adapter=Capture(command=cmd))
 if 'devicepreset' not in w.config['presets']:w.add_preset('devicepreset','Cetacea Phase1 Test +0.50',lightroom_name='Cetacea Phase1 Test +0.50')
 results=[]
 for original in ingest['results']:
  validate_volume(META['external_volume'],'apfs');source=next(s for s in META['selected_sources'] if s['source_id']==original['source_id']);validate_volume(source['volume'],'exfat')
  source_path=Path(source['path']);source_before=snapshot_file(source_path)
  file=original['task']['plan']['files'][0]
  dest=Path(w.config['library_root'])/file['dest_rel_path'];before=snapshot_file(dest)
  scan={'files':[{k:file[k] for k in ['rel_path','size','sha256','kind']}],'skipped':[],'digest':original['task']['plan']['scan_digest']}
  task=w.plan_import('test','tester',original['source_id'],batch_label=original['source_id'],preset_id='devicepreset',stages=['lr_register','lr_preset','lr_export','preview_verify'],scan_result=scan)
  if task['state']=='WAITING_APPROVAL':w.approve(task['task_id'],task['plan_digest'])
  result=w.retry(task['task_id']) if task['state']=='FAILED' else w.execute(task['task_id'])
  row={'source_id':source['source_id'],'task_id':task['task_id'],'state':result['state'],'error':result['error']}
  if result['state']!='COMPLETED':
   results.append(row);(OUT/'physical-lightroom-result.json').write_text(json.dumps({'result':'FAIL','results':results},indent=2));raise AssertionError(result['error'])
  metadata=w.adapter.call_tool('get_photo_metadata',{'photo_ids':[str(dest)],'sections':['developSettings']})
  assert metadata['photos'][0]['developSettings']['exposure']==0.5
  assert snapshot_file(dest)==before and snapshot_file(source_path)==source_before
  preview=w.verify_preview(task['task_id']);assert preview['status']=='OK' and preview['mock'] is False
  from cetacea import db
  from PIL import Image
  with db.connect(home) as c:exports=[dict(r) for r in c.execute('SELECT * FROM previews WHERE task_id=?',(task['task_id'],))]
  assert len(exports)==1
  with Image.open(exports[0]['path']) as im:
   im.load();dims=im.size;assert im.format=='JPEG' and max(dims)<=1600
  assert read_hash(exports[0]['path'])==exports[0]['sha256']
  row.update(source_unchanged=True,library_copy_unchanged=True,jpeg_dimensions=dims,jpeg_sha256=exports[0]['sha256'],mock=False,preview=preview,camera_model=metadata['photos'][0]['cameraModel'],exposure_readback=0.5,raw_compression_variant='NOT_INDEPENDENTLY_IDENTIFIED')
  results.append(row)
  (OUT/'physical-lightroom-result.json').write_text(json.dumps({'result':'PASS_SO_FAR','results':results},indent=2))
  print(json.dumps(row),flush=True)
 (OUT/'physical-lightroom-result.json').write_text(json.dumps({'result':'PASS','results':results,'catalog':'designated independent test catalog','raw_files_uploaded':False},indent=2))
if __name__=='__main__':main()
