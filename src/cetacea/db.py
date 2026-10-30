import sqlite3
from contextlib import contextmanager

SCHEMA = '''
CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY,title TEXT);
CREATE TABLE IF NOT EXISTS photographers(photographer_id TEXT PRIMARY KEY,name TEXT);
CREATE TABLE IF NOT EXISTS batches(batch_id TEXT,order_id TEXT,photographer_id TEXT,source_id TEXT,scan_digest TEXT,PRIMARY KEY(order_id,photographer_id,batch_id));
CREATE TABLE IF NOT EXISTS assets(asset_id TEXT PRIMARY KEY,order_id TEXT,photographer_id TEXT,batch_id TEXT,rel_path TEXT,size INTEGER,sha256 TEXT,kind TEXT,status TEXT,error TEXT,dest_rel_path TEXT,lr_photo_id TEXT,lr_status TEXT,preset_applied TEXT,mock INTEGER DEFAULT 0,verified_at TEXT,UNIQUE(order_id,photographer_id,batch_id,rel_path));
CREATE TABLE IF NOT EXISTS tasks(task_id TEXT PRIMARY KEY,idempotency_key TEXT UNIQUE,type TEXT,state TEXT,order_id TEXT,photographer_id TEXT,batch_id TEXT,source_id TEXT,plan_json TEXT,plan_digest TEXT,stages_json TEXT,run_count INTEGER DEFAULT 0,error TEXT,created_at TEXT,updated_at TEXT,lease_until REAL);
CREATE TABLE IF NOT EXISTS task_steps(task_id TEXT,run INTEGER,stage TEXT,state TEXT,succeeded INTEGER,failed INTEGER,skipped INTEGER,detail_json TEXT,started_at TEXT,ended_at TEXT);
CREATE TABLE IF NOT EXISTS approvals(task_id TEXT,plan_digest TEXT,approved_by TEXT,scopes TEXT,granted_at TEXT,revoked_at TEXT);
CREATE TABLE IF NOT EXISTS previews(preview_id TEXT PRIMARY KEY,task_id TEXT,run INTEGER,asset_id TEXT,path TEXT,sha256 TEXT,width INTEGER,height INTEGER,status TEXT,mock INTEGER);
CREATE TABLE IF NOT EXISTS audit_log(actor TEXT,action TEXT,task_id TEXT,detail_json TEXT,ts TEXT);
PRAGMA user_version=1;
'''
@contextmanager
def connect(home):
    db = sqlite3.connect(str(home/'state.sqlite3'), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON'); db.execute('PRAGMA journal_mode=WAL')
    try:
        with db: yield db
    finally: db.close()

def initialize(home):
    with connect(home) as db: db.executescript(SCHEMA)
