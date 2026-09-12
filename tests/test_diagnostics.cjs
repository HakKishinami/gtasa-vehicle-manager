const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = path.join(__dirname, '..', 'web');

class ClassList {
  constructor() { this.values = new Set(); }
  add(...names) { for (const name of names) this.values.add(name); }
  remove(...names) { for (const name of names) this.values.delete(name); }
  contains(name) { return this.values.has(name); }
}

class Element {
  constructor() {
    this.children = [];
    this.textContent = '';
    this.hidden = false;
    this.disabled = false;
    this.className = '';
    this.classList = new ClassList();
    this.listeners = {};
  }
  addEventListener(name, fn) { (this.listeners[name] = this.listeners[name] || []).push(fn); }
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.children.push(item); return item; }
  replaceChildren(...items) { this.children = items; }
  click() { for (const fn of this.listeners.click || []) fn(); }
  getAttribute() { return null; }
  setAttribute() {}
  set innerHTML(_) { throw Error('Operation rows must be built as text, never HTML'); }
  get innerHTML() { return ''; }
}

function setup() {
  const nodes = new Map();
  const requests = [];
  const errors = [];
  const replies = new Map();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) nodes.set(match[1], new Element());

  const document = {
    addEventListener() {},
    getElementById: id => nodes.get(id) || null,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => new Element(),
  };
  const payloadFor = url => {
    for (const [needle, payload] of replies) if (url.includes(needle)) return payload;
    return {success: true};
  };
  const ctx = {
    document,
    console: {log() {}, error: (...args) => errors.push(args)},
    setTimeout: () => 0,
    clearTimeout: () => {},
    URLSearchParams, AbortController,
    localStorage: {getItem: () => null, setItem() {}},
    fetch: async (url, options) => {
      requests.push({url, options});
      const payload = payloadFor(url);
      if (payload && payload.__reject) throw Error(payload.__reject);
      return {ok: true, json: async () => payload};
    },
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  const run = code => vm.runInContext(code, ctx);
  run(fs.readFileSync(path.join(web, 'i18n.js'), 'utf8'));
  run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));
  return {requests, errors, replies, run, node: id => nodes.get(id)};
}

test('the header carries a compact log entry that opens the diagnostics modal', async () => {
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  const button = html.match(/<button[^>]*id="btnOpenDiagnostics"[^>]*>[^<]*<\/button>/);
  assert.ok(button, 'the header must expose the log entry');
  assert.match(button[0], /data-i18n="header\.logs"/);
  assert.match(html, /<div class="modal" id="diagnosticsModal">/);
  assert.match(html, /id="btnExportDiagnostics"/);
  assert.match(html, /id="btnOpenDiagnosticsFolder"/);
  assert.match(html, /id="diagnosticsList"/);

  const source = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
  assert.match(source, /getElementById\("btnOpenDiagnostics"\)/);
  assert.match(source, /setupDiagnostics\(\);/);
  assert.match(source, /getElementById\("diagnosticsModal"\)/);
});

test('i18n defines the diagnostics copy in English', async () => {
  const e = setup();
  const keys = ['header.logs', 'header.logsTitle', 'diag.headerTitle', 'diag.headerDesc', 'diag.intro',
    'diag.btnExport', 'diag.btnOpenFolder', 'diag.btnRefresh', 'diag.btnClose', 'diag.recentTitle',
    'diag.empty', 'diag.exporting', 'diag.exported', 'diag.exportedToast', 'diag.loadFailed',
    'diag.statusOk', 'diag.statusFailed', 'diag.operationInstall', 'diag.operationMerge',
    'diag.operationOther', 'diag.noTarget'];
  for (const key of keys) {
    const value = e.run(`window.I18N_DICTIONARY.en[${JSON.stringify(key)}]`);
    assert.equal(typeof value, 'string', key + ' must be translated');
    assert.ok(value.length > 0, key + ' must not be empty');
  }
  const intro = e.run('window.I18N_DICTIONARY.en["diag.intro"]');
  assert.match(intro, /diagnostics\\exports/, 'the instructions must name where the package lands');
  assert.match(intro, /zip/i);
});

