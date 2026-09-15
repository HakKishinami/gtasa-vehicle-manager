// A package that points a new model at a GXT key the game already defines
// inherits that display name: the install wizard must leave the GXT/name
// fields empty and switch FXT generation off, so nothing renames the vanilla
// entry. Package-declared custom keys must keep the old prefill behavior.
// Run with: node --test tests/test_install_fxt_default.cjs (no npm dependencies).
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
  run('vanillaVehicles = [{ model: "buffalo", name: "Buffalo", id: 402, type: "car" }];');
  run('appStatus = { modloader_folders: ["Modded Cars", "Addon Cars"], data_folder: "Modded Cars", addon_folder: "Addon Cars" };');
  return { run, node: id => nodes.get(id) };
}

function inspectData({ inherited, singleAddon = true, twoCars = false } = {}) {
  const proposal = inherited
    ? { key: 'BUFFALO', name: 'Buffalo', inherited: true }
    : { key: 'MYCUST', name: 'Buffalo SUX', inherited: false };
  const addon = {
    model: 'buffsux', source_model: 'buffsux', target_model: 'buffsux', type: 'car', is_addon: true,
    fxt_proposal: proposal, has_handling: true, has_carcols: true, has_carmods: true,
  };
  const cars = twoCars
    ? [{ model: 'buffalo', source_model: 'buffalo', target_model: 'buffalo', type: 'car', is_addon: false,
         fxt_proposal: { key: 'BUFFALO', name: 'Buffalo', inherited: true },
         has_handling: true, has_carcols: true, has_carmods: true }, addon]
    : [addon];
  return {
    success: true,
    target_model: singleAddon ? 'buffsux' : 'buffalo',
    proposed_folder_name: 'BuffaloPack',
    target_vehicles: cars,
    primary_dffs: [{ name: 'buffsux.dff', rel: 'buffsux.dff' }],
    primary_txds: [{ name: 'buffsux.txd', rel: 'buffsux.txd' }],
    tuning_dffs: [], tuning_txds: [],
    readme_files: [{ name: 'readme.txt', rel: 'readme.txt' }], other_files: [],
    asset_files: { models: [], textures: [], tuning: [], documents: [], other: [] },
    parsed_config: {}, files: {},
    fxt_proposal: proposal,
    tuning_parts_analysis: [], variant_groups: [],
  };
}

test('an inherited vanilla GXT key leaves the fields empty and FXT off', () => {
  const e = setup();
  e.run('renderInstallStep2')(inspectData({ inherited: true }));
  assert.equal(e.node('installFxtKey').value, '');
  assert.equal(e.node('installFxtName').value, '');
  assert.equal(e.node('chkGenFxt').checked, false);
  assert.equal(e.node('installFxtInheritHint').style.display, 'block');
  assert.match(e.node('installFxtInheritHint').textContent, /BUFFALO/);
});

test('a package-declared custom key keeps the previous prefill', () => {
  const e = setup();
  e.run('renderInstallStep2')(inspectData({ inherited: false }));
  assert.equal(e.node('installFxtKey').value, 'MYCUST');
  assert.equal(e.node('installFxtName').value, 'Buffalo SUX');
  assert.equal(e.node('chkGenFxt').checked, true);
  assert.equal(e.node('installFxtInheritHint').style.display, 'none');
});

test('the wizard opens the inherited addon with empty FXT fields', () => {
  const e = setup();
  e.run('renderInstallStep2')(inspectData({ inherited: true, twoCars: true }));
  const wizard = e.run('wizardVehicles');
  assert.equal(wizard[1].fxt_inherited, true);
  e.run('loadWizardVehicleToForm')(1, true);
  assert.equal(e.node('installFxtKey').value, '');
  assert.equal(e.node('installFxtName').value, '');
  assert.equal(e.node('chkGenFxt').checked, false);
  assert.equal(e.node('installFxtInheritHint').style.display, 'block');
});

test('typing a GXT key hides the inherit hint', () => {
  const e = setup();
  e.run('renderInstallStep2')(inspectData({ inherited: true }));
  assert.equal(e.node('installFxtInheritHint').style.display, 'block');
  e.node('installFxtKey').value = 'MINE';
  e.run('refreshFxtInheritHint')();
  assert.equal(e.node('installFxtInheritHint').style.display, 'none');
});

test('both FXT fields re-evaluate the hint while typing', () => {
  const source = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
  assert.match(source, /fxtKeyInput\.addEventListener\("input", refreshFxtInheritHint\)/);
  assert.match(source, /fxtNameInput\.addEventListener\("input", refreshFxtInheritHint\)/);
});

test('inspector allows empty display name for replacement vehicle and rejects for addon', () => {
  const source = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
  assert.match(source, /isAddonModel\(model\)/);
  assert.match(source, /toast\.fxtRevertedToVanilla/);
  assert.match(source, /inspect\.fxtEditEmptyAddon/);
});

