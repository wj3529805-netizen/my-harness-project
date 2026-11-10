"""Import desk drives the real workbench. Fixtures are synthetic labeled bytes."""
import json
import threading
import time
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlparse

import pytest

from cetacea.core import Workbench
from cetacea.import_desk import ImportDesk, IngestOnlyAdapter
from cetacea import db

MARKER = b'CETACEA-SYNTHETIC-EXAMPLE-NOT-A-CAMERA-FILE\n'


class Client:
    def __init__(self, origin):
        parsed = urlparse(origin)
        self.host, self.port = parsed.hostname, parsed.port
        self.cookie = self.csrf = None

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection(self.host, self.port, timeout=10)
        payload = None if body is None else json.dumps(body).encode()
        merged = dict(headers or {})
        if self.cookie:
            merged['Cookie'] = self.cookie
        connection.request(method, path, body=payload, headers=merged)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, response.getheader('Set-Cookie'), raw

    def open_page(self):
        status, cookie, raw = self.request('GET', '/')
        assert status == 200
        self.cookie = cookie.split(';', 1)[0]
        text = raw.decode()
        self.csrf = text.split('name="csrf" content="', 1)[1].split('"', 1)[0]
        return text

    def post(self, path, body=None, **headers):
        merged = {'Content-Type': 'application/json', 'X-Cetacea-CSRF': self.csrf, 'Host': f'127.0.0.1:{self.port}'}
        merged.update(headers)
        status, _, raw = self.request('POST', path, body or {}, merged)
        return status, json.loads(raw.decode())


@pytest.fixture
def roots(tmp_path):
    for name in ('home', 'library', 'preview', 'card'):
        (tmp_path / name).mkdir()
    return tmp_path


def write_card(card):
    files = {
        'EXAMPLE_ONLY.NEF': 'standalone-nef',
        'EXAMPLE_ONLY.JPG': 'standalone-jpg',
        'nested/EXAMPLE_PAIR.NEF': 'paired-nef',
        'nested/EXAMPLE_PAIR.JPG': 'paired-jpg',
        'EXAMPLE_SOLO.jpeg': 'solo-jpeg',
    }
    for rel, label in files.items():
        path = card / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(MARKER + label.encode() + b'\n')
    return files


def snapshot(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns) for path in root.rglob('*') if path.is_file()}


@pytest.fixture
def desk(roots):
    scans = []
    def make(home):
        workbench = Workbench(home, adapter=IngestOnlyAdapter())
        original = workbench.scan_source
        def scan(source_id):
            scans.append(source_id)
            return original(source_id)
        workbench.scan_source = scan
        return workbench
    app = ImportDesk(workbench_factory=make)
    origin = app.start()
    client = Client(origin)
    page = client.open_page()
    yield app, client, roots, scans, page
    app.stop()


def create_workspace(client, roots):
    status, data = client.post('/api/workspace/create', {'home': str(roots/'home'), 'library': str(roots/'library'), 'preview': str(roots/'preview')})
    assert status == 200, data
    return data


def prepare(client, roots):
    create_workspace(client, roots)
    write_card(roots/'card')
    assert client.post('/api/sources', {'source_id': 'card', 'path': str(roots/'card')})[0] == 200
    assert client.post('/api/orders', {'order_id': 'order-1', 'title': '合成订单'})[0] == 200
    assert client.post('/api/photographers', {'photographer_id': 'photo-1', 'name': '合成摄影师'})[0] == 200


def test_loopback_page_has_no_preset_paths():
    with pytest.raises(ValueError, match='127.0.0.1'):
        ImportDesk(host='0.0.0.0')
    text = Path('scripts/mac/CETACEA导入.command').read_text()
    assert 'import_desk' in text and 'Volumes/' not in text and 'DEEPSEEK' not in text


