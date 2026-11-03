"""Conservative, read-only identification of macOS metadata files."""
import os
import stat
from pathlib import Path


def is_appledouble(path):
    path = Path(path)
    if not path.name.startswith('._'): return False
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as f:
            return stat.S_ISREG(os.fstat(f.fileno()).st_mode) and f.read(4) == b'\x00\x05\x16\x07'
    except OSError:
        return False


def is_ignorable_macos_metadata(path):
    """Ignore genuine AppleDouble and regular, exactly named .DS_Store files."""
    path = Path(path)
    if is_appledouble(path): return True
    try:
        return path.name == '.DS_Store' and stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False
