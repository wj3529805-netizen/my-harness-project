import os
import hashlib
import json
from .pathsafe import read_hash
RAW = set('raf nef nrw arw cr2 cr3 dng orf rw2 pef srw x3f raw 3fr iiq'.split())
def scan(root):
    files, skipped = [], []
    def walk(path, prefix=''):
        with os.scandir(path) as entries:
            for entry in sorted(entries,key=lambda e:e.name):
                rel = prefix+entry.name
                if entry.is_symlink(): skipped.append({'rel_path':rel,'reason':'symlink'})
                elif entry.name in {'.DS_Store','Thumbs.db'} or entry.name.startswith('._'): skipped.append({'rel_path':rel,'reason':'system'})
                elif entry.is_dir(follow_symlinks=False): walk(entry.path,rel+'/')
                elif entry.is_file(follow_symlinks=False):
                    ext = entry.name.rsplit('.',1)[-1].lower()
                    files.append({'rel_path':rel,'size':entry.stat(follow_symlinks=False).st_size,'sha256':read_hash(entry.path),'kind':'raw' if ext in RAW else 'jpeg' if ext in {'jpg','jpeg'} else 'sidecar' if ext in {'xmp','acr'} else 'other'})
                else: skipped.append({'rel_path':rel,'reason':'not regular'})
    walk(root)
    digest = hashlib.sha256(json.dumps([(f['rel_path'],f['size'],f['sha256']) for f in files],separators=(',',':')).encode()).hexdigest()
    return {'files':files,'skipped':skipped,'digest':digest}
