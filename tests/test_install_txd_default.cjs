// The install wizard must prefill a new addon model's TXD with the name the
// author declared in vehicles.ide ("ID, sentxs, sentinel, car, ..."): the
// package ships no sentxs.txd and the model is meant to share sentinel.txd.
// Run with: node --test tests/test_install_txd_default.cjs (no npm dependencies).
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
  toggle(name, force) {
    const on = force === undefined ? !this.values.has(name) : force;
    if (on) this.values.add(name); else this.values.delete(name);
    return on;
  }
}

class Element {
  constructor(tag) {
    this.tagName = tag || 'div';
    this.textContent = '';
    this.style = {};
    this.dataset = {};
    this.classList = new ClassList();
    this.listeners = {};
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.children = [];
    this.options = [];
  }
  addEventListener(name, fn) { (this.listeners[name] = this.listeners[name] || []).push(fn); }
  removeEventListener() {}
  click() { for (const fn of [...(this.listeners.click || [])]) fn(); }
  getAttribute() { return null; }
  setAttribute() {}
  removeAttribute() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  appendChild(child) { this.children.push(child); return child; }
  append(...children) { this.children.push(...children); }
  insertBefore(child) { this.children.push(child); return child; }
  remove() {}
  focus() {}
  blur() {}
  set innerHTML(value) { this._html = value; }
  get innerHTML() { return this._html || ''; }
}

function setup() {
  const nodes = new Map();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) nodes.set(match[1], new Element());
  const document = {
    addEventListener() {},
    getElementById: id => nodes.get(id) || null,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: tag => new Element(tag),
    body: new Element('body'),
    activeElement: null,
  };
  const ctx = {
    document,
    console: { log() {}, error() {} },
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    requestAnimationFrame: () => 0,
    URLSearchParams,
    AbortController,
    localStorage: { getItem: () => null, setItem() {} },
    fetch: async () => ({ ok: true, json: async () => ({ success: true }) }),
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  const run = code => vm.runInContext(code, ctx);
  run(fs.readFileSync(path.join(web, 'i18n.js'), 'utf8'));
  run(fs.readFileSync(path.join(web, 'install-assets.js'), 'utf8'));
  run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));
  // Minimal vanilla list and status so replace/addon classification resolves.
  run('vanillaVehicles = [{ model: "sentinel", name: "Sentinel", id: 405, type: "car" }];');
  run('appStatus = { modloader_folders: ["Modded Cars", "Addon Cars"], data_folder: "Modded Cars", addon_folder: "Addon Cars" };');
  return { run, node: id => nodes.get(id) };
}

function targetVehicles(declaredTxd) {
  const cars = [
    {
      model: 'sentinel', source_model: 'sentinel', target_model: 'sentinel', type: 'car',
      is_addon: false, declared_txd: 'sentinel', has_handling: true, has_carcols: true, has_carmods: true,
      fxt_proposal: { key: 'SENTINL', name: 'Sentinel' },
    },
  ];
  if (declaredTxd !== null) {
    cars.push({
      model: 'sentxs', source_model: 'sentxs', target_model: 'sentxs', type: 'car', is_addon: true,
      declared_txd: declaredTxd, has_handling: true, has_carcols: true, has_carmods: true,
      fxt_proposal: { key: 'SENTXS', name: 'Sentinel XS' },
    });
  }
  return cars;
}

function inspectData({ declaredTxd = 'sentinel', singleAddon = false } = {}) {
  const cars = singleAddon ? targetVehicles(declaredTxd).slice(1) : targetVehicles(declaredTxd);
  return {
    success: true,
    target_model: singleAddon ? 'sentxs' : 'sentinel',
    proposed_folder_name: 'Sentinel84',
    target_vehicles: cars,
    primary_dffs: [{ name: 'sentinel.dff', rel: 'sentinel.dff' }, { name: 'sentxs.dff', rel: 'sentxs.dff' }],
    primary_txds: [{ name: 'sentinel.txd', rel: 'sentinel.txd', model: 'sentinel' }],
    tuning_dffs: [], tuning_txds: [],
    readme_files: [{ name: 'readme.txt', rel: 'readme.txt' }], other_files: [],
    asset_files: { models: [], textures: [], tuning: [], documents: [], other: [] },
    parsed_config: {}, files: {},
    fxt_proposal: { key: singleAddon ? 'SENTXS' : 'SENTINL', name: singleAddon ? 'Sentinel XS' : 'Sentinel' },
    tuning_parts_analysis: [], variant_groups: [],
  };
}

test('wizard keeps the TXD the author declared for a new model', () => {
  const e = setup();
  e.run('renderInstallStep2')(inspectData());
  const wizard = e.run('wizardVehicles');
  assert.equal(wizard[0].install_mode, 'replace');
  assert.equal(wizard[0].target_txd, '');
  assert.equal(wizard[1].install_mode, 'addon');
  assert.equal(wizard[1].declared_txd, 'sentinel');
  assert.equal(wizard[1].target_txd, 'sentinel');

  e.run('loadWizardVehicleToForm')(1, true);
  assert.equal(e.node('installNewModelName').value, 'sentxs');
  assert.equal(e.node('installNewTxdName').value, 'sentinel');
});

test('a renamed addon follows the model name only when the TXD was its own', () => {
  const e = setup();
  e.run('renderInstallStep2')(inspectData({ declaredTxd: 'sentxs' }));
  const wizard = e.run('wizardVehicles');
  assert.equal(wizard[1].target_txd, 'sentxs');
});

test('single addon install prefills the declared TXD', () => {
  const e = setup();
  e.run('renderInstallStep2')(inspectData({ singleAddon: true }));
  assert.equal(e.run('singleInstallMode'), 'addon');
  assert.equal(e.node('installNewModelName').value, 'sentxs');
  assert.equal(e.node('installNewTxdName').value, 'sentinel');
});

test('an addon without a declared TXD still defaults to the model name', () => {
  const e = setup();
  e.run('renderInstallStep2')(inspectData({ singleAddon: true, declaredTxd: '' }));
  assert.equal(e.node('installNewTxdName').value, 'sentxs');
});
