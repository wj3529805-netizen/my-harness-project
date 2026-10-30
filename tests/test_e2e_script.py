import csv
import json
import subprocess
import sys
from pathlib import Path


def test_e2e_script(tmp_path):
    out = tmp_path/'evidence'
    result = subprocess.run([sys.executable, 'scripts/e2e_demo.py', '--out', str(out)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'MOCK — Linux simulation, not real Lightroom, not macOS' in result.stdout
    assert {p.name for p in out.iterdir()} == {'import-manifest.json', 'preview-manifest.json', 'report.json', 'report.md', 'run.jsonl', 'transcript.txt', 'photo-mapping.csv'}
    report = json.loads((out/'report.json').read_text())
    assert report['task']['state'] == 'COMPLETED'
    assert report['mock'] and report['idempotent'] and report['source_unchanged']
    assert report['preview']['status'] == 'OK'
    assert len(report['assets']) == 12
    assert len(json.loads((out/'preview-manifest.json').read_text())['previews']) == 6
    assert len(list(csv.DictReader((out/'photo-mapping.csv').open()))) == 6
    assert len((out/'run.jsonl').read_text().splitlines()) == 12
    assert (out/'transcript.txt').read_text().strip() == result.stdout.strip()
    assert 'MOCK — Linux simulation' in (out/'report.md').read_text()
