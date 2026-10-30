import json
from pathlib import Path
from .ingest.pathsafe import disjoint

def initialize(home, library, preview):
    disjoint(library, preview)
    home = Path(home); home.mkdir(parents=True, exist_ok=True)
    config = {'library_root': str(Path(library).absolute()), 'preview_root': str(Path(preview).absolute()), 'sources': {}, 'presets': {}}
    with (home/'config.json').open('x') as f: json.dump(config, f)
    Path(library).mkdir(parents=True, exist_ok=True)
    Path(preview).mkdir(parents=True, exist_ok=True)
    return config

def load(home): return json.loads((Path(home)/'config.json').read_text())
def save(home, config):
    path = Path(home)/'config.json'
    temp = path.with_suffix('.new')
    temp.write_text(json.dumps(config, indent=2)); temp.replace(path)
