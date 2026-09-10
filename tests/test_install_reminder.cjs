const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(data, language = 'zh') {
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.events = {}; }
    setAttribute() {}
    append(...nodes) { this.children.push(...nodes); }
    appendChild(node) { this.append(node); }
    addEventListener(name, fn) { this.events[name] = fn; }
    showModal() { this.open = true; }
    close() { this.open = false; this.events.close?.(); }
    remove() { this.removed = true; }
  }
  const document = {body: new Element('body'), createElement: tag => new Element(tag)};
  const requests = [];
  const ctx = {document, I18N: {pick: map => map[language]}, fetch: async (url, options) => {
    requests.push({url, body: JSON.parse(options.body)});
    return {json: async () => data};
  }};
  ctx.window = ctx;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/install-reminder.js'), 'utf8'), ctx);
  return {document, requests, run: ctx.InstallReminder.beforeInstall};
}
const matches = [{path: 'E:\\modloader\\<img onerror=bad> Renamed', models: ['cheetah']}];

test('first install proceeds without a dialog', async () => {
  const s = setup({success: true, matches: []});
  assert.equal((await s.run({target_model: 'cheetah'})).action, 'continue');
  assert.equal(s.document.body.children.length, 0);
  assert.equal(s.requests.length, 1);
  assert.equal(s.requests[0].url, '/api/installer/check-existing');
});

for (const action of ['library', 'continue', 'cancel']) {
  test(`${action} returns the user's choice without mutating requests`, async () => {
    const s = setup({success: true, matches});
    let resolved = false;
    const pending = s.run({vehicles: [{target_model: 'cheetah'}]}).then(r => {resolved = true; return r;});
    await new Promise(setImmediate);
    assert.equal(resolved, false);
    const dialog = s.document.body.children[0];
    assert.equal(dialog.open, true);
    assert.equal(dialog.children[2].children[0].children[1].textContent, matches[0].path);
    dialog.children[3].children.find(b => b.dataset.action === action).events.click();
    assert.equal((await pending).action, action);
    assert.equal(dialog.removed, true);
    assert.equal(s.requests.length, 1);
    assert.equal(s.requests[0].url, '/api/installer/check-existing');
  });
}

test('Escape cancels and English labels follow current language', async () => {
  const s = setup({success: true, matches}, 'en');
  const pending = s.run({target_model: 'cheetah'});
  await new Promise(setImmediate);
  const dialog = s.document.body.children[0];
  assert.equal(dialog.children[0].textContent, 'Existing vehicle mods found');
  let prevented = false;
  dialog.events.cancel({preventDefault() {prevented = true;}});
  assert.equal((await pending).action, 'cancel');
  assert.equal(prevented, true);
});

test('failed check rejects instead of silently continuing', async () => {
  const s = setup({success: false, error: 'denied'});
  await assert.rejects(s.run({target_model: 'cheetah'}), /denied/);
  assert.equal(s.document.body.children.length, 0);
});