def test_open_lists_existing_records_without_scanning(desk):
    app, client, roots, scans, page = desk
    assert '仅拷入' in page and '/Volumes/' not in page
    workbench = Workbench.init(roots/'home', roots/'library', roots/'preview')
    workbench.create_order('order-1', '已有订单')
    workbench.add_photographer('photo-1', '已有摄影师')
    workbench.add_source('card', roots/'card', '已有来源')
    (roots/'card'/'SECRET.JPG').write_bytes(MARKER + b'secret\n')
    status, data = client.post('/api/workspace/open', {'home': str(roots/'home')})
    assert status == 200
    assert data['orders'] == [{'id': 'order-1', 'title': '已有订单'}]
    assert data['photographers'] == [{'id': 'photo-1', 'name': '已有摄影师'}]
    assert data['sources'][0]['id'] == 'card'
    assert 'files' not in data and scans == []


def test_three_formats_plan_approval_and_verification(desk):
    app, client, roots, scans, page = desk
    prepare(client, roots)
    before = snapshot(roots/'card')
    status, plan = client.post('/api/plan', {'source_id': 'card', 'order_id': 'order-1', 'photographer_id': 'photo-1', 'batch_label': 'batch-1'})
    assert status == 200, plan
    assert plan['ingest_only'] is True and plan['stages'] == ['ingest']
    assert plan['file_count'] == 5
    assert plan['kinds']['RAW（含 NEF）'] == 2 and plan['kinds']['JPEG'] == 3
    assert plan['extensions'] == {'.nef': 2, '.jpg': 2, '.jpeg': 1}
    assert plan['source_path'] == str((roots/'card').resolve())
    assert plan['destination'].startswith(str((roots/'library').resolve()))
    assert scans == ['card']
    status, started = client.post('/api/import', {'task_id': plan['task_id'], 'plan_digest': plan['plan_digest'], 'destination': plan['destination']})
    assert status == 200, started
    progress = settle(client, plan['task_id'])
    assert progress['busy'] is False
    assert progress['state'] == 'COMPLETED', progress
    assert progress['counts'] == {'VERIFIED': 5}
    assert all(row['detail'] == '已从目标重新读回并比对 SHA-256' for row in progress['files'])
    assert snapshot(roots/'card') == before
    with db.connect(roots/'home') as connection:
        assert connection.execute('SELECT count(*) FROM approvals').fetchone()[0] == 1
        row = connection.execute('SELECT run_count, state FROM tasks').fetchone()
        assert row['run_count'] == 1 and row['state'] == 'COMPLETED'


def test_stale_digest_and_destination_do_not_copy(desk):
    app, client, roots, scans, page = desk
    prepare(client, roots)
    status, plan = client.post('/api/plan', {'source_id': 'card', 'order_id': 'order-1', 'photographer_id': 'photo-1'})
    status, denied = client.post('/api/import', {'task_id': plan['task_id'], 'plan_digest': '0' * 64, 'destination': plan['destination']})
    assert status == 409 and '重新' in denied['error']
    status, denied = client.post('/api/import', {'task_id': plan['task_id'], 'plan_digest': plan['plan_digest'], 'destination': str(roots/'preview')})
    assert status == 409
    assert list((roots/'library').rglob('*')) == []
    with db.connect(roots/'home') as connection:
        assert connection.execute('SELECT count(*) FROM approvals').fetchone()[0] == 0


def settle(client, task_id):
    deadline = time.monotonic() + 10
    progress = {'state': 'RUNNING', 'busy': True, 'files': []}
    while time.monotonic() < deadline:
        _, progress = client.post('/api/task', {'task_id': task_id})
        if not progress['busy']:
            return progress
        time.sleep(0.01)
    return progress


