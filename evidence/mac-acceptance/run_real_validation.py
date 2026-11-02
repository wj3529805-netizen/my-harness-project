"""Manual-triggered, local test-catalog acceptance; never use customer data.
Uses this repository's code and the sibling scratch runtime. Requires Lightroom
already switched to the catalog created for this validation; does not open lrcat.
"""
import hashlib,json,os,sys,time,subprocess
import cetacea
from pathlib import Path
from cetacea.core import Workbench
from cetacea import config,db
from cetacea.lightroom import RealLightroomMcpAdapter
ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'acceptance-data'; OUT=ROOT/'evidence/mac-acceptance'
assert Path(cetacea.__file__).resolve().is_relative_to(ROOT/'src'), 'Wrong checkout imported'
RUNTIME=ROOT.parent/'cetacea-workbench/.lightroom-runtime/node_modules/@mskalski/lightroom-mcp/dist/index.js'

def save(name,value): (OUT/name).write_text(json.dumps(value,indent=2,default=str))
def snapshot(root):
    return {str(p.relative_to(root)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'mtime_ns':p.stat().st_mtime_ns,'inode':p.stat().st_ino} for p in root.rglob('*') if p.is_file()}
def sidecars():
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for base in [DATA/'card-cc0',DATA/'library'] for p in base.rglob('*') if p.is_file() and p.suffix.lower() in {'.xmp','.acr'}}
class Capture(RealLightroomMcpAdapter):
    def call_tool(self,name,args):
        start=time.time(); entry={'tool':name,'arguments':args}
        try:
            r=super().call_tool(name,args); entry['result']=r
            return r
        except Exception as exc:
            entry['error']=self._error_summary(exc); raise
        finally:
            entry['seconds']=time.time()-start
            with (OUT/'real-cc0-calls.jsonl').open('a') as f: f.write(json.dumps(entry)+'\n')

def workbench():
    expected=ROOT.parent/'cetacea-workbench/acceptance-data/catalog/Cetacea-Phase1-Test-20261102/Cetacea-Phase1-Test-20261102.lrcat'
    pids=subprocess.check_output(['pgrep','-x','Adobe Lightroom Classic'],text=True).split()
    assert len(pids)==1, 'Ambiguous Lightroom process'
    descriptors=subprocess.check_output(['lsof','-p',pids[0],'-Fn'],text=True)
    catalogs={line[1:] for line in descriptors.splitlines() if line.startswith('n') and line.endswith('.lrcat')}
    assert catalogs=={str(expected)}, 'Lightroom is not using the designated test catalog'
    cmd=['/opt/homebrew/bin/node',str(RUNTIME)]
    if not (DATA/'home/config.json').exists():
        Workbench.init(DATA/'home',DATA/'library',DATA/'preview')
        c=config.load(DATA/'home'); c['lightroom']={'adapter':'real_mcp','command':cmd}; config.save(DATA/'home',c)
        w=Workbench(DATA/'home'); w.add_source('cc0',DATA/'card-cc0'); w.create_order('test','CC0 RAW validation only'); w.add_photographer('tester','Test operator')
        w.add_preset('testpreset','Cetacea Phase1 Test +0.50',lightroom_name='Cetacea Phase1 Test +0.50')
    w=Workbench(DATA/'home',adapter=Capture(command=cmd))
    assert Path(w.config['library_root']).resolve()==(DATA/'library').resolve()
    assert Path(w.config['preview_root']).resolve()==(DATA/'preview').resolve()
    assert Path(w.config['sources']['cc0']['path']).resolve()==(DATA/'card-cc0').resolve()
    return w

def initial():
    w=workbench(); before=snapshot(DATA/'card-cc0'); side_before=sidecars()
    save('source-before.json',before)
    t=w.plan_import('test','tester','cc0',batch_label='publicraw',stages=['ingest','lr_register'])
    save('cc0-plan.json',t)
    # User-authorized synthetic/public-test-data acceptance uses CLI test-operator
    # approval; the AI stdio principal is separately proved unable to approve.
    if t['state']=='WAITING_APPROVAL': w.approve(t['task_id'],t['plan_digest'])
    r=w.retry(t['task_id']) if t['state']=='FAILED' else w.execute(t['task_id'])
    save('cc0-register-result.json',r)
    assets=w.list_assets(task_id=t['task_id']); save('cc0-assets.json',assets)
    checks={'state':r['state'],'error':r['error'],'source_unchanged':snapshot(DATA/'card-cc0')==before,'sidecars_unchanged':sidecars()==side_before,'destination_hashes_match':all(hashlib.sha256((DATA/'library'/a['dest_rel_path']).read_bytes()).hexdigest()==a['sha256'] for a in assets)}
    save('cc0-register-checks.json',checks); print(json.dumps(checks),flush=True)
    assert checks['state']=='COMPLETED' and checks['source_unchanged'] and checks['sidecars_unchanged'] and checks['destination_hashes_match'], checks

def finish():
    w=workbench(); before=snapshot(DATA/'card-cc0'); side_before=sidecars()
    path=str(DATA/'library/test/tester/publicraw/Nikon-Z6.NEF')
    save('develop-before.json',w.adapter.call_tool('get_photo_metadata',{'photo_ids':[path],'sections':['developSettings']}))
    t=w.plan_import('test','tester','cc0',batch_label='publicraw',preset_id='testpreset',stages=['ingest','lr_register','lr_preset','lr_export','preview_verify'])
    save('cc0-full-plan.json',t)
    if t['state']=='WAITING_APPROVAL': w.approve(t['task_id'],t['plan_digest'])
    r=w.retry(t['task_id']) if t['state']=='FAILED' else w.execute(t['task_id'])
    save('cc0-full-result.json',r)
    save('develop-after.json',w.adapter.call_tool('get_photo_metadata',{'photo_ids':[path],'sections':['developSettings']}))
    report=w.report(t['task_id']); save('cc0-full-report.json',report)
    prior={str(p):v for root in [DATA/'library',DATA/'preview'] for p,v in [(root/s,meta) for s,meta in snapshot(root).items()]}
    repeated=w.plan_import('test','tester','cc0',batch_label='publicraw',preset_id='testpreset',stages=['ingest','lr_register','lr_preset','lr_export','preview_verify'])
    w.execute(t['task_id'])
    after={str(p):v for root in [DATA/'library',DATA/'preview'] for p,v in [(root/s,meta) for s,meta in snapshot(root).items()]}
    checks={'state':r['state'],'error':r['error'],'source_unchanged':snapshot(DATA/'card-cc0')==before,'sidecars_unchanged':sidecars()==side_before,'preview':w.verify_preview(t['task_id']),'same_task':repeated['task_id']==t['task_id'],'repeat_files_unchanged':prior==after,'assets':w.list_assets(task_id=t['task_id'])}
    save('cc0-full-checks.json',checks); print(json.dumps(checks),flush=True)
    assert checks['state']=='COMPLETED' and checks['source_unchanged'] and checks['sidecars_unchanged'] and checks['same_task'] and checks['repeat_files_unchanged'] and checks['preview']['status']=='OK', checks
    assert json.loads((OUT/'develop-after.json').read_text())['photos'][0]['developSettings']['exposure']==0.5

if __name__=='__main__': {'initial':initial,'finish':finish}[sys.argv[1]]()
