import errno
import hashlib
import os
import stat
from pathlib import Path
from .pathsafe import safe, read_hash

def publish_no_overwrite(temp, dest):
    """Publish on hard-link filesystems or coordinate CETACEA fallback writers.

    The rename fallback retains the documented limitation that external writers
    which ignore the per-destination lock can race the nonexistence check.
    """
    temp, dest = Path(temp), Path(dest)
    try:
        os.link(temp, dest)
    except OSError as exc:
        if exc.errno not in {errno.EOPNOTSUPP, errno.ENOSYS, errno.EXDEV, errno.EPERM}:
            raise
        lock = dest.with_name(dest.name + '.cetacea-lock')
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            if os.path.lexists(dest):
                raise FileExistsError(str(dest))
            os.rename(temp, dest)
        finally:
            os.close(lock_fd)
            lock.unlink()

class CopyEngine:
    def __init__(self, fault_hook=None): self.fault_hook = fault_hook or (lambda stage,rel: None)
    def copy(self, source, library, task_id, n, item):
        rel = item['rel_path']; temp = safe(library, f'.cetacea-tmp/{task_id}/{n}.part')
        dest = safe(library,item['dest_rel_path'])
        temp.parent.mkdir(parents=True,exist_ok=True)
        try:
            fd = os.open(safe(source,rel), os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd,'rb') as src:
                info = os.fstat(src.fileno())
                if not stat.S_ISREG(info.st_mode): raise ValueError('Not regular')
                with os.fdopen(os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as out:
                    h = hashlib.sha256()
                    while block := src.read(1024*1024): out.write(block); h.update(block)
                    out.flush(); os.fsync(out.fileno())
            self.fault_hook('after_temp_write',rel)
            if h.hexdigest()!=item['sha256']: raise ValueError('SOURCE_CHANGED')
            if read_hash(temp)!=item['sha256']: raise ValueError('TEMP_VERIFY_FAILED')
            self.fault_hook('before_commit',rel)
            dest = safe(library,item['dest_rel_path']); dest.parent.mkdir(parents=True,exist_ok=True)
            skipped = False
            try:
                os.chmod(temp,0o644)
                publish_no_overwrite(temp,dest)
                if temp.exists(): temp.unlink()
                directory = os.open(dest.parent,os.O_RDONLY|os.O_DIRECTORY)
                try: os.fsync(directory)
                finally: os.close(directory)
            except FileExistsError:
                if read_hash(dest)!=item['sha256']: raise ValueError('CONFLICT')
                skipped = True
            self.fault_hook('after_commit',rel)
            if read_hash(dest)!=item['sha256']: raise ValueError('FINAL_VERIFY_FAILED')
            return {'status':'VERIFIED','skipped_verified':skipped,'error':None}
        except Exception as exc:
            code = errno.errorcode.get(getattr(exc,'errno',None),'')
            return {'status':'CONFLICT' if str(exc)=='CONFLICT' else 'FAILED','error':f'{code} {exc}'.strip()}
        finally:
            if temp.exists(): temp.unlink()
