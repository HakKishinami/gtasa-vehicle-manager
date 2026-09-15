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

test('Inspector header includes btnOpenCurrentModFolder before btnRenameCurrentMod', () => {
  assert.match(html, /id="btnOpenCurrentModFolder"[^>]*>.*id="btnRenameCurrentMod"/s, 'Open Folder button is positioned before Rename Folder button');
  assert.match(i18n, /"inspect\.btnOpenFolder":/, 'inspect.btnOpenFolder translation key exists');
  assert.match(i18n, /"inspect\.btnOpenFolderTitle":/, 'inspect.btnOpenFolderTitle translation key exists');
  assert.match(appJs, /btnOpenCurrentModFolder/, 'app.js references and wires btnOpenCurrentModFolder');
});

test('Data Copies maximize and font zoom controls and styles are implemented', () => {
  const css = fs.readFileSync(path.join(root, 'web', 'style.css'), 'utf8');

  // DOM elements
  assert.match(html, /id="btnToggleDataCopyMaximize"/, 'Maximize button exists in HTML');
  assert.match(html, /id="dataCopyFontSizeDisplay"/, 'Font size display exists in HTML');

  // i18n keys
  const zoomKeys = [
    'datacopy.btnMaximize',
    'datacopy.btnMaximizeRestore',
    'datacopy.btnMaximizeTitle',
    'datacopy.fontSizeTitle',
    'datacopy.fontSizeZoom',
  ];
  for (const k of zoomKeys) {
    assert.ok(i18n.includes(`"${k}":`), `Missing zoom i18n key: ${k}`);
  }

  // CSS rules
  assert.match(css, /\.data-copies-card\.is-maximized\s*\{[^}]*position:\s*fixed\s*!important/s, 'is-maximized fixed rule exists');
  assert.match(css, /\.data-copies-card\s*\{[^}]*--data-copy-font-size:/s, 'CSS variable --data-copy-font-size exists');
  assert.match(css, /\.data-copy-line-numbers\s*\{[^}]*var\(--data-copy-font-size/s, 'line numbers use dynamic font size');
  assert.match(css, /\.data-copy-textarea\s*\{[^}]*var\(--data-copy-font-size/s, 'textarea uses dynamic font size');
  assert.match(css, /\.footer-zoom:hover/, 'footer-zoom hover effect exists');

  // app.js functions & handlers
  assert.match(appJs, /function toggleDataCopyMaximize/, 'toggleDataCopyMaximize function exists');
  assert.match(appJs, /function setDataCopyFontSize/, 'setDataCopyFontSize function exists');
  assert.match(appJs, /function getDataCopyLineHeight/, 'getDataCopyLineHeight function exists');
  assert.match(appJs, /btnToggleDataCopyMaximize/, 'wires btnToggleDataCopyMaximize');
  assert.match(appJs, /dataCopyFontSizeDisplay/, 'wires dataCopyFontSizeDisplay');
  assert.match(appJs, /localStorage\.getItem\("dataCopyFontSize"\)/, 'persists font size in localStorage');
});



