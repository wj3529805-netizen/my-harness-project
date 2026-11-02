"""A12: pause between RAWs, quit test Lightroom, release gate, reopen and retry."""
import json,shutil,sys,time
from pathlib import Path
from run_real_validation import ROOT,DATA,OUT,Capture,workbench,snapshot,save
from cetacea import db
READY=OUT/'interruption-ready.json'; GATE=OUT/'interruption-continue'

def start():
    w=workbench(); source=DATA/'interrupt-card'
    if not source.exists():
        source.mkdir()
        for n in range(3): shutil.copyfile(DATA/'card-cc0/Nikon-Z6.NEF',source/f'CETACEA_INTERRUPT_{n+1:02}.NEF')
        w.add_source('interrupt',source)
    save('interruption-source-before.json',snapshot(source))
    t=w.plan_import('test','tester','interrupt',batch_label='interrupted',stages=['ingest','lr_register'])
    save('interruption-plan.json',t)
    assert t['state']=='WAITING_APPROVAL',t['state']
    w.approve(t['task_id'],t['plan_digest'])
    original=w.adapter.register; calls=0
    def register(files):
        nonlocal calls
        calls+=1
        if calls==2:
            first=[a for a in w.list_assets(task_id=t['task_id']) if a['lr_photo_id']]
            assert len(first)==1
            save('interruption-library-before.json',snapshot(DATA/'library/test/tester/interrupted'))
            save(READY.name,{'task_id':t['task_id'],'registered_before_quit':first,'next_path':str(files[0].abs_path)})
            print('READY_TO_QUIT_TEST_LIGHTROOM',flush=True)
            deadline=time.monotonic()+180
            while not GATE.exists():
                if time.monotonic()>deadline: raise TimeoutError('A12 gate not released')
                time.sleep(.2)
        return original(files)
    w.adapter.register=register
    r=w.execute(t['task_id']); save('interruption-failed-result.json',r)
    assert r['state'] in {'FAILED','PAUSED'},r['state']
    assets=w.list_assets(task_id=t['task_id']); save('interruption-assets-after-close.json',assets)
    assert sum(bool(a['lr_photo_id']) for a in assets)==1
    print(json.dumps({'state':r['state'],'registered':sum(bool(a['lr_photo_id']) for a in assets)}),flush=True)

def retry():
    w=workbench(); tid=json.loads((OUT/'interruption-plan.json').read_text())['task_id']
    r=w.retry(tid); save('interruption-retry-result.json',r)
    assert r['state']=='COMPLETED',r['error']
    assets=w.list_assets(task_id=tid)
    photo_set=w.adapter.call_tool('search_photos',{'filename':'CETACEA_INTERRUPT','limit':100})
    with db.connect(w.home) as c: steps=[dict(row) for row in c.execute('SELECT * FROM task_steps WHERE task_id=? ORDER BY run,stage',(tid,))]
    result={'state':r['state'],'assets':assets,'steps':steps,'catalog_search':photo_set,'source_unchanged':snapshot(DATA/'interrupt-card')==json.loads((OUT/'interruption-source-before.json').read_text()),'library_unchanged':snapshot(DATA/'library/test/tester/interrupted')==json.loads((OUT/'interruption-library-before.json').read_text())}
    save('interruption-checks.json',result)
    assert all(a['lr_photo_id'] for a in assets) and len(assets)==3
    assert result['source_unchanged'] and result['library_unchanged']
    assert photo_set['count']==3 and len({p['id'] for p in photo_set['photos']})==3
    last=[s for s in steps if s['stage']=='lr_register' and s['run']==r['run_count']][0]
    assert (last['succeeded'],last['failed'],last['skipped'])==(2,0,1),last
    print(json.dumps({'state':r['state'],'registered':len(assets),'retry_succeeded':last['succeeded'],'retry_skipped':last['skipped'],'catalog_count':photo_set['count'],'source_unchanged':result['source_unchanged'],'library_unchanged':result['library_unchanged']}),flush=True)

if __name__=='__main__': {'start':start,'retry':retry}[sys.argv[1]]()