def test_conflict_and_read_failure_are_visible(desk):
    app, client, roots, scans, page = desk
    prepare(client, roots)
    status, plan = client.post('/api/plan', {'source_id': 'card', 'order_id': 'order-1', 'photographer_id': 'photo-1', 'batch_label': 'batch-1'})
    conflict = Path(plan['destination']) / 'EXAMPLE_ONLY.JPG'
    conflict.parent.mkdir(parents=True)
    original = b'CETACEA-SYNTHETIC-EXAMPLE-DIFFERENT-BYTES\n'
    conflict.write_bytes(original)
    client.post('/api/import', {'task_id': plan['task_id'], 'plan_digest': plan['plan_digest'], 'destination': plan['destination']})
    progress = settle(client, plan['task_id'])
    assert progress['busy'] is False
    assert progress['state'] == 'FAILED'
    shown = {row['rel_path']: row for row in progress['files']}
    assert shown['EXAMPLE_ONLY.JPG']['status'] == 'CONFLICT'
    assert shown['EXAMPLE_ONLY.NEF']['status'] == 'VERIFIED'
    assert conflict.read_bytes() == original

    def failing(home):
        workbench = Workbench(home, adapter=IngestOnlyAdapter())
        def hook(stage, rel):
            if stage == 'after_temp_write':
                raise OSError(5, 'synthetic read failure')
        workbench.engine.fault_hook = hook
        return workbench
    app.factory = failing
    (roots/'card'/'EXTRA.NEF').write_bytes(MARKER + b'extra\n')
    _, failed_plan = client.post('/api/plan', {'source_id': 'card', 'order_id': 'order-1', 'photographer_id': 'photo-1', 'batch_label': 'batch-2'})
    client.post('/api/import', {'task_id': failed_plan['task_id'], 'plan_digest': failed_plan['plan_digest'], 'destination': failed_plan['destination']})
    progress = settle(client, failed_plan['task_id'])
    assert progress['busy'] is False
    assert progress['state'] == 'FAILED'
    assert any(row['status'] == 'FAILED' and row['detail'] for row in progress['files'])


def test_second_click_does_not_start_another_import(desk):
    app, client, roots, scans, page = desk
    prepare(client, roots)
    release = threading.Event()
    def blocking(home):
        workbench = Workbench(home, adapter=IngestOnlyAdapter())
        def hook(stage, rel):
            if stage == 'before_commit':
                release.wait(5)
        workbench.engine.fault_hook = hook
        return workbench
    app.factory = blocking
    _, plan = client.post('/api/plan', {'source_id': 'card', 'order_id': 'order-1', 'photographer_id': 'photo-1', 'batch_label': 'batch-1'})
    first = client.post('/api/import', {'task_id': plan['task_id'], 'plan_digest': plan['plan_digest'], 'destination': plan['destination']})
    assert first[0] == 200
    second = client.post('/api/import', {'task_id': plan['task_id'], 'plan_digest': plan['plan_digest'], 'destination': plan['destination']})
    assert second[0] == 200 and second[1]['already'] is True
    release.set()
    progress = settle(client, plan['task_id'])
    assert progress['busy'] is False
    assert progress['state'] == 'COMPLETED'
    with db.connect(roots/'home') as connection:
        assert connection.execute('SELECT count(*) FROM approvals').fetchone()[0] == 1
        assert connection.execute('SELECT run_count FROM tasks').fetchone()[0] == 1


def test_cross_site_and_missing_token_are_rejected(desk):
    app, client, roots, scans, page = desk
    status, payload = client.post('/api/workspace/current', {}, Origin='http://evil.example')
    assert status == 403 and '跨站' in payload['error']
    status, _, raw = client.request('POST', '/api/workspace/current', {}, {'Host': f'127.0.0.1:{client.port}', 'Content-Type': 'application/json'})
    assert status == 403
    status, _, raw = client.request('GET', '/', headers={'Host': 'evil.example'})
    assert status == 403


def test_reveal_stays_inside_library(desk):
    app, client, roots, scans, page = desk
    opened = []
    app.reveal = lambda path: opened.append(path) or True
    prepare(client, roots)
    _, plan = client.post('/api/plan', {'source_id': 'card', 'order_id': 'order-1', 'photographer_id': 'photo-1', 'batch_label': 'batch-1'})
    client.post('/api/import', {'task_id': plan['task_id'], 'plan_digest': plan['plan_digest'], 'destination': plan['destination']})
    assert settle(client, plan['task_id'])['state'] == 'COMPLETED'
    status, result = client.post('/api/reveal', {'task_id': plan['task_id']})
    assert status == 200 and result['opened'] is True
    assert opened == [Path(plan['destination'])]
    assert str(opened[0]).startswith(str((roots/'library').resolve()))


