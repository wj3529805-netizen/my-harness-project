"""Offline mock end-to-end demonstration with durable, exclusive evidence."""
import argparse
import csv
import hashlib
import io
import json
import shutil
import tempfile
from pathlib import Path
from cetacea.core import Workbench
from cetacea import db

BANNER = 'MOCK — Linux simulation, not real Lightroom, not macOS'
STAGES = ['ingest', 'lr_register', 'lr_preset', 'lr_export', 'preview_verify']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('evidence/e2e'))
    args = parser.parse_args(argv)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    transcript = [BANNER]
    # Keep the temporary workbench alive until all destination bytes are verified
    # and all evidence has been copied. Paths in evidence describe that run.
    with tempfile.TemporaryDirectory(prefix='cetacea-e2e-') as temporary:
        root = Path(temporary)
        card = root/'card'
        for n in range(6):
            folder = card/f'DCIM/set-{n % 2}'
            folder.mkdir(parents=True, exist_ok=True)
            for ext in ['RAF', 'JPG']:
                (folder/f'IMG_{n:04d}.{ext}').write_bytes(f'MOCK source {n} {ext}\n'.encode()*100)
        before = {str(p.relative_to(card)): (p.read_bytes(), p.stat().st_mtime_ns) for p in card.rglob('*') if p.is_file()}
        w = Workbench.init(root/'home', root/'library', root/'preview')
        w.add_source('card', card)
        w.create_order('demo', 'Mock demonstration')
        w.add_photographer('photographer', 'Demo photographer')
        w.add_preset('demo', 'MOCK demo preset')
        scan = w.scan_source('card')
        transcript.append(f"scan: {len(scan['files'])} files")
        task = w.plan_import('demo', 'photographer', 'card', preset_id='demo', stages=STAGES, scan_result=scan)
        tid = task['task_id']
        transcript.append(f'plan: {tid}')
        w.approve(tid, task['plan_digest'])
        transcript.append('approve: human')
        result = w.execute(tid)
        transcript.append(f"execute: {result['state']}")
        with db.connect(w.home) as c:
            counts = tuple(c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ['assets', 'previews', 'task_steps'])
        snapshot = {str(p): (p.stat().st_ino, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for base in [root/'library', root/'preview'] for p in base.rglob('*') if p.is_file()}
        w.execute(tid)
        with db.connect(w.home) as c:
            counts_after = tuple(c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ['assets', 'previews', 'task_steps'])
        unchanged = all((Path(p).stat().st_ino, Path(p).stat().st_mtime_ns, hashlib.sha256(Path(p).read_bytes()).hexdigest()) == stat for p, stat in snapshot.items())
        after = {str(p.relative_to(card)): (p.read_bytes(), p.stat().st_mtime_ns) for p in card.rglob('*') if p.is_file()}
        report = w.report(tid)
        report.update(marker=BANNER, idempotent=counts == counts_after and unchanged, source_unchanged=before == after)
        report['markdown'] = BANNER + '\n\n' + report['markdown']
        manifest = next((root/'library').rglob('import-manifest-run*.json'))
        preview_manifest = next((root/'preview').rglob('preview-manifest.json'))
        mappings = json.loads(preview_manifest.read_text())['previews']
        files = {'import-manifest.json': manifest.read_bytes(), 'preview-manifest.json': preview_manifest.read_bytes(), 'run.jsonl': (w.home/'logs'/f'{tid}.jsonl').read_bytes()}
        report['mapping'] = mappings
        ok = (result['state'] == 'COMPLETED' and report['preview']['status'] == 'OK' and report['preview']['expected_count'] == 6 and len(report['assets']) == 12 and all(a['status'] == 'VERIFIED' for a in report['assets']) and report['idempotent'] and report['source_unchanged'])
        transcript.extend([f"repeat execute: idempotent={report['idempotent']}", f'verified: {ok}'])
        table = io.StringIO()
        writer = csv.writer(table)
        writer.writerow(['asset_id', 'source_rel_path', 'raw_sha256', 'jpg_path', 'jpg_sha256'])
        for row in mappings:
            writer.writerow([row['asset_id'], row['source_rel_path'], row['raw_sha256'], row['path'], row['sha256']])
        files.update({'report.json': json.dumps(report, indent=2).encode(), 'report.md': report['markdown'].encode(), 'photo-mapping.csv': table.getvalue().encode(), 'transcript.txt': ('\n'.join(transcript)+'\n').encode()})
        for name, content in files.items():
            with (out/name).open('xb') as f: f.write(content)
        print('\n'.join(transcript))
        return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
