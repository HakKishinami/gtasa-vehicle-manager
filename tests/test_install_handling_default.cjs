// The install wizard must prefill an addon model's handling ID with the name the
// author declared in vehicles.ide ("ID, secua, secua, car, SOLAIRSD, SECU, ..."):
// the model shares physics with SOLAIRSD so it must not default to SECUA or invent
// a redundant duplicate handling line. When declared handling differs from model name,
// a cyan hint should notify the user that physics are shared.
// Run with: node --test tests/test_install_handling_default.cjs (no npm dependencies).
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
  run('vanillaVehicles = [{ model: "solair", name: "Solair", id: 458, type: "car" }];');
  run('appStatus = { modloader_folders: ["Modded Cars", "Addon Cars"], data_folder: "Modded Cars", addon_folder: "Addon Cars" };');
  run('setupInstallModeControls();');
  return { run, node: id => nodes.get(id) };
}

function targetVehicles(declaredHandling) {
  return [
    {
      model: 'solairsd', source_model: 'solairsd', target_model: 'solairsd', type: 'car',
      is_addon: true, declared_txd: 'solairsd', declared_handling: 'SOLAIRSD',
      has_handling: true, has_carcols: true, has_carmods: true,
      fxt_proposal: { key: 'SOLAIRS', name: 'Solair Sedan' },
    },
    {
      model: 'secua', source_model: 'secua', target_model: 'secua', type: 'car',
      is_addon: true, declared_txd: 'secua', declared_handling: declaredHandling,
      has_handling: true, has_carcols: true, has_carmods: true,
      fxt_proposal: { key: 'SECU', name: 'Security Solair' },
    },
  ];
}

function inspectData({ declaredHandling = 'SOLAIRSD', singleAddon = false } = {}) {
  const cars = singleAddon ? targetVehicles(declaredHandling).slice(1) : targetVehicles(declaredHandling);
  return {
    success: true,
    target_model: singleAddon ? 'secua' : 'solairsd',
    proposed_folder_name: 'Solair2nd',
    target_vehicles: cars,
    primary_dffs: [{ name: 'solairsd.dff', rel: 'solairsd.dff' }, { name: 'secua.dff', rel: 'secua.dff' }],
    primary_txds: [{ name: 'solairsd.txd', rel: 'solairsd.txd' }, { name: 'secua.txd', rel: 'secua.txd' }],
    tuning_dffs: [], tuning_txds: [],
    readme_files: [{ name: 'readme.txt', rel: 'readme.txt' }], other_files: [],
    asset_files: { models: [], textures: [], tuning: [], documents: [], other: [] },
    parsed_config: {}, files: {},
    fxt_proposal: { key: singleAddon ? 'SECU' : 'SOLAIRS', name: singleAddon ? 'Security Solair' : 'Solair Sedan' },
    tuning_parts_analysis: [], variant_groups: [],
  };
}

test('wizard keeps the handling ID the author declared for an addon model', () => {
  const e = setup();
  e.run('renderInstallStep2')(inspectData());
  const wizard = e.run('wizardVehicles');
  assert.equal(wizard[1].install_mode, 'addon');
  assert.equal(wizard[1].declared_handling, 'SOLAIRSD');
  assert.equal(wizard[1].target_handling, 'SOLAIRSD');

  e.run('loadWizardVehicleToForm')(1, true);
  assert.equal(e.node('installNewModelName').value, 'secua');
  assert.equal(e.node('installNewHandlingId').value, 'SOLAIRSD');
  assert.equal(e.node('installHandlingSharedHint').style.display, 'block');
  assert.match(e.node('installHandlingSharedHint').textContent, /SOLAIRSD/);
});

test('single addon install prefills the declared handling ID and shows shared hint', () => {
  const e = setup();
  e.run('renderInstallStep2')(inspectData({ singleAddon: true }));
  assert.equal(e.run('singleInstallMode'), 'addon');
  assert.equal(e.node('installNewModelName').value, 'secua');
  assert.equal(e.node('installNewHandlingId').value, 'SOLAIRSD');
  assert.equal(e.node('installHandlingSharedHint').style.display, 'block');
  assert.match(e.node('installHandlingSharedHint').textContent, /SOLAIRSD/);
});

test('an addon without a declared handling ID defaults to suggested model name and hides shared hint', () => {
  const e = setup();
  e.run('renderInstallStep2')(inspectData({ singleAddon: true, declaredHandling: '' }));
  assert.equal(e.node('installNewHandlingId').value, 'SECUA');
  assert.equal(e.node('installHandlingSharedHint').style.display, 'none');
});

test('changing handling ID to match model name hides the shared hint', () => {
  const e = setup();
  e.run('renderInstallStep2')(inspectData({ singleAddon: true }));
  assert.equal(e.node('installHandlingSharedHint').style.display, 'block');

  // Simulate user changing handling ID to match model name
  e.node('installNewHandlingId').value = 'SECUA';
  for (const fn of [...(e.node('installNewHandlingId').listeners.input || [])]) fn();
  assert.equal(e.node('installHandlingSharedHint').style.display, 'none');
});
