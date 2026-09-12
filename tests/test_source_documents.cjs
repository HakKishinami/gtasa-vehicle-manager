const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup() {
  const nodes = new Map();
  class Element {
    constructor() { this.children = []; this.value = ''; this.textContent = ''; }
    replaceChildren() { this.children = []; }
    appendChild(child) { this.children.push(child); }
    set innerHTML(_) { throw Error('Source text must not be interpreted as HTML'); }
  }
  for (const id of ['sourceDocumentSelect', 'rawReadmeContent', 'sourceDocumentStatus', 'sourceDocumentSize', 'sourceDocumentNotice']) nodes.set(id, new Element());
  const requests = [];
  const ctx = {
    document: {getElementById: id => nodes.get(id), createElement: () => new Element()},
    URLSearchParams, AbortController,
    t: key => key,
    fetch: (url, options) => new Promise(resolve => requests.push({url, options, resolve})),
  };
  ctx.window = ctx;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/source-documents.js'), 'utf8'), ctx);
  const reply = (index, content, extra = {}) => requests[index].resolve({ok: true, json: async () => ({success: true, content, encoding: 'utf-8', ...extra})});
  return {nodes, requests, render: ctx.SourceDocuments.render, reply};
}
const detail = {mod_dir: 'E:/Game/modloader/Mod/Car', source_documents: [
  {path: 'readme.txt.used_source', archived: true, size: 2000},
  {path: 'sub/credits.txt', archived: false, size: 30},
]};

test('documents switch without interpreting author text as HTML', async () => {
  const e = setup();
  const rendering = e.render(detail);
  const text = '<script>alert(1)</script>\n' + 'Credits '.repeat(300);
  e.reply(0, text);
  await rendering;
  assert.equal(e.nodes.get('rawReadmeContent').textContent, text);
  assert.equal(e.nodes.get('sourceDocumentStatus').textContent, 'sources.archived');
  const select = e.nodes.get('sourceDocumentSelect');
  select.value = 'sub/credits.txt';
  const changing = select.onchange();
  e.reply(1, 'Author credits');
  await changing;
  assert.equal(e.nodes.get('rawReadmeContent').textContent, 'Author credits');
  assert.equal(e.nodes.get('sourceDocumentStatus').textContent, 'sources.active');
  assert.match(e.requests[1].url, /document=sub%2Fcredits.txt/);
});

test('a slow response cannot replace a more recently selected document', async () => {
  const e = setup();
  const first = e.render(detail);
  e.nodes.get('sourceDocumentSelect').value = 'sub/credits.txt';
  const second = e.nodes.get('sourceDocumentSelect').onchange();
  e.reply(1, 'Latest selection');
  await second;
  e.reply(0, 'Old selection');
  await first;
  assert.equal(e.nodes.get('rawReadmeContent').textContent, 'Latest selection');
  assert.equal(e.requests[0].options.signal.aborted, true);
});

test('reset clears documents and ignores pending requests from a deleted mod', async () => {
  const e = setup();
  const first = e.render(detail);
  e.render(null);
  e.reply(0, 'Deleted mod text');
  await first;
  assert.equal(e.nodes.get('rawReadmeContent').textContent, 'sources.selectMod');
  assert.equal(e.nodes.get('sourceDocumentSelect').disabled, true);
  assert.equal(e.nodes.get('sourceDocumentSelect').children.length, 0);
});

test('empty document lists and truncated previews are explicit', async () => {
  const e = setup();
  e.render({mod_dir: detail.mod_dir, source_documents: []});
  assert.equal(e.nodes.get('rawReadmeContent').textContent, 'sources.empty');
  const result = e.render(detail);
  e.reply(0, 'Partial text', {truncated: true});
  await result;
  assert.equal(e.nodes.get('sourceDocumentNotice').textContent, 'sources.truncated');
  assert.equal(e.nodes.get('sourceDocumentNotice').hidden, false);
});

test('unavailable files show an error instead of leaving previous text', async () => {
  const e = setup();
  const result = e.render(detail);
  e.requests[0].resolve({ok: false, json: async () => ({success: false})});
  await result;
  assert.equal(e.nodes.get('rawReadmeContent').textContent, 'sources.failed');
});