def test_settled_progress_keeps_failure_after_a_stale_running_row(desk):
    app, client, roots, scans, page = desk
    prepare(client, roots)
    _, plan = client.post('/api/plan', {'source_id': 'card', 'order_id': 'order-1', 'photographer_id': 'photo-1', 'batch_label': 'batch-1'})
    conflict = Path(plan['destination']) / 'EXAMPLE_ONLY.JPG'
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b'CETACEA-SYNTHETIC-EXAMPLE-DIFFERENT-BYTES\n')
    client.post('/api/import', {'task_id': plan['task_id'], 'plan_digest': plan['plan_digest'], 'destination': plan['destination']})
    assert settle(client, plan['task_id'])['state'] == 'FAILED'
    with db.connect(roots/'home') as connection:
        connection.execute('UPDATE tasks SET state="RUNNING" WHERE task_id=?', (plan['task_id'],))
    _, progress = client.post('/api/task', {'task_id': plan['task_id']})
    assert progress['busy'] is False and progress['state'] == 'FAILED'


def test_running_import_cannot_change_workbench(desk):
    app, client, roots, scans, page = desk
    prepare(client, roots)
    release = threading.Event()
    homes = []
    def blocking(home):
        homes.append(Path(home))
        workbench = Workbench(home, adapter=IngestOnlyAdapter())
        def hook(stage, rel):
            if stage == 'before_commit':
                release.wait(5)
        workbench.engine.fault_hook = hook
        return workbench
    app.factory = blocking
    _, plan = client.post('/api/plan', {'source_id': 'card', 'order_id': 'order-1', 'photographer_id': 'photo-1', 'batch_label': 'batch-1'})
    for name in ('home-b', 'library-b', 'preview-b'):
        (roots/name).mkdir()
    assert client.post('/api/import', {'task_id': plan['task_id'], 'plan_digest': plan['plan_digest'], 'destination': plan['destination']})[0] == 200
    status, denied = client.post('/api/workspace/create', {'home': str(roots/'home-b'), 'library': str(roots/'library-b'), 'preview': str(roots/'preview-b')})
    assert status == 400 and '不能切换' in denied['error']
    status, denied = client.post('/api/workspace/open', {'home': str(roots/'home')})
    assert status == 400 and '不能切换' in denied['error']
    again = client.post('/api/import', {'task_id': plan['task_id'], 'plan_digest': plan['plan_digest'], 'destination': plan['destination']})
    assert again[1]['already'] is True
    _, progress = client.post('/api/task', {'task_id': plan['task_id']})
    assert progress['busy'] is True
    assert progress['destination'].startswith(str((roots/'library').resolve()))
    release.set()
    finished = settle(client, plan['task_id'])
    assert finished['state'] == 'COMPLETED' and finished['busy'] is False
    assert homes and all(path.resolve() == (roots/'home').resolve() for path in homes)
    assert list((roots/'library-b').rglob('*')) == []
    with db.connect(roots/'home') as connection:
        assert connection.execute('SELECT count(*) FROM approvals').fetchone()[0] == 1
        assert connection.execute('SELECT run_count FROM tasks').fetchone()[0] == 1


def test_new_order_and_source_round_trip(desk):
    app, client, roots, scans, page = desk
    data = create_workspace(client, roots)
    assert data['orders'] == [] and data['sources'] == []
    status, denied = client.post('/api/sources', {'source_id': '../card', 'path': str(roots/'card')})
    assert status == 400
    link = roots/'link'
    link.symlink_to(roots/'card', target_is_directory=True)
    status, denied = client.post('/api/sources', {'source_id': 'linked', 'path': str(link)})
    assert status == 400
    status, denied = client.post('/api/workspace/create', {'home': str(roots/'home'), 'library': str(roots/'library'), 'preview': str(roots/'library')})
    assert status == 400
