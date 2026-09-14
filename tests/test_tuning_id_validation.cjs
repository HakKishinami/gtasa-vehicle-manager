// Run with node --test tests/test_tuning_id_validation.cjs. No DOM dependency.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.listeners = {};
    this.className = '';
    this.checked = false;
    this.disabled = false;
    this.value = '';
    this.classList = {
      toggle: (name, on) => {
        const names = new Set(this.className.split(/\s+/));
        if (on) names.add(name); else names.delete(name);
        this.className = [...names].join(' ');
      },
      contains: name => this.className.split(/\s+/).includes(name)
    };
  }
  set value(value) { this._value = String(value); }
  get value() { return this._value; }
  set innerHTML(value) { this.children = []; this._html = value; }
  get innerHTML() { return this._html || ''; }
  appendChild(child) { this.children.push(child); return child; }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  addEventListener(event, fn) { (this.listeners[event] ||= []).push(fn); }
  async emit(event) { for (const fn of this.listeners[event] || []) await fn(); }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [
      ...(selector.startsWith('.') ? child.classList.contains(selector.slice(1)) : child.tagName === selector) ? [child] : [],
      ...child.querySelectorAll(selector)
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
function setup() {
  const nodes = new Map();
  const node = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  const timers = new Map();
  const calls = [];
  const toasts = [];
  let nextTimer = 0;
  const ctx = {
    document: { getElementById: node, createElement: tag => new Element(tag) },
    setTimeout: fn => { timers.set(++nextTimer, fn); return nextTimer; },
    clearTimeout: id => timers.delete(id),
    console,
    t: (key, fallback) => fallback,
    loc: value => value.en,
    showToast: (...args) => toasts.push(args),
    fetch: async url => { calls.push(url); return response({ is_free: true }); },
    currentInspectData: { inspect_dir: 'source', parsed_config: {} },
    wizardVehicles: [],
    validateNewInstallName: () => true,
    effectiveInstallTarget: () => 'euros',
    effectiveInstallTxd: () => 'euros',
    effectiveInstallHandling: () => 'EUROS',
    installTargetSourceModel: () => 'euros',
    installSourceType: () => 'car',
    refreshInstallReplaceHint() {},
    anyInstallClassMismatch: () => null,
    collectVariantChoices: () => ({}),
    collectAddonIdAssignments: () => ({}),
    ensureKillableLimit: async () => null,
    InstallReminder: { beforeInstall: async () => ({ action: 'continue' }) },
    renderInstallResult() {}, loadSystemStatus() {}, loadMods() {},
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  const run = code => vm.runInContext(code, ctx);
  run(source.slice(source.indexOf('// ---------------- Tuning Parts Table & Live ID Check'),
    source.indexOf('// ---------------- ID Pool Inspector Modal')));
  run(source.slice(source.indexOf('  // Execute Install Button'), source.indexOf('  // Go to Library button')));
  node('installSubfolderName').value = 'Euros';
  const render = (ids = [11688, 11689]) => ctx.renderTuningPartsTable(ids.map((id, i) => ({
    part_name: ['rf_a_eu', 'rf_c_eu'][i], assigned_id: id, status: 'suggested_safe'
  })));
  const rows = () => node('installTuningTableBody').querySelectorAll('tr');
  const states = () => rows().map(row => row.dataset.idState);
  const input = index => rows()[index].querySelector('.input-id-edit');
  const check = index => rows()[index].querySelector('.chk-tuning-part');
  const flush = async () => {
    const pending = [...timers.values()]; timers.clear();
    await Promise.all(pending.map(fn => fn()));
  };
  return { ctx, node, run, render, rows, states, input, check, flush, calls, toasts };
}
function response(result, success = true) { return { ok: true, json: async () => ({ success, result }) }; }
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }

test('both duplicate rows turn red immediately and installation is blocked', async () => {
  const h = setup(); h.render(); await h.flush();
  assert.equal(h.node('btnExecuteInstall').disabled, false);
  h.input(1).value = '11688'; await h.input(1).emit('input');
  assert.deepEqual(h.states(), ['duplicate', 'duplicate']);
  assert.ok(h.rows().every(row => row.querySelector('.input-id-edit').classList.contains('has-conflict')));
  assert.match(h.node('tuningTableSummaryText').textContent, /2 part\(s\) need/);
  assert.equal(h.node('btnExecuteInstall').disabled, true);
  await h.node('btnExecuteInstall').emit('click'); // even a programmatic click cannot bypass it
  assert.ok(h.calls.every(url => !url.includes('/installer/install')));
  assert.match(h.toasts.at(-1)[0], /Resolve/);
});

test('changing either duplicate checks the entire batch; rapid edits lose no row', async () => {
  const h = setup(); h.render([11688, 11688]);
  h.input(0).value = '12000'; await h.input(0).emit('input');
  h.input(1).value = '12001'; await h.input(1).emit('input');
  assert.deepEqual(h.states(), ['pending', 'pending']);
  assert.equal(h.node('btnExecuteInstall').disabled, true);
  await h.flush();
  assert.deepEqual(h.states(), ['safe', 'safe']);
  assert.deepEqual(h.calls.sort(), ['/api/ids/check?id=12000', '/api/ids/check?id=12001']);
});

test('excluding and reselecting a duplicate updates both rows and the summary', async () => {
  const h = setup(); h.render([11688, 11688]);
  h.check(1).checked = false; await h.check(1).emit('change'); await h.flush();
  assert.deepEqual(h.states(), ['safe', 'excluded']);
  assert.equal(h.input(1).disabled, true);
  assert.equal(h.node('btnExecuteInstall').disabled, false);
  assert.deepEqual(JSON.parse(JSON.stringify(h.ctx.collectExcludedTuningParts())), ['rf_c_eu']);
  h.check(1).checked = true; await h.check(1).emit('change');
  assert.deepEqual(h.states(), ['duplicate', 'duplicate']);
  h.node('chkAllTuningParts').checked = false; h.node('chkAllTuningParts').onchange();
  assert.deepEqual(h.states(), ['excluded', 'excluded']);
  assert.equal(h.node('btnExecuteInstall').disabled, false);
  h.node('chkAllTuningParts').checked = true; h.node('chkAllTuningParts').onchange();
  assert.deepEqual(h.states(), ['duplicate', 'duplicate']);
});

test('old free replies cannot overwrite newer duplicates', async () => {
  const h = setup(); const old = deferred(); h.ctx.fetch = () => old.promise;
  h.render(); const checking = h.flush();
  h.input(1).value = '11688'; await h.input(1).emit('input');
  old.resolve(response({ is_free: true })); await checking;
  assert.deepEqual(h.states(), ['duplicate', 'duplicate']);
  assert.equal(h.node('btnExecuteInstall').disabled, true);
});

test('a new pack clears old rows and ignores outstanding validation', async () => {
  const h = setup(); const old = deferred(); h.ctx.fetch = () => old.promise;
  h.render(); const checking = h.flush(); h.render([]);
  old.resolve(response({ is_free: false, name: 'other' })); await checking;
  assert.deepEqual(h.states(), []);
  assert.equal(h.node('btnExecuteInstall').disabled, false);
  assert.deepEqual(Object.keys(h.ctx.collectTuningIdAssignments()), []);
});

test('invalid numbers remain invalid instead of being truncated or omitted', async () => {
  const h = setup();
  for (const value of ['', '999', '65536', '11688.5', '1e4', '-11688']) {
    h.render([value]); await h.flush();
    assert.deepEqual(h.states(), ['invalid'], value);
    assert.equal(h.ctx.collectTuningIdAssignments().rf_a_eu, value);
  }
  for (const value of ['1000', '65535']) {
    h.render([value]); await h.flush(); assert.deepEqual(h.states(), ['safe']);
  }
});

test('occupied IDs and failed checks fail closed, with a working retry', async () => {
  const h = setup(); h.ctx.fetch = async () => response({ is_free: false, name: 'other', file: 'other.ide' });
  h.render([11688]); await h.flush(); assert.deepEqual(h.states(), ['occupied']);
  h.ctx.fetch = async () => { throw new Error('offline'); };
  await h.ctx.refreshTuningValidation(true); assert.deepEqual(h.states(), ['error']);
  assert.equal(h.node('btnExecuteInstall').disabled, true);
  h.ctx.fetch = async () => response({ is_free: true });
  await h.rows()[0].querySelector('.tuning-status-cell').children[0].emit('click');
  assert.deepEqual(h.states(), ['safe']);
  assert.equal(h.node('btnExecuteInstall').disabled, false);
  h.ctx.fetch = async () => response(null, false);
  await h.ctx.refreshTuningValidation(true); assert.deepEqual(h.states(), ['error']);
});

test('reinstalling the same registered model at its own ID is allowed', async () => {
  const h = setup(); h.ctx.fetch = async () => response({ is_free: false, name: 'RF_A_EU' });
  h.render([11688]); await h.flush(); assert.deepEqual(h.states(), ['safe']);
});

test('auto-assign checks the returned IDs instead of blindly marking them safe', async () => {
  const h = setup(); h.render([11688, 11688]);
  h.ctx.fetch = async url => url.includes('/allocate')
    ? { ok: true, json: async () => ({ success: true, allocated: [12000, 12001] }) }
    : response({ is_free: !url.endsWith('12001'), name: 'other' });
  await h.node('btnAutoReassignIds').onclick();
  assert.deepEqual(h.states(), ['safe', 'occupied']);
  assert.equal(h.node('btnExecuteInstall').disabled, true);
  assert.equal(h.toasts.length, 0);
  h.ctx.fetch = async url => url.includes('/allocate')
    ? { ok: true, json: async () => ({ success: true, allocated: [12002, 12003] }) }
    : response({ is_free: true });
  await h.node('btnAutoReassignIds').onclick();
  assert.deepEqual(h.states(), ['safe', 'safe']);
  assert.equal(h.node('btnExecuteInstall').disabled, false);
  assert.match(h.toasts.at(-1)[0], /Assigned safe IDs/);
});

test('late auto-assign results do not overwrite a subsequent edit', async () => {
  const h = setup(); h.render(); const allocation = deferred();
  h.ctx.fetch = () => allocation.promise;
  const assigning = h.node('btnAutoReassignIds').onclick();
  h.input(0).value = '13000'; await h.input(0).emit('input');
  allocation.resolve({ ok: true, json: async () => ({ success: true, allocated: [12000, 12001] }) });
  await assigning; assert.equal(h.input(0).value, '13000');
});

test('install rechecks previously safe IDs before posting', async () => {
  const h = setup(); h.render([11688]); await h.flush();
  h.ctx.fetch = async url => { h.calls.push(url); return response({ is_free: false, name: 'new_owner' }); };
  await h.node('btnExecuteInstall').emit('click');
  assert.deepEqual(h.states(), ['occupied']);
  assert.ok(!h.calls.includes('/api/installer/install'));
});

test('valid IDs are submitted and edits during confirmation cancel that submission', async () => {
  const h = setup(); h.render(); await h.flush(); let posted;
  h.ctx.fetch = async (url, options) => {
    if (url === '/api/installer/install') posted = JSON.parse(options.body);
    return response({ is_free: true });
  };
  await h.node('btnExecuteInstall').emit('click');
  assert.deepEqual(posted.tuning_id_assignments, { rf_a_eu: '11688', rf_c_eu: '11689' });
  assert.equal(h.node('btnExecuteInstall').disabled, false);
  posted = null;
  h.ctx.InstallReminder.beforeInstall = async () => {
    h.input(1).value = '11688'; await h.input(1).emit('input');
    return { action: 'continue' };
  };
  await h.node('btnExecuteInstall').emit('click');
  assert.equal(posted, null);
  assert.equal(h.node('btnExecuteInstall').disabled, true);
  assert.match(h.toasts.at(-1)[0], /changed during confirmation/);
});
