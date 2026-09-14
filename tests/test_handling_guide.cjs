const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = path.join(__dirname, '..', 'web');

// A real vanilla handling.cfg line: 36 whitespace-separated tokens with the
// engine-inertia field (5.0) between acceleration and the Drive/Engine pair.
const LINE = 'ALPHA 1500.0 3400.0 2.0 0.0 0.1 -0.2 85 0.7 0.8 0.5 5 200.0 23.0 5.0 R P 7.0 0.55 0 30.0 '
  + '1.2 0.12 0.0 0.30 -0.15 0.5 0.4 0.25 0.50 35000 40002800 200000 1 1 0';

const TOKENS = LINE.split(' ');
const offsetOf = index => TOKENS.slice(0, index).reduce((sum, token) => sum + token.length + 1, 0);

class ClassList {
  constructor() { this.values = new Set(); }
  add(...names) { for (const name of names) this.values.add(name); }
  remove(...names) { for (const name of names) this.values.delete(name); }
  toggle(name, force) {
    const on = force === undefined ? !this.contains(name) : Boolean(force);
    if (on) this.add(name); else this.remove(name);
    return on;
  }
  contains(name) { return this.values.has(name); }
}

class Element {
  constructor() {
    this.value = '';
    this.textContent = '';
    this.title = '';
    this.selectionStart = 0;
    this.selectionEnd = 0;
    this.classList = new ClassList();
    this.listeners = {};
    this.spans = [];
    this.style = {};
    this.dataset = {};
    this.children = [];
    this.hidden = false;
    this.focused = false;
  }
  addEventListener(name, fn) { (this.listeners[name] = this.listeners[name] || []).push(fn); }
  fire(name) { for (const fn of this.listeners[name] || []) fn(); }
  focus() { this.focused = true; }
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  querySelectorAll(selector) { return selector === 'span' ? this.spans : []; }
  appendChild(child) { this.children.push(child); return child; }
  getAttribute() { return null; }
  setAttribute() {}
}

function setup() {
  const nodes = new Map();
  const errors = [];
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  // The app binds controls at load time, so every id in the page needs a node.
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) nodes.set(match[1], new Element());
  const chips = [...html.matchAll(/<span data-i18n="inspect\.hguide\d+">([^<]+)<\/span>/g)]
    .map(match => match[1]);
  assert.equal(chips.length, 14, 'the guide keeps its fourteen chips');
  const grid = nodes.get('handlingGuideGrid');
  grid.spans = chips.map(label => {
    const span = new Element();
    span.textContent = label;
    return span;
  });
  nodes.set('inputHandlingRaw', new Element());

  const document = {
    addEventListener() {},
    getElementById: id => nodes.get(id) || null,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => new Element(),
  };
  const ctx = {
    document,
    console: {log() {}, error: (...args) => errors.push(args)},
    setTimeout: () => 0,
    clearTimeout: () => {},
    URLSearchParams, AbortController,
    localStorage: {getItem: () => null, setItem() {}},
    fetch: async () => ({ok: true, json: async () => ({success: true})}),
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  const run = code => vm.runInContext(code, ctx);
  run(fs.readFileSync(path.join(web, 'i18n.js'), 'utf8'));
  run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));
  run('setupParamGuideInteractive();');

  const input = nodes.get('inputHandlingRaw');
  const activeChip = () => grid.spans.find(span => span.classList.contains('active-item')) || null;
  const caretOnToken = index => {
    input.value = LINE;
    input.selectionStart = offsetOf(index) + 1;
    input.fire('keyup');
  };
  return {input, grid, errors, activeChip, caretOnToken, run, node: id => nodes.get(id)};
}

test('the handling guide highlights the chip that owns the caret', async () => {
  const e = setup();
  const cases = [
    [0, '1.Identifier'],
    [2, '3.TurnMass'],
    [5, '5.CenterOfMass'],
    [10, '7.Traction'],
    [11, '8.Gears'],
    [12, '9.MaxSpeed'],
    [13, '10.Accel'],
    [15, '11.Drive[FR4]'],
    [16, '12.Engine[PDE]'],
    [18, '13.Brake'],
    [20, '14.SteerAngle'],
  ];
  for (const [tokenIndex, label] of cases) {
    e.caretOnToken(tokenIndex);
    const active = e.activeChip();
    assert.ok(active, `token ${tokenIndex} must highlight a chip`);
    assert.equal(active.textContent, label, `token ${tokenIndex} belongs to ${label}`);
  }
  assert.deepEqual(e.errors, []);
});

test('fields no chip names clear the highlight instead of lighting the wrong one', async () => {
  const e = setup();
  // 14 is the engine-inertia field no chip names; 21..27 are the suspension
  // block the guide deliberately stops short of.
  for (const tokenIndex of [14, 21, 27]) {
    e.caretOnToken(tokenIndex);
    assert.equal(e.activeChip(), null, `token ${tokenIndex} has no chip`);
  }
});

