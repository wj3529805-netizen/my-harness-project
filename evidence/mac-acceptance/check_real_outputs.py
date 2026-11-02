"""Verify test-only outputs, delete one generated JPG, then restore it exclusively."""
import hashlib,json,os
from pathlib import Path
from PIL import Image
from cetacea.core import Workbench
from cetacea import db
root=Path(__file__).resolve().parents[2]; data=root/'acceptance-data'; out=root/'evidence/mac-acceptance'
w=Workbench(data/'home'); t=json.loads((out/'cc0-full-result.json').read_text()); tid=t['task_id']
assert t['state']=='COMPLETED',t['error']
with db.connect(w.home) as c: rows=[dict(r) for r in c.execute('SELECT * FROM previews WHERE task_id=?',(tid,))]
assert len(rows)==1
p=Path(rows[0]['path']); assert p.is_relative_to(data/'preview') and p.suffix.lower()=='.jpg' and not p.is_symlink()
b=p.read_bytes(); sha=hashlib.sha256(b).hexdigest(); assert sha==rows[0]['sha256']
with Image.open(p) as im:
 im.load(); dims=im.size; assert im.format=='JPEG' and max(dims)<=1600
before=w.verify_preview(tid); assert before['status']=='OK'
p.unlink()
try:
 missing=w.verify_preview(tid)
 assert missing['status']!='OK' and missing['missing']==[rows[0]['asset_id']],missing
finally:
 with p.open('xb') as f: f.write(b)
restored=w.verify_preview(tid); assert restored['status']=='OK'
a=json.loads((out/'develop-before.json').read_text())['photos'][0]['developSettings']['exposure']
z=json.loads((out/'develop-after.json').read_text())['photos'][0]['developSettings']['exposure']
assert a==0 and z==0.5,(a,z)
result={'jpeg_dimensions':dims,'jpeg_sha256':sha,'exposure_before':a,'exposure_after':z,'before':before,'after_test_deletion':missing,'after_exclusive_restore':restored,'restored_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
(out/'real-preview-checks.json').write_text(json.dumps(result,indent=2)); print(json.dumps(result))
