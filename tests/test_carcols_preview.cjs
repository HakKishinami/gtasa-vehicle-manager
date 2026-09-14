const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup() {
  const output = {innerHTML: ''};
  const ctx = {
    document: {getElementById: () => output},
    window: {t: (_key, fallback) => fallback},
    carcolsPaletteCache: {1: '#112233', 2: '#223344', 3: '#334455', 4: '#445566'},
  };
  const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
  const start = source.indexOf('function renderLiveCarcolsSwatches(');
  const end = source.indexOf('\nlet currentVanillaHandling', start);
  assert.ok(start >= 0 && end > start);
  vm.runInNewContext(source.slice(start, end), ctx);
  return raw => {
    ctx.renderLiveCarcolsSwatches(raw);
    return output.innerHTML;
  };
}

// Original four-color rows from the user-provided Benefactor Admiral pack.
const CARCOLS_ROWS = {
  "admiral": "admiral, 96,20,0,0, 114,102,0,0, 68,102,0,0, 123,102,0,0, 0,102,0,0, 1,65,0,0, 53,20,0,0, 99,24,0,0",
  "admrl28": "admrl28, 123,102,0,0, 3,102,0,0, 46,102,0,0, 7,20,0,0, 83,65,0,0, 1,20,0,0, 37,107,0,0, 6,102,0,0"
};

for (const model of Object.keys(CARCOLS_ROWS)) {
  test(`${model} readme renders eight four-color schemes with all original IDs`, () => {
    const row = CARCOLS_ROWS[model];
    const html = setup()(`car4 ${row}`);
    assert.equal((html.match(/class="color-pair-badge"/g) || []).length, 8);
    assert.equal((html.match(/class="quad"/g) || []).length, 32);
    assert.ok(!html.includes('class="half"'));
    const ids = row.split(',').slice(1).map(s => Number(s.trim()));
    for (let i = 0; i < 8; i++) {
      assert.ok(html.includes(`<span class="swatch-ids">${ids.slice(i * 4, i * 4 + 4).join(', ')}</span>`));
    }
  });
}

test('four-color preview uses the third and fourth palette colors and quad tooltip', () => {
  const html = setup()('CAR4 euros, 1,2,3,4, 5,6,7,8');
  assert.equal((html.match(/class="color-pair-badge"/g) || []).length, 2);
  for (const hex of ['#112233', '#223344', '#334455', '#445566']) assert.ok(html.includes(hex));
  assert.ok(html.includes('4-Color Scheme #2: Colors 5, 6, 7, 8'));
});

test('two-color preview still renders pairs', () => {
  const html = setup()('admiral, 1,2,3,4');
  assert.equal((html.match(/class="half"/g) || []).length, 4);
  assert.equal((html.match(/class="color-pair-badge"/g) || []).length, 2);
  assert.ok(!html.includes('swatch-quad'));
});

test('editing incomplete groups shows only complete schemes and clears stale output', () => {
  const render = setup();
  let html = render('car4 euros, 1,2,3,4,5,6,7');
  assert.equal((html.match(/class="color-pair-badge"/g) || []).length, 1);
  assert.ok(!html.includes('undefined'));
  assert.equal(render('car4 euros, 1,2,3'), '');
  render('euros, 1,2');
  assert.equal(render(''), '');
});

test('a model name beginning with car4 does not switch to four-color mode', () => {
  const html = setup()('car4custom, 1,2,3,4');
  assert.equal((html.match(/class="half"/g) || []).length, 4);
});
