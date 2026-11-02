import json
import os
from .pathsafe import safe
from .copier import publish_no_overwrite

def write(library, batch_rel, task_id, run, data):
    target = safe(library,f'{batch_rel}/.cetacea/import-manifest-run{run}.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    temp = safe(library,f'.cetacea-tmp/{task_id}/manifest.part')
    temp.parent.mkdir(parents=True,exist_ok=True)
    with temp.open('x') as f:
        json.dump(data,f,indent=2); f.flush(); os.fsync(f.fileno())
    try:
        while True:
            try:
                publish_no_overwrite(temp,target)
                break
            except FileExistsError:
                run += 1
                target = safe(library,f'{batch_rel}/.cetacea/import-manifest-run{run}.json')
    finally: temp.unlink(missing_ok=True)
    return str(target)
