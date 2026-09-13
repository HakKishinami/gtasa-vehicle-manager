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
    this.textContent = '';
    this.style = {};
    this.dataset = {};
    this.classList = new ClassList();
    this.listeners = {};
  }
  addEventListener(name, fn) { (this.listeners[name] = this.listeners[name] || []).push(fn); }
  removeEventListener(name, fn) {
    this.listeners[name] = (this.listeners[name] || []).filter(item => item !== fn);
  }
  click() { for (const fn of [...(this.listeners.click || [])]) fn(); }
  getAttribute() { return null; }
  setAttribute() {}
  querySelectorAll() { return []; }
  appendChild(child) { return child; }
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
    createElement: () => new Element(),
  };
  const ctx = {
    document,
    console: {log() {}, error() {}},
    setTimeout: () => 0,
    clearTimeout: () => {},
    URLSearchParams, AbortController,
    localStorage: {getItem: () => null, setItem() {}},
    fetch: async () => ({ok: true, json: async () => ({success: true})}),
  };
  ctx.window = ctx;
  ctx.alert = () => { throw Error('the themed alert must be used instead of window.alert'); };
  vm.createContext(ctx);
  const run = code => vm.runInContext(code, ctx);
  run(fs.readFileSync(path.join(web, 'i18n.js'), 'utf8'));
  run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));
  return {nodes, run, node: id => nodes.get(id)};
}

test('the themed alert shows the message and acknowledges once', async () => {
  const e = setup();
  const pending = e.run('showAppAlert("vehicles.ide: ALPHA keeps ID 602; the package declared ID 13000")');
  const modal = e.node('appAlertModal');
  assert.equal(modal.classList.contains('active'), true, 'the dialog opens');
  assert.match(e.node('appAlertMessage').textContent, /keeps ID 602/);

  e.node('appAlertOk').click();
  await pending;
  assert.equal(modal.classList.contains('active'), false, 'OK closes it');
  assert.equal(e.node('appAlertOk').listeners.click.length, 0, 'the listener is released');
});

test('closing the alert with the X also dismisses it', async () => {
  const e = setup();
  const pending = e.run('showAppAlert("note")');
  e.node('appAlertClose').click();
  await pending;
  assert.equal(e.node('appAlertModal').classList.contains('active'), false);
});

test('the install result pops the identity notes in that dialog', async () => {
  const source = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
  assert.match(source, /data\.ide_notes/);
  assert.match(source, /showAppAlert\(window\.t\("install\.ideNotesTitle"/);

  const e = setup();
  assert.equal(e.run('window.I18N_DICTIONARY.en["alert.btnOk"]'), 'OK');
  assert.equal(typeof e.run('window.I18N_DICTIONARY.en["install.ideNotesTitle"]'), 'string');
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  assert.match(html, /<div class="modal" id="appAlertModal">/);
  assert.match(html, /id="appAlertOk"/);
});
