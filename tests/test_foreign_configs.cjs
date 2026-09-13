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
    this.className = '';
    this.classList = new ClassList();
    this.listeners = {};
  }
  addEventListener(name, fn) { (this.listeners[name] = this.listeners[name] || []).push(fn); }
  click() { for (const fn of this.listeners.click || []) fn(); }
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.children.push(item); return item; }
  replaceChildren(...items) { this.children = items; }
  getAttribute() { return null; }
  setAttribute() {}
  set innerHTML(_) { throw Error('Guard rows must be built as text, never HTML'); }
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
      return {ok: true, json: async () => payloadFor(url)};
    },
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  const run = code => vm.runInContext(code, ctx);
  run(fs.readFileSync(path.join(web, 'i18n.js'), 'utf8'));
  run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));
  return {requests, errors, replies, run, node: id => nodes.get(id)};
}

test('the baseline panel and the notice modal expose the config guard', async () => {
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  assert.match(html, /<div class="card" id="foreignConfigsCard">/);
  assert.match(html, /id="foreignConfigsList"/);
  assert.match(html, /<div class="modal" id="foreignConfigsModal">/);
  assert.match(html, /id="foreignConfigsModalList"/);
  assert.match(html, /id="chkForeignConfigsDontRemind"/);
  assert.match(html, /id="btnForeignConfigsGotIt"/);

  const source = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
  assert.match(source, /fetch\("\/api\/foreign-configs\/scan"/);
  assert.match(source, /setupForeignConfigs\(\);/);
  assert.match(source, /runForeignConfigGuard\(\);/);
  assert.match(source, /getElementById\("foreignConfigsModal"\)/);
});

test('i18n defines the config guard copy in English', async () => {
  const e = setup();
  const keys = ['foreign.cardTitle', 'foreign.badgeChecking', 'foreign.badgeCount', 'foreign.badgeNone',
    'foreign.cardHint', 'foreign.none', 'foreign.stateDisabledNow', 'foreign.stateDisabled',
    'foreign.btnOpenFolder', 'foreign.openFailed', 'foreign.chkDontRemind', 'foreign.btnGotIt',
    'foreign.modalTitle', 'foreign.modalDesc', 'foreign.modalIntro', 'foreign.loadFailed'];
  for (const key of keys) {
    const value = e.run(`window.I18N_DICTIONARY.en[${JSON.stringify(key)}]`);
    assert.equal(typeof value, 'string', key + ' must be translated');
    assert.ok(value.length > 0, key + ' must not be empty');
  }
  assert.match(e.run('window.I18N_DICTIONARY.en["foreign.modalIntro"]'), /vmm-disabled/);
});

test('the guard lists what it disabled and warns once per session', async () => {
  const e = setup();
  const payload = {
    success: true,
    checked: true,
    notify: true,
    disabled: [{name: 'handling.cfg', path: 'E:\\Game\\modloader\\Proper Fixes\\Vehicles Config Fix\\handling.cfg',
                disabled_path: 'E:\\Game\\modloader\\Proper Fixes\\Vehicles Config Fix\\handling.cfg.vmm-disabled'}],
    already_disabled: [{name: 'vehicles.ide.vmm-disabled', path: 'E:\\Game\\modloader\\Mod\\vehicles.ide.vmm-disabled'}],
    errors: [],
  };
  e.replies.set('/api/foreign-configs/scan', payload);
  await e.run('runForeignConfigGuard()');

  assert.equal(e.requests[0].url, '/api/foreign-configs/scan');
  assert.equal(e.requests[0].options.method, 'POST');
  assert.equal(e.node('foreignConfigsModal').classList.contains('active'), true);

  const modalRows = e.node('foreignConfigsModalList').children;
  assert.equal(modalRows.length, 2, 'the notice lists what was disabled now and earlier');
  const head = modalRows[0].children[0];
  assert.equal(head.children[0].textContent, 'handling.cfg', 'the file name is its own label');
  assert.equal(head.children[1].textContent, 'just disabled', 'the state is a separate badge');
  assert.equal(head.children[2].textContent, '📂 Open folder');
  assert.equal(modalRows[0].children[1].textContent,
    'E:\\Game\\modloader\\Proper Fixes\\Vehicles Config Fix\\handling.cfg.vmm-disabled');
  assert.doesNotMatch(modalRows[1].className, /foreign-row-new/);

  // The locate button opens the folder the disabled file lives in.
  head.children[2].click();
  await new Promise(resolve => setImmediate(resolve));
  const openRequest = e.requests[e.requests.length - 1];
  assert.equal(openRequest.url, '/api/open-folder');
  assert.deepEqual(JSON.parse(openRequest.options.body),
    {path: 'E:\\Game\\modloader\\Proper Fixes\\Vehicles Config Fix'});

  const listRows = e.node('foreignConfigsList').children;
  assert.equal(listRows.length, 2, 'the panel lists freshly disabled and earlier ones');
  assert.match(listRows[0].className, /foreign-row-new/);
  assert.doesNotMatch(listRows[1].className, /foreign-row-new/);
  assert.equal(listRows[1].children[0].children[1].textContent, 'disabled earlier');
  assert.equal(e.node('foreignConfigsBadge').textContent, '2 disabled');

  // A later run in the same session must not reopen the notice.
  e.node('foreignConfigsModal').classList.remove('active');
  await e.run('runForeignConfigGuard()');
  assert.equal(e.node('foreignConfigsModal').classList.contains('active'), false);
  assert.equal(e.errors.length, 0);
});

test('copies disabled by an earlier run are explained until acknowledged', async () => {
  const e = setup();
  e.replies.set('/api/foreign-configs/scan', {
    success: true, checked: true, notify: true, disabled: [],
    already_disabled: [{name: 'carcols.dat.vmm-disabled',
                        path: 'E:\\Game\\modloader\\Proper Fixes\\Vehicles Config Fix\\carcols.dat.vmm-disabled'}],
    errors: [],
  });
  await e.run('runForeignConfigGuard()');
  assert.equal(e.node('foreignConfigsModal').classList.contains('active'), true,
    'a run that only found earlier copies still explains them');
  const rows = e.node('foreignConfigsModalList').children;
  assert.equal(rows.length, 1);
  assert.doesNotMatch(rows[0].className, /foreign-row-new/);
  assert.equal(e.node('chkForeignConfigsDontRemind').checked, false);
});

test('got it stores the acknowledgement for this game folder', async () => {
  const e = setup();
  e.replies.set('/api/foreign-configs/scan', {
    success: true, checked: true, notify: true,
    disabled: [{name: 'carmods.dat', path: 'p', disabled_path: 'p.vmm-disabled'}],
    already_disabled: [], errors: [],
  });
  await e.run('runForeignConfigGuard()');
  await e.run('acknowledgeForeignConfigs()');
  const ack = e.requests[e.requests.length - 1];
  assert.equal(ack.url, '/api/foreign-configs/ack');
  assert.equal(ack.options.method, 'POST');
  assert.deepEqual(JSON.parse(ack.options.body), {never: false});
  assert.equal(e.node('foreignConfigsModal').classList.contains('active'), false);
});

test('the reminder checkbox is sent as a permanent dismissal', async () => {
  const e = setup();
  e.replies.set('/api/foreign-configs/scan', {
    success: true, checked: true, notify: true, disabled: [],
    already_disabled: [{name: 'shopping.dat.vmm-disabled', path: 'q'}], errors: [],
  });
  await e.run('runForeignConfigGuard()');
  e.node('chkForeignConfigsDontRemind').checked = true;
  await e.run('acknowledgeForeignConfigs()');
  assert.deepEqual(JSON.parse(e.requests[e.requests.length - 1].options.body), {never: true});
});

test('an empty result reports the clear state', async () => {
  const e = setup();
  e.replies.set('/api/foreign-configs/scan',
    {success: true, checked: true, notify: false, disabled: [], already_disabled: [], errors: []});
  await e.run('runForeignConfigGuard()');
  assert.equal(e.node('foreignConfigsModal').classList.contains('active'), false);
  assert.equal(e.node('foreignConfigsBadge').textContent, 'None');
  const rows = e.node('foreignConfigsList').children;
  assert.equal(rows.length, 1);
  assert.match(rows[0].textContent, /No competing copies found/);
});