test('clicking a chip jumps to the field it names', async () => {
  const e = setup();
  e.input.value = LINE;

  const clickChip = label => {
    const span = e.grid.spans.find(item => item.textContent === label);
    assert.ok(span, label + ' chip exists');
    span.fire('click');
  };

  clickChip('9.MaxSpeed');
  assert.equal(e.input.selectionStart, offsetOf(12));
  assert.equal(e.input.selectionEnd, offsetOf(12) + TOKENS[12].length);
  assert.equal(e.activeChip().textContent, '9.MaxSpeed', 'the jump keeps the chip lit');

  // A grouped field selects its first token only: replacing a three-token
  // vector with one number would shift every following field.
  clickChip('5.CenterOfMass');
  assert.equal(e.input.selectionStart, offsetOf(4));
  assert.equal(e.input.selectionEnd, offsetOf(4) + TOKENS[4].length);
  assert.equal(e.activeChip().textContent, '5.CenterOfMass');

  clickChip('13.Brake');
  assert.equal(e.input.selectionStart, offsetOf(17));
  assert.equal(e.activeChip().textContent, '13.Brake');
  assert.deepEqual(e.errors, []);
});

test('bike, boat and plane lines disable the guide instead of guessing', async () => {
  const e = setup();
  // Real lines from data/handling.cfg: the !/%/$ variants use a different,
  // shorter field layout that the fourteen car chips do not describe.
  const variants = [
    '!\tBIKE\t\t0.35\t0.15\t0.34\t0.10\t45.0\t38.0\t0.93\t0.70\t0.5\t\t0.1\t\t35.0\t-40.0\t-0.009\t0.7\t\t0.6',
    '%\tPREDATOR\t0.79\t0.5\t\t0.6\t\t7.0\t\t0.60\t-1.9\t4.0\t\t\t0.8\t\t0.998\t0.998\t\t0.85\t0.98\t0.97\t4.0',
  ];
  for (const line of variants) {
    e.input.value = line;
    e.input.selectionStart = 10;
    e.input.fire('keyup');
    const label = line.trim().split(/\s+/)[0];
    assert.equal(e.activeChip(), null, 'no chip describes ' + label);
    assert.equal(e.grid.spans.filter(span => span.classList.contains('chip-disabled')).length, 14,
      'every chip steps aside for ' + label);
    assert.match(e.grid.spans[8].title, /different physics layout/);

    // Clicking a chip must not move the caret on such a line.
    e.input.selectionStart = 3;
    e.input.selectionEnd = 3;
    e.grid.spans[8].fire('click');
    assert.equal(e.input.selectionStart, 3, label + ' is left alone by chip clicks');
  }
});

test('a car line keeps the guide enabled', async () => {
  const e = setup();
  e.caretOnToken(12);
  assert.equal(e.grid.spans.filter(span => span.classList.contains('chip-disabled')).length, 0);
  assert.match(e.grid.spans[8].title, /Click to jump/);
  assert.equal(e.activeChip().textContent, '9.MaxSpeed');
});

test('a long prefixed line is never parsed as a car line', async () => {
  const e = setup();
  assert.equal(e.run('parseHandlingLine(' + JSON.stringify(LINE) + ')') === null, false,
    'the car line still parses');
  const longPlane = '$\tSEAPLANE ' + Array.from({ length: 25 }, (_, i) => (i % 5 === 0 ? 'F P' : '1.0')).join(' ');
  assert.equal(e.run('parseHandlingLine(' + JSON.stringify(longPlane) + ')'), null,
    'a prefixed line never falls through to the car fields');
});

test('the handling card describes a secondary line instead of car stats', async () => {
  const e = setup();
  // Exactly what core/parser.py returns for a prefixed secondary physics line.
  const bike = {
    valid: true, is_secondary: true, prefix: '!', identifier: 'BIKE',
    raw: '!BIKE 0.35 0.15 0.34 0.1 45.0 38.0 0.93 0.7 0.5 0.1 35.0 -40.0 -0.009 0.7 0.6',
    values: [0.35, 0.15, 0.34, 0.1],
  };
  e.run('renderHandlingPreview(' + JSON.stringify(bike) + ', null, false)');
  const details = e.node('handlingDetails').innerHTML;
  const badge = e.node('handlingDriveBadge').innerHTML;
  assert.ok(!/undefined/.test(details), 'no car field renders as undefined: ' + details);
  assert.ok(!/undefined/.test(badge), 'badge stays meaningful: ' + badge);
  assert.match(badge, /Bike/);
  assert.match(badge, /separate physics/);
  assert.match(details, /different physics layout|own physics layout/);
});

test('a line without a Drive/Engine pair highlights nothing and jumps nowhere', async () => {
  const e = setup();
  const broken = TOKENS.map((token, index) => (index === 15 || index === 16 ? '1' : token));
  e.input.value = broken.join(' ');
  e.input.selectionStart = offsetOf(12) + 1;
  e.input.fire('keyup');
  assert.equal(e.activeChip(), null);

  e.input.selectionStart = 0;
  e.grid.spans[8].fire('click');
  assert.equal(e.input.selectionStart, 0, 'an unusable line is left alone');
  assert.equal(e.activeChip(), null);
});

test('a line with a custom engine type like 4 R highlights drive and engine chips', async () => {
  const e = setup();
  const customTokens = TOKENS.map((token, index) => {
    if (index === 15) return '4';
    if (index === 16) return 'R';
    return token;
  });
  e.input.value = customTokens.join(' ');
  // Position caret inside token 16 ('R', engine type)
  const engineTokenOffset = customTokens.slice(0, 16).join(' ').length + 1;
  e.input.selectionStart = engineTokenOffset;
  e.input.fire('keyup');
  const active = e.activeChip();
  assert.ok(active, 'chip must be lit when caret is inside custom engine type');
  assert.equal(active.textContent, '12.Engine[PDE]');
});


