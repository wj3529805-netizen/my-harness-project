import os
import re
import stat
from pathlib import Path

def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9._-]*', value):
        raise ValueError('Invalid identifier')
    return value

def relative(value):
    if not value or value.startswith('/') or '\\' in value or any(p in {'', '.', '..'} for p in value.split('/')):
        raise ValueError('Unsafe relative path')
    return value

def safe(root, rel):
    relative(rel)
    root = Path(root)
    current = root
    for part in (root, *[root.joinpath(*Path(rel).parts[:n]) for n in range(1, len(Path(rel).parts)+1)]):
        if part.is_symlink(): raise ValueError('Symlink destination')
    current = root / rel
    if not current.resolve().is_relative_to(root.resolve()): raise ValueError('Destination escape')
    return current

def disjoint(a, b):
    a, b = Path(a).resolve(), Path(b).resolve()
    if a.is_relative_to(b) or b.is_relative_to(a): raise ValueError('Overlapping roots')

def read_hash(path):
    import hashlib
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode): raise ValueError('Not regular')
        h = hashlib.sha256()
        while block := f.read(1024*1024): h.update(block)
        return h.hexdigest()
