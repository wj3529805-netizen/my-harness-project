import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from . import config, db
from .audit import now, record
from .perms import HUMAN, PermissionDenied, NotApproved
from .tasks import transition, InvalidTransition
from .ingest.pathsafe import identifier, disjoint, safe
from .ingest.scanner import scan
from .ingest.copier import CopyEngine
from .ingest.manifest import write

def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class Workbench:
    def __init__(self, home, principal=HUMAN, fault_hook=None, disk_usage=None):
        self.home=Path(home); self.principal=principal; self.engine=CopyEngine(fault_hook); self.disk_usage=disk_usage or shutil.disk_usage
        self.config=config.load(self.home); db.initialize(self.home)
    @classmethod
    def init(cls, home, library, preview):
        config.initialize(home,library,preview); return cls(home)
    def _call(self,scope,action,task_id=None):
        self.principal.require(scope)
        with db.connect(self.home) as conn: record(conn,self.principal,action,task_id)
    def _admin(self,action):
        self._call('admin',action)
        if self.principal.actor_type!='human': raise PermissionDenied('human only')
    def add_source(self,source_id,path,label=None,kind='card'):
        self._admin('add_source'); identifier(source_id)
        if kind not in {'card','folder'}: raise ValueError('kind')
        if Path(path).is_symlink() or not Path(path).is_dir(): raise ValueError('source directory required')
        for root in ['library_root','preview_root']: disjoint(path,self.config[root])
        self.config['sources'][source_id]={'path':str(Path(path).resolve()),'label':label or source_id,'kind':kind}; config.save(self.home,self.config)
    def list_sources(self): self._call('read','list_sources'); return self.config['sources']
    def add_preset(self,preset_id,label=None,lightroom_uuid=None,lightroom_name=None):
        self._admin('add_preset'); identifier(preset_id)
        self.config['presets'][preset_id]={'label':label or preset_id,'lightroom_uuid':lightroom_uuid,'lightroom_name':lightroom_name or label or preset_id}; config.save(self.home,self.config)
    def _add(self,table,key,value):
        self._admin('add_'+table); identifier(key)
        with db.connect(self.home) as c: c.execute(f'INSERT INTO {table} VALUES(?,?)',(key,value))
    def create_order(self,order_id,title): self._add('orders',order_id,title)
    def add_photographer(self,photographer_id,name): self._add('photographers',photographer_id,name)
    def list_orders(self):
        self._call('read','list_orders')
        with db.connect(self.home) as c: return [dict(r) for r in c.execute('SELECT * FROM orders')]
    def scan_source(self,source_id):
        self._call('read','scan_source'); return scan(self.config['sources'][source_id]['path'])
    def plan_import(self,order_id,photographer_id,source_id,batch_label=None,preset_id=None,stages=None,scan_result=None):
        self._call('plan','plan_import'); identifier(order_id); identifier(photographer_id)
        stages=['ingest'] if stages is None else stages
        if not stages or any(s not in {'ingest','lr_register','lr_preset','lr_export','preview_verify'} for s in stages): raise ValueError('stages')
        if preset_id is not None: self.config['presets'][preset_id]
        result=scan_result or self.scan_source(source_id); batch=identifier(batch_label or 'b_'+result['digest'][:12])
        if len(batch)>64: raise ValueError('batch too long')
        source=self.config['sources'][source_id]['path']; disjoint(source,self.config['library_root'])
        base=f'{order_id}/{photographer_id}/{batch}'
        files=[]
        for f in result['files']:
            item=dict(f); item['dest_rel_path']=f'{base}/{f["rel_path"]}'; safe(self.config['library_root'],item['dest_rel_path'])
            item['asset_id']='ast_'+hashlib.sha256('\0'.join([order_id,photographer_id,batch,f['rel_path'],f['sha256']]).encode()).hexdigest()[:24]; files.append(item)
        key=digest([order_id,photographer_id,source_id,batch,result['digest'],preset_id,stages])
        plan={'files':files,'total_bytes':sum(f['size'] for f in files),'destination':base,'stages':stages,'preset_id':preset_id,'scan_digest':result['digest']}
        task_id='tsk_'+uuid.uuid4().hex
        with db.connect(self.home) as c:
            c.execute('BEGIN IMMEDIATE')
            existing=c.execute('SELECT task_id FROM tasks WHERE idempotency_key=?',(key,)).fetchone()
            if existing: task_id=existing['task_id']
            else:
                for table,column,value in [('orders','order_id',order_id),('photographers','photographer_id',photographer_id)]:
                    if not c.execute(f'SELECT 1 FROM {table} WHERE {column}=?',(value,)).fetchone(): raise ValueError('Unregistered '+column)
                c.execute('INSERT INTO tasks(task_id,idempotency_key,type,state,order_id,photographer_id,batch_id,source_id,plan_json,plan_digest,stages_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(task_id,key,'import','PENDING',order_id,photographer_id,batch,source_id,json.dumps(plan),digest(plan),json.dumps(stages),now(),now()))
                c.execute('INSERT OR IGNORE INTO batches VALUES(?,?,?,?,?)',(batch,order_id,photographer_id,source_id,result['digest']))
                for f in files:
                    c.execute('INSERT OR IGNORE INTO assets(asset_id,order_id,photographer_id,batch_id,rel_path,size,sha256,kind,status,dest_rel_path) VALUES(?,?,?,?,?,?,?,?,?,?)',(f['asset_id'],order_id,photographer_id,batch,f['rel_path'],f['size'],f['sha256'],f['kind'],'PLANNED',f['dest_rel_path']))
                transition(c,self.principal,task_id,'WAITING_APPROVAL')
        return self.get_task(task_id)
    def get_task(self,task_id):
        self._call('read','get_task',task_id)
        with db.connect(self.home) as c:
            row=c.execute('SELECT * FROM tasks WHERE task_id=?',(task_id,)).fetchone()
            if row is None: raise KeyError(task_id)
            result=dict(row); result['plan']=json.loads(result['plan_json']); return result
    def list_tasks(self):
        self._call('read','list_tasks')
        with db.connect(self.home) as c: return [dict(r) for r in c.execute('SELECT * FROM tasks')]
    def list_assets(self,task_id=None,batch_id=None):
        self._call('read','list_assets')
        with db.connect(self.home) as c:
            if task_id:
                t=c.execute('SELECT * FROM tasks WHERE task_id=?',(task_id,)).fetchone()
                return [dict(r) for r in c.execute('SELECT * FROM assets WHERE order_id=? AND photographer_id=? AND batch_id=?',(t['order_id'],t['photographer_id'],t['batch_id']))]
            return [dict(r) for r in c.execute('SELECT * FROM assets'+(' WHERE batch_id=?' if batch_id else ''),(batch_id,) if batch_id else ())]
    def approve(self,task_id,plan_digest):
        self._call('approve','approve',task_id)
        with db.connect(self.home) as c:
            t=c.execute('SELECT * FROM tasks WHERE task_id=?',(task_id,)).fetchone()
            if t['plan_digest']!=plan_digest: raise PermissionDenied('stale plan_digest')
            if t['state']!='WAITING_APPROVAL': raise InvalidTransition('approve requires WAITING_APPROVAL')
            c.execute('INSERT INTO approvals VALUES(?,?,?,?,?,NULL)',(task_id,plan_digest,self.principal.actor_id,json.dumps(sorted(self.principal.scopes)),now()))
        return self.get_task(task_id)
    def cancel(self,task_id):
        self._call('cancel','cancel',task_id)
        with db.connect(self.home) as c:
            error=transition(c,self.principal,task_id,'CANCELLED')
            if not error: c.execute('UPDATE approvals SET revoked_at=? WHERE task_id=?',(now(),task_id))
        if error: raise error
        return self.get_task(task_id)
    def retry(self,task_id):
        self._call('execute','retry',task_id); t=self.get_task(task_id)
        if t['state']=='CANCELLED':
            with db.connect(self.home) as c:
                transition(c,self.principal,task_id,'WAITING_APPROVAL'); c.execute('UPDATE tasks SET run_count=run_count+1 WHERE task_id=?',(task_id,))
            return self.get_task(task_id)
        if t['state']!='FAILED': raise InvalidTransition('retry requires FAILED or CANCELLED')
        return self.execute(task_id)
    def recover(self):
        self._call('execute','recover'); recovered=[]
        with db.connect(self.home) as c:
            for r in c.execute('SELECT task_id FROM tasks WHERE state="RUNNING" AND lease_until<?',(time.time(),)).fetchall():
                transition(c,self.principal,r['task_id'],'PAUSED'); recovered.append(r['task_id'])
        return recovered
    def execute(self,task_id,plan_digest=None,stop_on_error=None):
        self._call('execute','execute',task_id)
        error=None
        with db.connect(self.home) as c:
            c.execute('BEGIN IMMEDIATE'); t=dict(c.execute('SELECT * FROM tasks WHERE task_id=?',(task_id,)).fetchone())
            if plan_digest is not None and plan_digest!=t['plan_digest']: raise PermissionDenied('stale plan_digest')
            if t['state']=='COMPLETED': return t
            if not c.execute('SELECT 1 FROM approvals WHERE task_id=? AND plan_digest=? AND revoked_at IS NULL',(task_id,t['plan_digest'])).fetchone(): raise NotApproved(task_id)
            if t['state']=='RUNNING': raise InvalidTransition('live runner')
            error=transition(c,self.principal,task_id,'RUNNING')
            if not error: c.execute('UPDATE tasks SET run_count=run_count+1,lease_until=? WHERE task_id=?',(time.time()+300,task_id))
        if error: raise error
        t=self.get_task(task_id); plan=t['plan']; run=t['run_count']; library=Path(self.config['library_root'])
        tempdir=safe(library,f'.cetacea-tmp/{task_id}')
        if tempdir.exists():
            for part in tempdir.iterdir():
                if part.name.endswith('.part') and not part.is_dir(): part.unlink()
        results=[]; task_error=None; unsupported=None
        try:
            for stage in plan['stages']:
                started=now()
                if stage!='ingest':
                    with db.connect(self.home) as c:
                        c.execute('INSERT INTO task_steps VALUES(?,?,?,?,?,?,?,?,?,?)',(task_id,run,stage,'FAILED',0,0,0,json.dumps({'error':'NotImplementedError','stage':stage}),started,now()))
                    unsupported=NotImplementedError(stage)
                    raise unsupported
                if self.disk_usage(library).free < plan['total_bytes']*1.01: task_error='INSUFFICIENT_SPACE'
                else:
                    for n,item in enumerate(plan['files']):
                        with db.connect(self.home) as c:
                            state=c.execute('SELECT state FROM tasks WHERE task_id=?',(task_id,)).fetchone()['state']
                            if state=='CANCELLED': break
                            c.execute('UPDATE tasks SET lease_until=? WHERE task_id=?',(time.time()+300,task_id))
                            old=c.execute('SELECT sha256 FROM assets WHERE order_id=? AND photographer_id=? AND batch_id=? AND rel_path=?',(t['order_id'],t['photographer_id'],t['batch_id'],item['rel_path'])).fetchone()
                        result={'status':'FAILED','error':'IDENTITY_CONFLICT'} if old['sha256']!=item['sha256'] else self.engine.copy(Path(self.config['sources'][t['source_id']]['path']),library,task_id,n,item)
                        event={**item,**result,'verified_at':now() if result['status']=='VERIFIED' else None,'order':t['order_id'],'photographer':t['photographer_id'],'batch':t['batch_id'],'source_id':t['source_id'],'run':run}; results.append(event)
                        with db.connect(self.home) as c: c.execute('UPDATE assets SET status=?,error=?,verified_at=? WHERE asset_id=?',(result['status'],result['error'],event['verified_at'],item['asset_id']))
                        logs=self.home/'logs'; logs.mkdir(exist_ok=True)
                        with (logs/f'{task_id}.jsonl').open('a') as f: f.write(json.dumps(event)+'\n')
                        if result['status']!='VERIFIED':
                            task_error=result['error']
                            if stop_on_error is True or (stop_on_error is None and ('ENOSPC' in task_error or 'EDQUOT' in task_error)): break
                with db.connect(self.home) as c: c.execute('INSERT INTO task_steps VALUES(?,?,?,?,?,?,?,?,?,?)',(task_id,run,stage,'FAILED' if task_error else 'COMPLETED',sum(r['status']=='VERIFIED' and not r.get('skipped_verified') for r in results),sum(r['status']!='VERIFIED' for r in results),sum(bool(r.get('skipped_verified')) for r in results),json.dumps(results),started,now()))
                if results: write(library,plan['destination'],task_id,run,results)
                if task_error: break
        except Exception as exc: task_error=str(exc)
        with db.connect(self.home) as c:
            if c.execute('SELECT state FROM tasks WHERE task_id=?',(task_id,)).fetchone()['state']=='RUNNING': transition(c,self.principal,task_id,'FAILED' if task_error else 'COMPLETED')
            c.execute('UPDATE tasks SET error=?,lease_until=NULL WHERE task_id=?',(task_error,task_id))
        if unsupported: raise unsupported
        return self.get_task(task_id)
