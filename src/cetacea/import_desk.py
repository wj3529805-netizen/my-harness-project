"""Local Chinese import desk. Ingest only, through the existing workbench.

The server listens on 127.0.0.1. It never calls a model, never probes Lightroom,
and never copies bytes itself: plan, approve and execute stay in core.
"""
import argparse
import json
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .core import Workbench
from . import db
from .lightroom.base import LightroomAdapter
from .perms import PermissionDenied
from .tasks import InvalidTransition

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf" content="__CSRF__">
<title>CETACEA 导入</title>
<style>
  :root { color-scheme: light; --ink:#1c1915; --muted:#5c564c; --line:#e4dccf; --paper:#f7f3ec; --card:#fffdf8; --green:#0f6e56; --green-ink:#08382c; --warn:#8a4b08; --bad:#8f1d1d; }
  * { box-sizing: border-box; }
  body { margin:0; font:16px/1.5 "Songti SC","Source Han Serif SC",Palatino,serif; color:var(--ink); background:var(--paper); }
  header { padding:28px 32px 8px; }
  header h1 { margin:0; font-size:28px; font-weight:650; letter-spacing:0.02em; }
  header p { margin:8px 0 0; color:var(--muted); max-width:46rem; }
  main { display:grid; gap:16px; padding:16px 32px 48px; max-width:980px; }
  section { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:18px 20px 20px; }
  h2 { margin:0 0 12px; font-size:18px; }
  label { display:block; margin:10px 0 4px; color:var(--muted); font-size:14px; }
  input, select, button { font:inherit; }
  input, select { width:100%; padding:10px 12px; border:1px solid var(--line); border-radius:10px; background:#fff; color:var(--ink); }
  .row { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  .actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; align-items:center; }
  button { border:0; border-radius:999px; padding:10px 16px; background:var(--green); color:white; cursor:pointer; align-self:center; }
  button.secondary { background:#efe8dc; color:var(--ink); }
  button:disabled { opacity:.45; cursor:not-allowed; }
  .note { color:var(--muted); font-size:14px; }
  .banner { padding:10px 12px; border-radius:10px; background:#e7f4ef; color:var(--green-ink); }
  .warn { background:#fff4e5; color:var(--warn); }
  .bad { background:#fdecec; color:var(--bad); }
  dl { display:grid; grid-template-columns:8rem 1fr; gap:6px 12px; margin:12px 0; }
  dt { color:var(--muted); }
  dd { margin:0; overflow-wrap:anywhere; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { text-align:left; padding:6px 4px; border-bottom:1px solid var(--line); vertical-align:top; }
  .check { display:flex; gap:8px; align-items:flex-start; margin-top:12px; }
  .check input { width:auto; margin-top:4px; }
  #progress-bar { height:10px; background:#efe8dc; border-radius:999px; overflow:hidden; }
  #progress-bar span { display:block; height:100%; width:0; background:var(--green); }
  @media (max-width:720px) { .row { grid-template-columns:1fr; } header, main { padding-left:16px; padding-right:16px; } }
</style>
</head>
<body>
<header>
  <h1>CETACEA 导入</h1>
  <p>只把照片拷入你确认的目标目录，并在目标上重新读回、比对 SHA-256。不调用模型，不连接 Lightroom。来源目录只读，已有文件不会被覆盖。</p>
</header>
<main>
  <section id="workspace">
    <h2>工作台与目标位置</h2>
    <p class="note">三个目录都要你自己在访达里建好，再把绝对路径粘贴进来。这里没有预填路径，也不会写到生产 NAS 或旧资料，除非你明确打开那样的工作台并在计划里再次确认。</p>
    <label for="open-home">打开已有工作台</label><input id="open-home" placeholder="/绝对路径/home" autocomplete="off">
    <div class="actions"><button type="button" id="open-btn" class="secondary">打开</button></div>
    <div class="row">
      <div><label for="new-home">新工作台状态目录</label><input id="new-home" placeholder="/绝对路径/home" autocomplete="off"></div>
      <div><label for="new-library">新的照片库（拷入目标）</label><input id="new-library" placeholder="/绝对路径/library" autocomplete="off"></div>
    </div>
    <label for="new-preview">预览目录（本次拷入不会写入，仍须与库分开）</label>
    <input id="new-preview" placeholder="/绝对路径/preview" autocomplete="off">
    <div class="actions"><button type="button" id="create-btn">用以上三个目录新建</button></div>
    <p id="workspace-msg" class="note"></p>
    <div id="workspace-now" hidden></div>
  </section>
  <section id="setup" hidden>
    <h2>来源、订单、摄影师</h2>
    <p class="note">打开工作台不会扫描照片。只有点击「查看计划」才会读取你选中的那一个来源。</p>
    <div class="row">
      <div><label for="source">已有来源</label><select id="source"></select></div>
      <div><label for="order">已有订单</label><select id="order"></select></div>
    </div>
    <label for="photographer">已有摄影师</label><select id="photographer"></select>
    <div class="row">
      <div><label for="source-id">新来源编号</label><input id="source-id" placeholder="字母数字，如 card-a" autocomplete="off"></div>
      <div><label for="source-path">新来源绝对路径</label><input id="source-path" placeholder="在访达中复制文件夹路径" autocomplete="off"></div>
    </div>
    <div class="actions"><button type="button" id="add-source" class="secondary">登记来源</button></div>
    <div class="row">
      <div><label for="order-id">新订单编号</label><input id="order-id" placeholder="字母数字" autocomplete="off"></div>
      <div><label for="order-title">订单名称</label><input id="order-title" placeholder="可以是中文" autocomplete="off"></div>
    </div>
    <div class="actions"><button type="button" id="add-order" class="secondary">登记订单</button></div>
    <div class="row">
      <div><label for="photog-id">新摄影师编号</label><input id="photog-id" placeholder="字母数字" autocomplete="off"></div>
      <div><label for="photog-name">摄影师姓名</label><input id="photog-name" placeholder="可以是中文" autocomplete="off"></div>
    </div>
    <div class="actions"><button type="button" id="add-photog" class="secondary">登记摄影师</button></div>
    <label for="batch">批次编号（可留空）</label><input id="batch" placeholder="留空则按扫描内容生成" autocomplete="off">
    <div class="actions"><button type="button" id="plan-btn">查看计划</button></div>
    <p id="setup-msg" class="note"></p>
  </section>
  <section id="plan" hidden>
    <h2>计划</h2>
    <div id="plan-body"></div>
    <label class="check"><input id="confirm" type="checkbox"><span id="confirm-text"></span></label>
    <div class="actions">
      <button type="button" id="run-btn" disabled>确认并开始拷入</button>
      <button type="button" id="replan" class="secondary">返回修改</button>
    </div>
  </section>
  <section id="run" hidden>
    <h2>进度与结果</h2>
    <div id="progress-bar" aria-hidden="true"><span></span></div>
    <p id="run-msg"></p>
    <div id="run-body"></div>
    <div class="actions">
      <button type="button" id="reveal" class="secondary" hidden>打开成品目录</button>
      <button type="button" id="quit" class="secondary">退出导入界面</button>
    </div>
  </section>
</main>
<script>
const csrf = document.querySelector('meta[name=csrf]').content;
const $ = (id) => document.getElementById(id);
let workspace = null;
let plan = null;
let running = false;
function say(id, text, kind) {
  const node = $(id);
  node.textContent = text || '';
  node.className = kind ? kind : 'note';
}
async function api(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type':'application/json', 'X-Cetacea-CSRF': csrf},
    body: JSON.stringify(body || {})
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}
function option(select, value, text) {
  const node = document.createElement('option');
  node.value = value;
  node.textContent = text;
  select.appendChild(node);
}
function fill(select, rows, blank, label) {
  select.replaceChildren();
  option(select, '', blank);
  for (const row of rows) option(select, row.id, label(row));
}
function showWorkspace(data) {
  workspace = data;
  $('setup').hidden = false;
  const box = $('workspace-now');
  box.hidden = false;
  box.replaceChildren();
  const dl = document.createElement('dl');
  for (const [name, value] of [['状态目录', data.home], ['拷入目标', data.library_root], ['预览目录', data.preview_root]]) {
    const dt = document.createElement('dt'); dt.textContent = name; dl.appendChild(dt);
    const dd = document.createElement('dd'); dd.textContent = value; dl.appendChild(dd);
  }
  box.appendChild(dl);
  fill($('source'), data.sources, '选择已有来源', (row) => row.id + '  ' + row.path);
  fill($('order'), data.orders, '选择已有订单', (row) => row.id + '  ' + row.title);
  fill($('photographer'), data.photographers, '选择已有摄影师', (row) => row.id + '  ' + row.name);
}
function bytes(n) {
  if (n < 1024) return n + ' 字节';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KiB';
  if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MiB';
  return (n / 1073741824).toFixed(2) + ' GiB';
}
function showPlan(data) {
  plan = data;
  $('plan').hidden = false;
  $('confirm').checked = false;
  $('run-btn').disabled = true;
  const body = $('plan-body');
  body.replaceChildren();
  const banner = document.createElement('p');
  banner.className = 'banner';
  banner.textContent = '仅拷入。不会调用模型，不会连接 Lightroom，也不会因为缺 NEF 或 JPG 跳过另一张已存在的照片。';
  body.appendChild(banner);
  const dl = document.createElement('dl');
  const kinds = Object.entries(data.kinds).map(([k, v]) => k + ' ' + v).join('，') || '无';
  const exts = Object.entries(data.extensions).map(([k, v]) => k + ' ' + v).join('，') || '无';
  const rows = [
    ['来源', data.source_path], ['订单', data.order_id], ['摄影师', data.photographer_id],
    ['目标目录', data.destination], ['数量', String(data.file_count)], ['大小', bytes(data.total_bytes)],
    ['种类', kinds], ['格式', exts], ['计划摘要', data.plan_digest]
  ];
  for (const [name, value] of rows) {
    const dt = document.createElement('dt'); dt.textContent = name; dl.appendChild(dt);
    const dd = document.createElement('dd'); dd.textContent = value; dl.appendChild(dd);
  }
  body.appendChild(dl);
  if (data.names.length) {
    const list = document.createElement('p');
    list.className = 'note';
    list.textContent = (data.names_truncated ? '部分文件名：' : '文件：') + data.names.join('、');
    body.appendChild(list);
  }
  $('confirm-text').textContent = '我确认把这 ' + data.file_count + ' 个文件拷入「' + data.destination + '」，并只批准摘要 ' + data.plan_digest.slice(0, 12) + '。';
}
const STATE_LABEL = {WAITING_APPROVAL:'等待确认', RUNNING:'正在拷入', COMPLETED:'已完成', FAILED:'失败', PAUSED:'已暂停', CANCELLED:'已取消'};
function drawRun(data) {
  $('run').hidden = false;
  const total = data.file_count || 0;
  const done = (data.counts.VERIFIED || 0) + (data.counts.FAILED || 0) + (data.counts.CONFLICT || 0);
  $('progress-bar').firstElementChild.style.width = (total ? Math.round(100 * done / total) : 0) + '%';
  const msg = $('run-msg');
  msg.className = data.state === 'COMPLETED' ? 'banner' : (data.state === 'FAILED' ? 'bad' : 'banner');
  const bits = ['状态 ' + (STATE_LABEL[data.state] || data.state)];
  if (data.error) bits.push(data.error);
  if (data.job_error) bits.push(data.job_error);
  msg.textContent = bits.join('。');
  const body = $('run-body');
  body.replaceChildren();
  const dl = document.createElement('dl');
  const dt = document.createElement('dt'); dt.textContent = '目标目录'; dl.appendChild(dt);
  const dd = document.createElement('dd'); dd.textContent = data.destination; dl.appendChild(dd);
  body.appendChild(dl);
  const table = document.createElement('table');
  const head = document.createElement('tr');
  for (const name of ['文件', '种类', '结果', '说明']) {
    const th = document.createElement('th'); th.textContent = name; head.appendChild(th);
  }
  table.appendChild(head);
  for (const file of data.files) {
    const tr = document.createElement('tr');
    for (const value of [file.rel_path, file.kind, file.status, file.detail]) {
      const td = document.createElement('td'); td.textContent = value || ''; tr.appendChild(td);
    }
    table.appendChild(tr);
  }
  body.appendChild(table);
  $('reveal').hidden = data.state === 'RUNNING';
}
async function poll(taskId) {
  const data = await api('/api/task', {task_id: taskId});
  drawRun(data);
  if (data.state === 'RUNNING' || data.busy) setTimeout(() => poll(taskId), 500);
  else running = false;
}
$('open-btn').onclick = async () => {
  try { showWorkspace(await api('/api/workspace/open', {home: $('open-home').value})); say('workspace-msg', '已打开工作台。照片尚未扫描。'); }
  catch (error) { say('workspace-msg', error.message, 'bad'); }
};
$('create-btn').onclick = async () => {
  try {
    showWorkspace(await api('/api/workspace/create', {home: $('new-home').value, library: $('new-library').value, preview: $('new-preview').value}));
    say('workspace-msg', '已新建工作台。请核对上面三个路径。');
  } catch (error) { say('workspace-msg', error.message, 'bad'); }
};
async function refresh() { showWorkspace(await api('/api/workspace/current', {})); }
$('add-source').onclick = async () => {
  try { await api('/api/sources', {source_id: $('source-id').value, path: $('source-path').value}); await refresh(); say('setup-msg', '来源已登记，尚未扫描。'); }
  catch (error) { say('setup-msg', error.message, 'bad'); }
};
$('add-order').onclick = async () => {
  try { await api('/api/orders', {order_id: $('order-id').value, title: $('order-title').value}); await refresh(); say('setup-msg', '订单已登记。'); }
  catch (error) { say('setup-msg', error.message, 'bad'); }
};
$('add-photog').onclick = async () => {
  try { await api('/api/photographers', {photographer_id: $('photog-id').value, name: $('photog-name').value}); await refresh(); say('setup-msg', '摄影师已登记。'); }
  catch (error) { say('setup-msg', error.message, 'bad'); }
};
$('plan-btn').onclick = async () => {
  try {
    showPlan(await api('/api/plan', {
      source_id: $('source').value, order_id: $('order').value, photographer_id: $('photographer').value, batch_label: $('batch').value
    }));
    say('setup-msg', '');
  } catch (error) { say('setup-msg', error.message, 'bad'); }
};
$('confirm').onchange = () => { $('run-btn').disabled = !$('confirm').checked || running; };
$('replan').onclick = () => { $('plan').hidden = true; plan = null; };
$('run-btn').onclick = async () => {
  if (running || !plan || !$('confirm').checked) return;
  running = true;
  $('run-btn').disabled = true;
  $('plan-btn').disabled = true;
  try {
    const data = await api('/api/import', {task_id: plan.task_id, plan_digest: plan.plan_digest, destination: plan.destination});
    drawRun(data);
    poll(plan.task_id);
  } catch (error) {
    running = false;
    $('run-btn').disabled = !$('confirm').checked;
    $('plan-btn').disabled = false;
    say('setup-msg', error.message, 'bad');
  }
};
$('reveal').onclick = async () => {
  try { const data = await api('/api/reveal', {task_id: plan.task_id}); say('run-msg', data.opened ? '已打开成品目录。' : '请在访达中打开：' + data.destination, 'banner'); }
  catch (error) { say('run-msg', error.message, 'bad'); }
};
$('quit').onclick = async () => { await api('/api/shutdown', {}); document.body.insertAdjacentText('beforeend', ''); };
</script>
</body>
</html>
"""

KIND_LABEL = {'raw': 'RAW（含 NEF）', 'jpeg': 'JPEG', 'sidecar': '侧车', 'other': '其他'}


class IngestOnlyAdapter(LightroomAdapter):
    """Fails closed if an ingest desk accidentally reaches Lightroom."""
    mock = False
    def status(self):
        raise RuntimeError('导入界面不连接 Lightroom')
    def register(self, files):
        raise RuntimeError('导入界面不连接 Lightroom')
    def apply_preset(self, photo_refs, preset):
        raise RuntimeError('导入界面不连接 Lightroom')
    def export_jpeg(self, photo_refs, dest_dir, max_edge, quality):
        raise RuntimeError('导入界面不连接 Lightroom')


def default_workbench(home):
    return Workbench(home, adapter=IngestOnlyAdapter())


def reveal_destination(path):
    if sys.platform != 'darwin':
        return False
    opener = Path('/usr/bin/open')
    if not opener.is_file():
        return False
    subprocess.run([str(opener), str(path)], check=False)
    return True


def existing_directory(value, label):
    if not isinstance(value, str) or not value.startswith('/') or '\x00' in value:
        raise ValueError(label + '需要绝对路径')
    path = Path(value)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(label + '必须是已存在的真实目录，请先在访达中建好')
    return path


class ImportDesk:
    def __init__(self, host='127.0.0.1', port=0, workbench_factory=None, reveal=None):
        if host != '127.0.0.1':
            raise ValueError('导入界面只监听 127.0.0.1')
        self.host = host
        self.factory = workbench_factory or default_workbench
        self.reveal = reveal if reveal is not None else reveal_destination
        self.lock = threading.Lock()
        self.jobs = set()
        self.job_errors = {}
        self.home = None
        self.stopping = False
        self.csrf = __import__('secrets').token_urlsafe(32)
        self.httpd = ThreadingHTTPServer((host, port), self._handler())
        self.thread = None

    @property
    def port(self):
        return self.httpd.server_address[1]

    @property
    def origin(self):
        return f'http://127.0.0.1:{self.port}'

    def _handler(self):
        desk = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, fmt, *args):
                return
            def do_GET(self):
                desk._get(self)
            def do_POST(self):
                desk._post(self)
            def handle_error(self, request, client_address):
                if not desk.stopping:
                    super().handle_error(request, client_address)
        return Handler

    def start(self):
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self.origin

    def stop(self):
        self.stopping = True
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def request_stop(self):
        threading.Thread(target=self.httpd.shutdown, daemon=True).start()

    def workbench(self):
        if self.home is None:
            raise ValueError('请先打开或新建工作台')
        return self.factory(self.home)

    def _send(self, handler, status, payload, content_type='application/json; charset=utf-8', cookie=False):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        handler.send_response(status)
        handler.send_header('Content-Type', content_type)
        handler.send_header('Content-Length', str(len(body)))
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'")
        handler.send_header('Referrer-Policy', 'no-referrer')
        if cookie:
            handler.send_header('Set-Cookie', f'cetacea_desk={self.csrf}; HttpOnly; SameSite=Strict; Path=/')
        handler.end_headers()
        handler.wfile.write(body)

    def _authorized(self, handler):
        host = handler.headers.get('Host', '')
        if host != f'127.0.0.1:{self.port}':
            self._send(handler, 403, {'error': '只接受本机访问'})
            return False
        origin = handler.headers.get('Origin')
        if origin not in (None, self.origin):
            self._send(handler, 403, {'error': '拒绝跨站请求'})
            return False
        cookie = handler.headers.get('Cookie', '')
        token = handler.headers.get('X-Cetacea-CSRF', '')
        if f'cetacea_desk={self.csrf}' not in cookie.split('; ') or token != self.csrf:
            self._send(handler, 403, {'error': '缺少本页确认'})
            return False
        return True

    def _get(self, handler):
        path = urlparse(handler.path).path
        if handler.headers.get('Host', '') != f'127.0.0.1:{self.port}':
            self._send(handler, 403, {'error': '只接受本机访问'})
            return
        if path != '/':
            self._send(handler, 404, {'error': '没有这个页面'})
            return
        page = PAGE.replace('__CSRF__', self.csrf).encode()
        self._send(handler, 200, page, 'text/html; charset=utf-8', cookie=True)

    def _post(self, handler):
        if not self._authorized(handler):
            return
        length = int(handler.headers.get('Content-Length', '0') or 0)
        if length > 1_000_000:
            self._send(handler, 400, {'error': '请求过大'})
            return
        try:
            body = json.loads(handler.rfile.read(length) or b'{}')
            if not isinstance(body, dict):
                raise ValueError('请求格式不正确')
            path = urlparse(handler.path).path
            if path == '/api/shutdown':
                self.request_stop()
                self._send(handler, 200, {'stopping': True})
                return
            result = self._dispatch(path, body)
        except (PermissionDenied, InvalidTransition, ValueError, KeyError, OSError) as exc:
            message = '计划已变化，请重新查看并确认' if isinstance(exc, PermissionDenied) else str(exc)
            status = 409 if isinstance(exc, (PermissionDenied, InvalidTransition)) else 400
            self._send(handler, status, {'error': message})
            return
        self._send(handler, 200, result)

    def _dispatch(self, path, body):
        if path == '/api/workspace/open':
            return self._open(body['home'])
        if path == '/api/workspace/create':
            return self._create(body['home'], body['library'], body['preview'])
        if path == '/api/workspace/current':
            return self._view(self.workbench())
        if path == '/api/orders':
            self.workbench().create_order(body['order_id'], body.get('title') or body['order_id'])
            return self._view(self.workbench())
        if path == '/api/photographers':
            self.workbench().add_photographer(body['photographer_id'], body.get('name') or body['photographer_id'])
            return self._view(self.workbench())
        if path == '/api/sources':
            self.workbench().add_source(body['source_id'], body['path'], body.get('label') or body['source_id'])
            return self._view(self.workbench())
        if path == '/api/plan':
            return self._plan(body)
        if path == '/api/import':
            return self._start(body)
        if path == '/api/task':
            return self._progress(body['task_id'])
        if path == '/api/reveal':
            return self._reveal(body['task_id'])
        raise KeyError(path)

    def _open(self, home):
        path = existing_directory(home, '工作台')
        if not (path / 'config.json').is_file():
            raise ValueError('这个目录不是 CETACEA 工作台')
        self.home = path
        return self._view(self.workbench())

    def _create(self, home, library, preview):
        from . import config
        home_path = existing_directory(home, '状态目录')
        library_path = existing_directory(library, '照片库')
        preview_path = existing_directory(preview, '预览目录')
        if (home_path / 'config.json').exists():
            raise ValueError('工作台已存在，请改用打开')
        config.initialize(home_path, library_path, preview_path)
        self.home = home_path
        return self._view(self.workbench())

    def _view(self, workbench):
        return {
            'home': str(workbench.home),
            'library_root': workbench.config['library_root'],
            'preview_root': workbench.config['preview_root'],
            'orders': [{'id': row['order_id'], 'title': row['title']} for row in workbench.list_orders()],
            'photographers': [{'id': row['photographer_id'], 'name': row['name']} for row in workbench.list_photographers()],
            'sources': [{'id': key, 'path': value['path'], 'label': value.get('label', key), 'kind': value.get('kind', '')}
                        for key, value in workbench.list_sources().items()],
        }

    def _plan(self, body):
        label = body.get('batch_label') or None
        if isinstance(label, str) and not label.strip():
            label = None
        task = self.workbench().plan_import(body['order_id'], body['photographer_id'], body['source_id'], batch_label=label, stages=['ingest'])
        return self._summary(self.workbench(), task)

    def _summary(self, workbench, task):
        plan = task['plan']
        if plan['stages'] != ['ingest'] or 'lightroom' in plan:
            raise ValueError('导入界面只制定仅拷入计划')
        library = Path(workbench.config['library_root'])
        destination = str((library / plan['destination']).resolve())
        kinds, extensions = {}, {}
        names = []
        for item in plan['files']:
            kinds[KIND_LABEL.get(item['kind'], item['kind'])] = kinds.get(KIND_LABEL.get(item['kind'], item['kind']), 0) + 1
            suffix = Path(item['rel_path']).suffix.lower() or '(无扩展名)'
            extensions[suffix] = extensions.get(suffix, 0) + 1
            if len(names) < 40:
                names.append(item['rel_path'])
        return {
            'task_id': task['task_id'], 'plan_digest': task['plan_digest'], 'state': task['state'],
            'source_id': task['source_id'], 'source_path': workbench.config['sources'][task['source_id']]['path'],
            'order_id': task['order_id'], 'photographer_id': task['photographer_id'],
            'library_root': workbench.config['library_root'], 'preview_root': workbench.config['preview_root'],
            'destination': destination, 'file_count': len(plan['files']), 'total_bytes': plan['total_bytes'],
            'kinds': kinds, 'extensions': extensions, 'names': names, 'names_truncated': len(plan['files']) > len(names),
            'ingest_only': True, 'stages': plan['stages'],
        }

    def _approved(self, task_id, digest):
        with db.connect(self.home) as connection:
            return connection.execute(
                'SELECT 1 FROM approvals WHERE task_id=? AND plan_digest=? AND revoked_at IS NULL',
                (task_id, digest)).fetchone() is not None

    def _start(self, body):
        task_id, digest, destination = body['task_id'], body['plan_digest'], body['destination']
        with self.lock:
            if task_id in self.jobs:
                return self._progress(task_id, already=True)
            workbench = self.workbench()
            task = workbench.get_task(task_id)
            summary = self._summary(workbench, task)
            if task['plan_digest'] != digest or summary['destination'] != destination:
                raise PermissionDenied('计划已变化，请重新查看并确认')
            if not task['plan']['files']:
                raise ValueError('没有可拷贝的文件')
            if task['state'] == 'COMPLETED':
                return self._progress(task_id)
            if task['state'] == 'RUNNING':
                return self._progress(task_id, already=True)
            if task['state'] == 'WAITING_APPROVAL':
                if not self._approved(task_id, digest):
                    workbench.approve(task_id, digest)
            elif task['state'] not in {'PAUSED', 'FAILED'}:
                raise InvalidTransition('当前状态不能开始拷入')
            self.jobs.add(task_id)
            self.job_errors.pop(task_id, None)
        threading.Thread(target=self._execute, args=(task_id, digest), daemon=True).start()
        return self._progress(task_id)

    def _execute(self, task_id, digest):
        try:
            self.factory(self.home).execute(task_id, digest)
        except Exception as exc:
            self.job_errors[task_id] = str(exc)
        finally:
            with self.lock:
                self.jobs.discard(task_id)

    def _progress(self, task_id, already=False):
        workbench = self.workbench()
        task = workbench.get_task(task_id)
        summary = self._summary(workbench, task)
        files = []
        counts = {}
        for asset in workbench.list_assets(task_id=task_id):
            counts[asset['status']] = counts.get(asset['status'], 0) + 1
            detail = '已从目标重新读回并比对 SHA-256' if asset['status'] == 'VERIFIED' else (asset.get('error') or '')
            files.append({'rel_path': asset['rel_path'], 'kind': asset['kind'], 'status': asset['status'], 'detail': detail, 'size': asset['size']})
        return {**summary, 'counts': counts, 'files': files, 'error': task.get('error'),
                'job_error': self.job_errors.get(task_id), 'busy': task_id in self.jobs, 'already': already}

    def _reveal(self, task_id):
        workbench = self.workbench()
        task = workbench.get_task(task_id)
        if task_id in self.jobs or task['state'] == 'RUNNING':
            raise ValueError('拷入尚未结束')
        summary = self._summary(workbench, task)
        path = Path(summary['destination'])
        if not path.is_relative_to(Path(workbench.config['library_root']).resolve()):
            raise ValueError('成品目录不在照片库内')
        if not path.is_dir():
            raise ValueError('成品目录还不存在')
        return {'destination': str(path), 'opened': bool(self.reveal(path))}


def serve(port=8765, open_browser=True):
    last = None
    desk = None
    for candidate in range(port, port + 10):
        try:
            desk = ImportDesk(port=candidate)
            break
        except OSError as exc:
            last = exc
    if desk is None:
        raise last
    origin = desk.start()
    print(f'CETACEA 导入界面：{origin}', flush=True)
    print('退出：在网页中点击「退出导入界面」，或在此窗口按 Ctrl+C。', flush=True)
    if open_browser:
        webbrowser.open(origin)
    try:
        desk.thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        desk.httpd.server_close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='打开本机 CETACEA 导入界面')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    if args.port <= 0 or args.port > 65535:
        parser.error('端口不正确')
    return serve(args.port, open_browser=not args.no_browser)


if __name__ == '__main__':
    raise SystemExit(main())
