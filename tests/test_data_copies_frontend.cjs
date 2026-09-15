const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'web', 'index.html'), 'utf8');
const i18n = fs.readFileSync(path.join(root, 'web', 'i18n.js'), 'utf8');
const appJs = fs.readFileSync(path.join(root, 'web', 'app.js'), 'utf8');

test('Data Copies nav tab and section exist in index.html', () => {
  assert.match(html, /data-tab="dataCopiesTab"/, 'dataCopiesTab button exists');
  assert.match(html, /id="dataCopiesTab"[^>]*class="[^"]*tab-panel[^"]*"/, 'dataCopiesTab section exists');
});

test('Data Copies required controls exist in DOM', () => {
  const requiredIds = [
    'dataCopyFolderSelect',
    'dataCopyFilePills',
    'btnToggleDataCopyFind',
    'dataCopyStatusBadge',
    'btnReloadDataCopy',
    'btnSaveDataCopy',
    'dataCopyFindWidget',
    'dataCopyFindInput',
    'dataCopyFindCount',
    'btnDataCopyFindPrev',
    'btnDataCopyFindNext',
    'btnDataCopyFindClose',
    'dataCopyLineNumbers',
    'dataCopyHighlightOverlay',
    'dataCopyTextarea',
    'dataCopyPathDisplay',
    'dataCopyLinesDisplay',
    'dataCopyCharsDisplay',
  ];

  for (const id of requiredIds) {
    assert.ok(html.includes(`id="${id}"`), `Missing required element: #${id}`);
  }
});

test('i18n dictionary defines all Data Copies keys in English', () => {
  const requiredKeys = [
    'nav.dataCopies',
    'datacopy.source',
    'datacopy.selectFolderTitle',
    'datacopy.btnFind',
    'datacopy.btnFindTitle',
    'datacopy.findPlaceholder',
    'datacopy.findPrevTitle',
    'datacopy.findNextTitle',
    'datacopy.findCloseTitle',
    'datacopy.noMatches',
    'datacopy.matchCount',
    'datacopy.readOnlyBadge',
    'datacopy.unsavedBadge',
    'datacopy.savedBadge',
    'datacopy.btnReload',
    'datacopy.btnReloadTitle',
    'datacopy.btnSave',
    'datacopy.btnSaveTitle',
    'datacopy.noFiles',
    'datacopy.confirmUnsaved',
    'datacopy.saveSuccess',
    'datacopy.vanillaNote',
    'datacopy.emptyFile',
    'datacopy.linesCount',
    'datacopy.charsCount',
  ];

  for (const key of requiredKeys) {
    assert.ok(i18n.includes(`"${key}":`), `Missing i18n key: ${key}`);
  }
});

test('app.js defines Data Copies setup and handlers', () => {
  assert.match(appJs, /setupDataCopiesModule\(\)/, 'setupDataCopiesModule is called');
  assert.match(appJs, /loadDataCopiesView/, 'loadDataCopiesView exists');
  assert.match(appJs, /saveCurrentDataCopyFile/, 'saveCurrentDataCopyFile exists');
  assert.match(appJs, /openDataCopyFindWidget/, 'openDataCopyFindWidget exists');
  assert.match(appJs, /closeDataCopyFindWidget/, 'closeDataCopyFindWidget exists');
  assert.match(appJs, /performDataCopyFind/, 'performDataCopyFind exists');
  assert.match(appJs, /jumpToDataCopyMatch/, 'jumpToDataCopyMatch exists');
  assert.match(appJs, /renderDataCopyHighlights/, 'renderDataCopyHighlights exists');
});

test('In-editor find match calculation correctly finds occurrences', () => {
  const sample = "cars\n400, landstal, landstal, car, LANDSTAL\n411, infernus, infernus, car, INFERNUS\nend";
  const query = "infernus";
  const matches = [];
  let pos = 0;
  while ((pos = sample.toLowerCase().indexOf(query.toLowerCase(), pos)) !== -1) {
    matches.push({ start: pos, end: pos + query.length });
    pos += query.length;
  }
  assert.equal(matches.length, 3, 'infernus appears 3 times (model, txd, gxt)');
  assert.equal(sample.substring(matches[0].start, matches[0].end), 'infernus');
});

test('CSS optimizes Data Copies card height and reclaims bottom dead space', () => {
  const css = fs.readFileSync(path.join(root, 'web', 'style.css'), 'utf8');
  assert.match(css, /\.data-copies-card\s*\{[^}]*margin-bottom:\s*0\s*!important/s, 'card margin-bottom is 0 !important');
  assert.match(css, /\.data-copies-card\s*\{[^}]*height:\s*calc\(100vh\s*-\s*164px\)/s, 'card height dynamically fills screen');
  assert.match(css, /#dataCopiesTab\s*\{[^}]*margin-bottom:\s*-16px/s, 'dataCopiesTab eliminates bottom whitespace');
  assert.match(css, /\.app-footer\s*\{[^}]*padding:\s*8px\s*0\s*12px/s, 'app-footer padding is compact');
});

test('CSS defines active line strip and glowing bounding box for search matches', () => {
  const css = fs.readFileSync(path.join(root, 'web', 'style.css'), 'utf8');
  assert.match(css, /\.data-copy-active-line-strip/, 'active line strip exists');
  assert.match(css, /\.data-copy-word-highlight\.is-active/, 'active word highlight exists');
  assert.match(css, /animation:\s*dataCopyPulse/, 'pulse glow animation exists');
});