test('opening the modal lists what the server recorded', async () => {
  const e = setup();
  e.replies.set('/api/diagnostics?', {success: true, dir: 'D:\\App\\diagnostics', operations: [
    {timestamp: '2026-09-12T20:45:59+08:00', operation: 'install', success: true,
     context: {vehicles: [{source_model: 'zr150', target_model: 'zr350'}]}},
    {timestamp: '2026-09-12T20:50:00+08:00', operation: 'apply_merge', success: false,
     error: '<script>alert(1)</script>', errors: ['<script>alert(1)</script>']},
  ]});
  await e.run('openDiagnosticsModal()');
  assert.equal(e.node('diagnosticsModal').classList.contains('active'), true);
  assert.equal(e.requests[0].url, '/api/diagnostics?limit=50');

  const rows = e.node('diagnosticsList').children;
  assert.equal(rows.length, 2);
  const [ok, failed] = rows;
  assert.match(ok.className, /diagnostics-row/);
  assert.doesNotMatch(ok.className, /\bfailed\b/);
  assert.match(failed.className, /\bfailed\b/);
  assert.equal(ok.children[0].children[0].textContent, 'OK');
  assert.equal(failed.children[0].children[0].textContent, 'Failed');
  assert.equal(ok.children[0].children[1].textContent, 'Install');
  assert.equal(failed.children[0].children[1].textContent, 'Apply merge');
  assert.equal(ok.children[0].children[2].textContent, 'zr150 → zr350');
  assert.equal(failed.children[1].textContent, '<script>alert(1)</script>');
  assert.deepEqual(e.errors, []);
});

test('selecting an operation reveals its full record', async () => {
  const e = setup();
  const entry = {timestamp: '2026-09-12T20:45:59+08:00', operation: 'install', success: false,
                 errors: ['locked'], context: {folder_name: 'ZR150'}};
  e.run('renderDiagnostics(' + JSON.stringify([entry]) + ')');
  const detail = e.node('diagnosticsDetail');
  assert.equal(detail.hidden, true);

  e.node('diagnosticsList').children[0].click();
  assert.equal(detail.hidden, false);
  assert.deepEqual(JSON.parse(detail.textContent), entry);
});

test('creating the package posts to the export endpoint and reports the file', async () => {
  const e = setup();
  e.replies.set('/api/diagnostics/export', {success: true, size: 2048,
    path: 'D:\\App\\diagnostics\\exports\\vmm-diagnostics-20260912-210000.zip'});
  e.replies.set('/api/diagnostics?', {success: true, dir: 'D:\\App\\diagnostics', operations: []});
  await e.run('createDiagnosticsPackage()');

  assert.equal(e.requests[0].url, '/api/diagnostics/export');
  assert.equal(e.requests[0].options.method, 'POST');
  assert.match(e.node('diagnosticsNotice').textContent, /vmm-diagnostics-20260912-210000\.zip/);
  assert.equal(e.node('btnExportDiagnostics').disabled, false);
  assert.match(e.node('toast').textContent, /Diagnostics package created/);
});

test('an unreachable backend is reported instead of breaking the panel', async () => {
  const e = setup();
  e.replies.set('/api/diagnostics?', {__reject: 'connection refused'});
  await e.run('loadDiagnostics()');
  assert.equal(e.errors.length, 1);
  assert.match(e.node('toast').textContent, /Request failed/);
  assert.equal(e.node('diagnosticsList').children.length, 0);
});

test('a missing log renders the empty hint', async () => {
  const e = setup();
  e.replies.set('/api/diagnostics?', {success: true, dir: 'D:\\App\\diagnostics', operations: []});
  await e.run('loadDiagnostics()');
  const rows = e.node('diagnosticsList').children;
  assert.equal(rows.length, 1);
  assert.match(rows[0].textContent, /No operations recorded yet/);
});
