// Run with: node --test tests/test_language_frontend.cjs (no npm dependencies).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.join(__dirname, '..', 'web');

function setup(cachedLanguage = null) {
  const nodes = new Map(), events = [], requests = [], errors = [];
  class ClassList {
    constructor() { this.set = new Set(); }
    add(...tokens) { tokens.join(' ').split(/\s+/).filter(Boolean).forEach(c => this.set.add(c)); }
    remove(...tokens) { tokens.join(' ').split(/\s+/).filter(Boolean).forEach(c => this.set.delete(c)); }
    contains(token) { return this.set.has(token); }
    toggle(token, force) {
      const on = force === undefined ? !this.set.has(token) : Boolean(force);
      if (on) this.set.add(token); else this.set.delete(token);
      return on;
    }
  }
  class Element {
    // HTML input values are strings, including values assigned as numbers.
    set value(value) { this._value = String(value); }
    get value() { return this._value; }
    constructor() {
      this.value = ''; this.checked = false; this.textContent = '';
      this.dataset = {}; this.style = {}; this.options = []; this.children = [];
      this.attributes = {}; this.radios = [];
      this.classList = new ClassList();
    }
    addEventListener() {}
    getAttribute(key) { return this.attributes[key]; }
    setAttribute(key, val) { this.attributes[key] = val; }
    appendChild(el) { this.children.push(el); this.options.push(el); return el; }
    set innerHTML(value) {
      this.html = value; this.children = []; this.options = []; this.radios = [];
      for (const match of value.matchAll(/<input\b([^>]+)>/g)) {
        const attrs = match[1], el = new Element();
        el.dataset.gkey = attrs.match(/data-gkey="([^"]+)"/)?.[1];
        el.dataset.rel = attrs.match(/data-rel="([^"]+)"/)?.[1];
        el.checked = /\bchecked\b/.test(attrs);
        this.radios.push(el);
      }
    }
    get innerHTML() { return this.html || ''; }
    querySelector() { return null; }
    querySelectorAll(selector = '*') {
      const radios = [];
      const collectRadios = el => {
        for (const radio of el.radios) radios.push(radio);
        for (const child of el.children) collectRadios(child);
      };
      collectRadios(this);
      if (!selector || selector === '*') return radios;
      if (selector.startsWith('.')) {
        const cls = selector.slice(1);
        const matches = [];
        const collectMatches = el => {
          for (const child of el.children) {
            if (child.classList && child.classList.contains(cls)) matches.push(child);
            collectMatches(child);
          }
        };
        collectMatches(this);
        return matches;
      }
      return [];
    }
  }
  const document = {
    title: '', documentElement: {}, activeElement: null,
    addEventListener: (name, fn) => events.push(fn),
    getElementById: id => nodes.get(id) || null,
    querySelector: () => null,
    querySelectorAll: selector => {
      if (selector.includes('#installVariantGroups')) return (nodes.get('installVariantGroups')?.querySelectorAll() || []).filter(r => r.checked);
      // Mirror the real DOM for the selectors i18n's applyDom relies on.
      const attrSelector = selector.match(/^\[(data-i18n[a-z-]*)\]$/);
      if (attrSelector) return [...nodes.values()].filter(el => el.attributes[attrSelector[1]]);
      if (selector === '#densityToggle .density-btn') return (nodes.get('densityToggle')?.querySelectorAll('.density-btn') || []);
      return [];
    },
    createElement: () => new Element(),
  };
  const ctx = {document, console: {log() {}, error: (...args) => errors.push(args)},
    setTimeout, clearTimeout, URLSearchParams, AbortController,
    localStorage: {getItem: () => cachedLanguage, setItem() { throw Error('Startup must not write browser storage'); }},
    fetch: async (url, options) => { requests.push({url, body: options && JSON.parse(options.body)}); return {ok:true, json: async () => ({success:true})}; },
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  const run = code => vm.runInContext(code, ctx);
    run(fs.readFileSync(path.join(web, 'i18n.js'), 'utf8'));
  ctx.I18N.register(
    { id: 'es', name: 'Español', htmlLang: 'es', title: 'GTASA Vehicle Manager' },
    {
      'vanilla.bannerTitle': 'No se pudo cargar la lista de vehículos',
      'vanilla.btnRetry': 'Reintentar',
      'assets.configEditorPlaceholder': 'Editar líneas de configuración aquí...',
      'fla.audioModPreset': 'Preset del mod',
      'carcols.countBadge': '{0} esquemas de color',
      'carcols.typeBadge': '{0}×2-color',
      'inspect.diffModified': 'Modificado',
      'inspect.paramCenterOfMass': 'Desplazamiento del centro de masa [X, Y, Z]',
      'mods.emptyTitle': 'No se encontraron mods de vehículos coincidentes'
    }
  );
  const node = (id, props = {}) => { const el = Object.assign(new Element(), props); nodes.set(id, el); return el; };
  return {ctx, node, events, requests, errors, run};
}

for (const cached of [null, 'es', 'en']) {
  test(`startup uses backend language without a POST (cache=${cached})`, async () => {
    const e = setup(cached);
    e.events[0]();
    assert.equal(e.requests.length, 0);
    e.ctx.I18N.initialize({language:'en', default_language:'en'});
    assert.equal(e.ctx.I18N.current, 'en');
    assert.equal(e.ctx.document.documentElement.lang, 'en');
    assert.equal(e.requests.length, 0);
    await e.ctx.setLanguage('es', false);
    e.ctx.I18N.initialize({language:'en', default_language:'en'});
    assert.equal(e.ctx.I18N.current, 'es', 'status refresh must preserve the session choice');
  });
}

test('a user choice wins over a delayed startup response', async () => {
  const e = setup();
  await e.ctx.setLanguage('en', false);
  e.ctx.I18N.initialize({language:'es', default_language:'es'});
  assert.equal(e.ctx.I18N.current, 'en');
});

test('a callback registered through both APIs is called once; saving default does not redraw', async () => {
  const e = setup(); let calls = 0;
  e.ctx.onLanguageChanged = () => calls++;
  e.ctx.I18N.onChange(e.ctx.onLanguageChanged);
  e.ctx.I18N.onChange(e.ctx.onLanguageChanged);
  await e.ctx.setLanguage('es', false);
  assert.equal(calls, 1);
  await e.ctx.setLanguage('es', true);
  assert.equal(calls, 1);
  assert.deepEqual(e.requests.map(r => r.body.set_default), [false, true]);
});

test('rapid changes reach the server in selection order', async () => {
  const e = setup(); const received = []; let release;
  e.ctx.fetch = async (url, options) => {
    received.push(JSON.parse(options.body).language);
    if (received.length === 1) await new Promise(resolve => {release = resolve;});
    return {ok:true, json: async () => ({success:true})};
  };
  const first = e.ctx.setLanguage('en', false);
  const second = e.ctx.setLanguage('es', false);
  await Promise.resolve();
  assert.deepEqual(received, ['en']);
  release(); await Promise.all([first, second]);
  assert.deepEqual(received, ['en','es']);
  assert.equal(e.ctx.I18N.current, 'es');
});

for (const multi of [false, true]) {
  test(`language switch preserves installer state (${multi ? 'multiple vehicles' : 'single vehicle'})`, async () => {
    const e = setup();
    e.run(fs.readFileSync(path.join(web, 'install-assets.js'), 'utf8'));
    const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
    for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
    e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));
    // Isolate unrelated library/inspector panels; exercise the real installer
    // refresh, asset state, variant renderer and language callback together.
    e.run('updatePartitionFolderBar = () => {}; updateModCountBadges = () => {}; resetInspectorView = () => {}; resetFlaDisplay = () => {};');
    e.node('installStep2', {style:{display:'block'}});
    const ids = ['installVehicleSelect','installCategorySelect','installAuthorFolder','installSubfolderName',
      'installFxtKey','installFxtName','installAddonIdInput','installWizardCarFolder','installWizardCarCategory'];
    const inputs = ids.map((id,i) => e.node(id, {value:`custom-${i}`}));
    const checks = ['chkCopyFiles','chkMergeHandling','chkMergeCarcols','chkMergeCarmods','chkGenShopping','chkGenFxt','chkMergeFla','chkSkipCurrentCar']
      .map((id,i) => e.node(id, {checked:i % 2 === 0}));
    const filesBadge = e.node('installTotalFilesBadge', {textContent:'2 个文件'});
    filesBadge.setAttribute('data-i18n','install.zeroFiles');
    e.node('installChecklistSummary'); e.node('installTuningBadge');
    e.node('installVariantCard'); const variants = e.node('installVariantGroups');
    e.node('installVariantBadge'); e.node('variantQuickRow');
    e.node('installWizardProgressBadge');
    e.run(`currentInspectData = {asset_files:{}, parsed_config:{handling_cfg:['CUSTOM 123']},
      primary_dffs:['a.dff'], primary_txds:['a.txd'],
      variant_groups:[{key:'car.dff',name:'car.dff',kind:'vehicle',options:[{rel:'a/car.dff',dir:'a'},{rel:'b/car.dff',dir:'b'}]}]};
      InstallAssets.setData(currentInspectData, []);
      InstallAssets.setExcludedFiles(new Set(['unwanted.dff']));
      renderVariantPicker(currentInspectData);
      singleAddonId = 18001;
      phaseDest = {replace:{category:'Custom',author:'User',subfolder:'Keep'},addon:{category:'New',author:'User',subfolder:'Keep2'}};
      displayedDestPhase = 'addon';
      wizardVehicles = ${multi ? "[{source_model:'a',target_model:'customa',addon_id:18002,skip:true,folder_name:'per-car'},{source_model:'b',target_model:'customb',addon_id:18003,skip:false,folder_name:'other'}]" : '[]'};
      wizardCurrentIndex = ${multi ? 1 : 0};`);
    const radios = variants.querySelectorAll(); radios[0].checked = false; radios[1].checked = true;
    const before = e.run('JSON.stringify({wizardVehicles,wizardCurrentIndex,phaseDest,displayedDestPhase,singleAddonId,currentInspectData})');
    const fieldValues = inputs.map(el => el.value), checkValues = checks.map(el => el.checked);
    for (const lang of ['en','es','en']) await e.ctx.setLanguage(lang, false);
    assert.equal(e.run('JSON.stringify({wizardVehicles,wizardCurrentIndex,phaseDest,displayedDestPhase,singleAddonId,currentInspectData})'), before);
    assert.deepEqual(inputs.map(el => el.value), fieldValues);
    assert.deepEqual(checks.map(el => el.checked), checkValues);
    assert.deepEqual([...e.ctx.InstallAssets.getExcludedFiles()], ['unwanted.dff']);
    assert.equal(e.run('collectVariantChoices()["car.dff"]'), 'b/car.dff');
    assert.equal(filesBadge.textContent, '2 files');
    assert.deepEqual(e.errors, [], 'language callbacks must finish without swallowed exceptions');
  });
}

test('empty mod list hint follows language switches', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  e.node('installStep2', {style:{display:'none'}});
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));
  e.run('updatePartitionFolderBar = () => {}; updateModCountBadges = () => {}; resetInspectorView = () => {}; resetFlaDisplay = () => {};');
  const grid = e.node('modGrid');

  await e.ctx.setLanguage('es', false);
  e.run('applyFilter()');
  assert.match(grid.innerHTML, /No se encontraron mods/);

  await e.ctx.setLanguage('en', false);
  assert.match(grid.innerHTML, /No matching vehicle mods found/);

  await e.ctx.setLanguage('es', false);
  assert.match(grid.innerHTML, /No se encontraron mods/);
  assert.deepEqual(e.errors, [], 'language callbacks must finish without swallowed exceptions');
});

test('addon-only packages default to the Addon Cars folder', async () => {
  const e = setup();
  e.run(fs.readFileSync(path.join(web, 'install-assets.js'), 'utf8'));
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));
  e.run('updatePartitionFolderBar = () => {}; updateModCountBadges = () => {}; resetInspectorView = () => {}; resetFlaDisplay = () => {};');
  e.node('installStep2', {style:{display:'none'}});
  const catSel = e.node('installCategorySelect');
  const preview = e.node('installPathLivePreview');

  const addonData = {
    target_model: 'stanier',
    target_vehicles: [{
      source_model: 'stanier', model: 'stanier', target_model: 'stanier', name: 'STANIER',
      proposed_addon_id: 12000,
      fxt_proposal: {key: 'STANIER', name: 'STANIER', has_author_fxt: false},
    }],
    proposed_folder_name: '1992 Vapid Stanier',
    detected_author: 'OniK',
    existing_authors: ['OniK'],
    primary_dffs: [], primary_txds: [], tuning_dffs: [], tuning_txds: [],
    readme_files: [], other_files: [],
    parsed_config: {},
    asset_files: {models: [], textures: [], tuning: [], documents: [], other: []},
    tuning_parts_analysis: [],
    variant_groups: [],
    fxt_proposal: {key: 'STANIER', name: 'STANIER'},
    addon_id_proposals: {stanier: 12000},
    addon_name_conflicts: [],
  };
  e.run(`vanillaVehicles = [{id: 400, model: 'landstal', name: 'Landstalker', type: 'car'}];
    appStatus = {data_folder: 'Modded Cars', addon_folder: 'Addon Cars', modloader_folders: ['Modded Cars', 'Addon Cars']};
    currentInspectData = ${JSON.stringify(addonData)};
    renderInstallStep2(currentInspectData);`);

  assert.equal(catSel.value, 'Addon Cars');
  assert.match(preview.innerHTML, /Addon Cars/);

  // Switching the target kind flips between the two default folders...
  e.run("syncDefaultCategoryToTarget('landstal')");
  assert.equal(catSel.value, 'Modded Cars');
  e.run("syncDefaultCategoryToTarget('stanier')");
  assert.equal(catSel.value, 'Addon Cars');
  // ...but a custom category chosen by the user is never overridden.
  catSel.value = 'Custom Cars';
  e.run("syncDefaultCategoryToTarget('landstal')");
  assert.equal(catSel.value, 'Custom Cars');
  assert.deepEqual(e.errors, []);
});

test('an addon package does not offer its own model as a replacement target', async () => {
  const e = setup();
  e.run(fs.readFileSync(path.join(web, 'install-assets.js'), 'utf8'));
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  // Capture the select before anything renders: e.node() rebuilds the element.
  const select = e.node('installVehicleSelect');
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));
  e.run('updatePartitionFolderBar = () => {}; updateModCountBadges = () => {}; resetInspectorView = () => {}; resetFlaDisplay = () => {};');
  e.node('installStep2', {style:{display:'none'}});

  const zr150 = {
    target_model: 'zr150',
    target_vehicles: [{
      source_model: 'zr150', model: 'zr150', target_model: 'zr150', name: 'ZR-150',
      proposed_addon_id: 12093,
      fxt_proposal: {key: 'ZR150', name: 'ZR-150', has_author_fxt: false},
    }],
    proposed_folder_name: '1980 Annis ZR-150',
    detected_author: 'Annis',
    existing_authors: [],
    primary_dffs: [], primary_txds: [], tuning_dffs: [], tuning_txds: [],
    readme_files: [], other_files: [],
    parsed_config: {},
    asset_files: {models: [], textures: [], tuning: [], documents: [], other: []},
    tuning_parts_analysis: [],
    variant_groups: [],
    fxt_proposal: {key: 'ZR150', name: 'ZR-150'},
    addon_id_proposals: {zr150: 12093},
    addon_name_conflicts: [],
  };
  e.run(`vanillaVehicles = [
      {id: 477, model: 'zr350', name: 'ZR-350', type: 'car'},
      {id: 445, model: 'admiral', name: 'Admiral', type: 'car'}];
    appStatus = {data_folder: 'Modded Cars', addon_folder: 'Addon Cars', modloader_folders: ['Modded Cars', 'Addon Cars']};
    currentInspectData = ${JSON.stringify(zr150)};
    renderInstallStep2(currentInspectData);`);

  const optionFor = model => select.options.find(o => o.value === model);
  assert.ok(optionFor('zr150'), 'the package model must stay representable in the select');
  assert.equal(optionFor('zr150').hidden, false, 'an addon package offers its own model while installing as an addon');

  // Converting the package into a replacement, then searching for its model.
  e.run("document.getElementById('installVehicleSelect').value = 'admiral'; setInstallMode('replace');");
  e.run("vehiclePickerSearch = 'zr'; applyVehiclePickerFilter();");
  assert.equal(optionFor('zr150').hidden, true,
    'a replacement install must not offer the package model as a target');
  assert.equal(optionFor('zr350').hidden, false, 'vanilla matches keep showing');

  // Back to addon mode: the package model is a legal target again.
  e.run("setInstallMode('addon'); vehiclePickerSearch = 'zr'; applyVehiclePickerFilter();");
  assert.equal(optionFor('zr150').hidden, false);
  assert.deepEqual(e.errors, []);
});

test('every navigation tab switches to a panel', async () => {
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
  const tabs = [...html.matchAll(/<button class="tab-btn[^"]*"([^>]*)>/g)];
  assert.ok(tabs.length >= 5, 'the five workspace tabs stay in the navigation');
  for (const tab of tabs) {
    const target = tab[1].match(/data-tab="([^"]+)"/);
    assert.ok(target, `a tab button has no data-tab: ${tab[0]}`);
    assert.ok(ids.has(target[1]), `tab target ${target[1]} has no panel`);
  }
});

test('mod cards show a vehicle-type icon tile', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));
  e.run('updatePartitionFolderBar = () => {}; updateModCountBadges = () => {};');
  const grid = e.node('modGrid', {});

  const mods = [
    {name: 'Boat Mod', author: 'A', rel_path: 'Modded Cars\\A\\BoatMod', full_path: 'X:\\BoatMod',
     mod_type: 'replace', is_addon: false, target_model: 'predator', target_models: ['predator'],
     target_vehicles: [{model: 'predator', name: 'Predator', id: 472, type: 'boat', is_addon: false}],
     has_handling: false, has_carcols: false, fla_has_audio: false, total_tuning_parts: 0,
     has_shopping_risk: false, fla_special: null},
    {name: 'Heli Mod', author: 'B', rel_path: 'Modded Cars\\B\\HeliMod', full_path: 'X:\\HeliMod',
     mod_type: 'replace', is_addon: false, target_model: 'hunter', target_models: ['hunter'],
     target_vehicles: [{model: 'hunter', name: 'Hunter', id: 425, type: 'heli', is_addon: false}],
     has_handling: false, has_carcols: false, fla_has_audio: false, total_tuning_parts: 0,
     has_shopping_risk: false, fla_special: null},
    {name: 'No Type Info', author: 'C', rel_path: 'Modded Cars\\C\\Fallback', full_path: 'X:\\Fallback',
     mod_type: 'replace', is_addon: false, target_model: 'landstal', target_models: ['landstal'],
     target_vehicles: [{model: 'landstal', name: 'Landstalker', id: 400, is_addon: false}],
     has_handling: false, has_carcols: false, fla_has_audio: false, total_tuning_parts: 0,
     has_shopping_risk: false, fla_special: null},
  ];
  e.run(`renderModGrid(${JSON.stringify(mods)})`);

  assert.equal(grid.children.length, 3);
  assert.match(grid.children[0].innerHTML, /mod-card-type type-boat/);
  assert.match(grid.children[1].innerHTML, /mod-card-type type-heli/);
  assert.match(grid.children[2].innerHTML, /mod-card-type type-car/);
  assert.deepEqual(e.errors, []);
});

test('card density toggle switches layout and persists', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));

  const grid = e.node('modGrid');
  const btnComfort = e.node('densityBtnComfort');
  btnComfort.setAttribute('data-density', 'comfortable');
  btnComfort.classList.add('density-btn');
  const btnCompact = e.node('densityBtnCompact');
  btnCompact.setAttribute('data-density', 'compact');
  btnCompact.classList.add('density-btn');
  const toggle = e.node('densityToggle');
  toggle.appendChild(btnComfort);
  toggle.appendChild(btnCompact);

  e.run("applyCardDensity('compact')");
  assert.equal(grid.classList.contains('density-compact'), true);
  assert.equal(btnCompact.classList.contains('active'), true);
  assert.equal(btnComfort.classList.contains('active'), false);
  assert.equal(e.requests.length, 0, 'non-persist calls must not POST');

  e.run("applyCardDensity('bogus-value')");
  assert.equal(grid.classList.contains('density-compact'), false);
  assert.equal(btnComfort.classList.contains('active'), true);

  e.run("applyCardDensity('compact', true)");
  const last = e.requests[e.requests.length - 1];
  assert.equal(last.url, '/api/config/card-density');
  assert.deepEqual(last.body, {density: 'compact'});
  assert.deepEqual(e.errors, []);
});

test('handling comparison is grouped and non-semantic deltas are neutral', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));

  const current = {
    valid: true, max_speed_kmh: 180, mass_kg: 1350, acceleration: 18.5, gears: 5,
    drive_type: 'R', engine_type: 'P', brake_decel: 8, brake_bias: 0.6, steering_lock_deg: 30,
    turn_mass: 2800, drag_mult: 2, center_of_mass: [0, 0, 0], traction_mult: 0.7,
    traction_loss: 0.8, traction_bias: 0.5, engine_inertia: 1, submerged_percent: 0,
    suspension_force: 1.5, suspension_damping: 0.1, suspension_lower_limit: -0.2,
    monetary_value: 100000,
  };
  const vanilla = Object.assign({}, current, {
    max_speed_kmh: 160, mass_kg: 1400, acceleration: 18, brake_bias: 0.65, steering_lock_deg: 35,
  });

  const detailsEl = e.node('handlingDetails');
  e.run(`renderHandlingPreview(${JSON.stringify(current)}, ${JSON.stringify(vanilla)}, false)`);
  const out = detailsEl.innerHTML;
  assert.match(out, /diff-group-row/, 'comparison table must render group headers');
  assert.match(out, /diff-tag-up/, 'semantic improvements keep green delta');
  assert.match(out, /diff-tag-neutral/, 'non-semantic changes use the neutral tag');
  current.center_of_mass = [0, 0.15, -0.1];
  vanilla.center_of_mass = [0, 0.3, -0.1];
  for (const [lang, label, status] of [
    ['en', 'Center of Mass Offset [X, Y, Z]', 'Modified'],
    ['es', 'Desplazamiento del centro de masa [X, Y, Z]', 'Modificado'],
    ['en', 'Center of Mass Offset [X, Y, Z]', 'Modified'],
  ]) {
    await e.ctx.setLanguage(lang, false);
    e.run(`renderHandlingPreview(${JSON.stringify(current)}, ${JSON.stringify(vanilla)}, false)`);
    const row = detailsEl.innerHTML.split('<tr').find(r => r.includes(label));
    assert.ok(row, `localized center of mass label: ${lang}`);
    assert.ok(row.includes(`>${status}</span>`), `localized vector status: ${lang}`);
    // checked above
    if (lang === 'en') assert.ok(!/[\u4e00-\u9fff]/.test(row));
    const title = detailsEl.innerHTML.match(/class="diff-summary-title">([^<]+)/)[1];
    assert.ok(!title.includes('⚖'), 'the separate icon must not be repeated in the title');
  }
  assert.deepEqual(e.errors, []);
});

test('carcols preview merges duplicate schemes and tags 2/4-color', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));

  const palettes = e.node('carcolsPalettes');
  const countBadge = e.node('colorCountBadge');
  const typeBadge = e.node('colorTypeBadge');
  await e.ctx.setLanguage('en', false);
  const data = {
    color_pairs: [
      {c1: 14, c2: 33, hex1: '#111111', hex2: '#222222'},
      {c1: 14, c2: 33, hex1: '#111111', hex2: '#222222'},
      {c1: 1, c2: 2, c3: 3, c4: 4, hex1: '#aa0000', hex2: '#bb0000', hex3: '#cc0000', hex4: '#dd0000'},
    ],
  };
  e.run(`renderCarcolsPreview(${JSON.stringify(data)})`);

  assert.equal(countBadge.textContent, '2 Color Schemes');
  assert.match(typeBadge.textContent, /1×2-color/);
  assert.match(typeBadge.textContent, /1×4-color/);
  assert.match(palettes.innerHTML, /swatch-kind/);
  assert.deepEqual(e.errors, []);
});

test('tuning rows show the real shopping price, not the category default', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));

  const tDiv = e.node('tuningDetails');
  const data = {
    parts: [{
      part_name: 'nto_b_l', name_cn: '氮气加速 (Nitro)', name_en: 'Nitro', category: 'nitro',
      model_id: 1008, shopping_price: 777, default_price: 500,
    }],
  };
  e.run(`renderCarmodsPreview(${JSON.stringify(data)}, {files: {tuning_dffs: []}, missing_shopping_parts: []})`);

  assert.match(tDiv.innerHTML, /\$777/);
  assert.deepEqual(e.errors, []);
});

test('deleting an inspected mod discards inspector context and resets inspector view', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  e.ctx.confirm = () => true;
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));

  const nameEl = e.node('inspectModName');
  const modPath = 'D:\\games\\modloader\\Modded Cars\\Infernus';
  const modSummary = { name: 'Infernus Mod', author: 'AuthorA', full_path: modPath, target_model: 'infernus' };

  e.run(`activeMod = ${JSON.stringify(modSummary)};
    currentInspectorSummary = ${JSON.stringify(modSummary)};
    currentInspectorDetail = { mod_dir: ${JSON.stringify(modPath)}, target_model: 'infernus' };
    document.getElementById("inspectModName").textContent = 'Infernus Mod';
  `);

  assert.equal(nameEl.textContent, 'Infernus Mod');

  // Perform delete request with forward-slash path variant
  await e.run(`requestDeleteMod(encodeURIComponent('D:/games/modloader/Modded Cars/Infernus'), encodeURIComponent('Infernus Mod'), 'infernus')`);

  assert.equal(e.run('activeMod'), null, 'activeMod must be cleared after deletion');
  assert.equal(e.run('currentInspectorDetail'), null, 'currentInspectorDetail must be cleared');
  assert.equal(e.run('currentInspectorSummary'), null, 'currentInspectorSummary must be cleared');
  assert.match(nameEl.textContent, /选择一个模组进行深度解析|Select a mod to inspect/, 'inspector name must be reset');
  assert.deepEqual(e.errors, []);
});

test('FLA audio shows the mod preset when the deployed line is vanilla baseline', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));

  const badge = e.node('audioStatusBadge');
  const input = e.node('audioRawInput');
  await e.ctx.setLanguage('en', false);
  const presetLine = 'supergt 0 95 94 0 0.7 1.0 1 0.890899 4 0 1 0 11 0.0';
  const detail = {
    model: 'supergt',
    special: {exists: false},
    audio: {exists: true, is_vanilla: true, is_modified: false,
            raw_line: 'supergt 0 87 86 0 0.85 1.0 3 0.943874 2 0 4 0 45 0.0'},
    mod_preset: {audio_raw: presetLine, special_raw: null},
  };
  e.run(`currentInspectedModel = 'supergt'; renderFlaDetail(${JSON.stringify(detail)})`);

  assert.equal(badge.textContent, 'Mod Preset');
  assert.equal(input.value, presetLine);
  assert.deepEqual(e.errors, []);
});

test('addon name validation fails closed while the vanilla list is unavailable', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));

  e.node('installNewModelName', { value: 'elegy' });
  const errEl = e.node('installNewNameError');
  e.run("singleInstallMode = 'addon'; vanillaVehicles = []; vanillaVehiclesReady = false;");

  // Without the vanilla list every name looks free - refuse instead of passing.
  assert.equal(e.run("validateNewInstallName()"), false);
  assert.match(errEl.textContent, /重新加载|Reload/);

  // Once the list is known, the same colliding name is rejected on its merits.
  e.run("vanillaVehicles = [{id:398,model:'elegy',name:'Elegy',type:'car'}];"
      + " vanillaVehiclesReady = true;");
  assert.equal(e.run("validateNewInstallName()"), false);
  assert.notEqual(errEl.textContent, '');

  e.node('installNewModelName', { value: 'elegy_custom' });
  assert.equal(e.run("validateNewInstallName()"), true);
  assert.equal(errEl.textContent, '');
  assert.deepEqual(e.errors, []);
});

test('the vanilla list banner starts hidden and toggles with a retry control', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));

  // The stub DOM does not parse inline styles, so assert on the markup itself.
  assert.match(html, /id="vanillaListWarningBanner"[^>]*style="display:none;"/);
  assert.match(html, /id="btnRetryVanillaList"/);
  assert.match(html, /data-i18n="vanilla\.bannerTitle"/);

  const banner = e.node('vanillaListWarningBanner', { style: {} });
  e.run("setVanillaListWarning(true)");
  assert.equal(banner.style.display, 'flex');
  e.run("setVanillaListWarning(false)");
  assert.equal(banner.style.display, 'none');
});

const VANILLA_LIST_KEYS = [
  'vanilla.bannerTitle', 'vanilla.bannerDesc', 'vanilla.btnRetry',
  'vanilla.reloadOk', 'vanilla.reloadFailed', 'install.newNameListUnavailable',
];

test('the vanilla list banner text follows the language switch', async () => {
  const e = setup();
  e.ctx.I18N.initialize({ language: 'es', default_language: 'es' });
  const esTitle = e.ctx.t('vanilla.bannerTitle', 'MISSING');
  const esBtn = e.ctx.t('vanilla.btnRetry', 'MISSING');
  assert.notEqual(esTitle, 'MISSING');
  assert.equal(esTitle, 'No se pudo cargar la lista de vehículos');
  assert.equal(esBtn, 'Reintentar');

  await e.ctx.setLanguage('en', false);
  const enTitle = e.ctx.t('vanilla.bannerTitle', 'MISSING');
  const enDesc = e.ctx.t('vanilla.bannerDesc', 'MISSING');
  const enErr = e.ctx.t('install.newNameListUnavailable', 'MISSING');
  assert.notEqual(enTitle, esTitle);
  for (const value of [enTitle, enDesc, enErr]) {
    assert.notEqual(value, 'MISSING');
    assert.ok(!/[\u4e00-\u9fff]/.test(value), 'English banner text must not contain Chinese');
  }
});

for (const key of VANILLA_LIST_KEYS) {
  test(`i18n defines ${key} in English`, async () => {
    const e = setup();
    const value = e.ctx.I18N_DICTIONARY.en[key];
    assert.equal(typeof value, 'string');
    assert.ok(value.length > 0);
    assert.ok(!/[\u4e00-\u9fff]/.test(value), 'English string must not contain Chinese');
  });
}

test('custom addon model/texture name helpers validate and suggest', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));
  // The app always loads the vanilla list before these helpers are reachable;
  // without it every model looks like an addon and 'elegy' would suggest itself.
  e.run("vanillaVehicles = [{id:398,model:'elegy',name:'Elegy',type:'car'}];"
      + " vanillaVehiclesReady = true;");

  assert.equal(e.run("validateCustomModelName('previon2', new Set(['previon']))"), '');
  assert.equal(e.run("validateCustomModelName('', new Set())"), 'empty');
  assert.equal(e.run("validateCustomModelName('bad name', new Set())"), 'charset');
  assert.equal(e.run("validateCustomModelName('previon', new Set(['previon']))"), 'taken');
  assert.equal(e.run("suggestAddonName('elegy')"), 'elegy2');
  assert.equal(e.run("suggestAddonName('a'.repeat(20)).length"), 20);
  assert.equal(e.run("suggestHandlingId('previon2')"), 'PREVION2');
  assert.equal(e.run("suggestHandlingId('a'.repeat(20)).length"), 14);
  assert.equal(e.run("validateCustomHandlingId('PREVION2')"), '');
  assert.equal(e.run("validateCustomHandlingId('bad handling')"), 'charset');
  assert.equal(e.run("validateCustomHandlingId('')"), 'empty');
  assert.deepEqual(e.errors, []);
});

// Static attributes carry Chinese as the in-markup fallback. If such an
// attribute is not wired to an i18n key, the Chinese text survives a switch to
// English - which is exactly how the installer's config editor placeholder
// shipped untranslated.
const LOCALIZED_ATTRIBUTES = [
  ['placeholder', 'data-i18n-placeholder'],
  ['title', 'data-i18n-title'],
  ['aria-label', 'data-i18n-aria-label'],
];

function findUntranslatedAttributes(html, dicts) {
  const problems = [];
  for (const tag of html.match(/<[a-zA-Z][^>]*>/g) || []) {
    for (const [attr, keyAttr] of LOCALIZED_ATTRIBUTES) {
      const value = tag.match(new RegExp(`\\b${attr}="([^"]*)"`));
      if (!value || !/[\u4e00-\u9fff]/.test(value[1])) continue;
      const key = tag.match(new RegExp(`${keyAttr}="([^"]+)"`));
      if (!key) {
        problems.push(`${attr}="${value[1]}" has no ${keyAttr}`);
        continue;
      }
      for (const lang of ['zh', 'en']) {
        const text = dicts[lang][key[1]];
        if (!text) {
          problems.push(`${key[1]} is missing from the ${lang} dictionary`);
        } else if (lang === 'en' && /[\u4e00-\u9fff]/.test(text)) {
          problems.push(`${key[1]} still contains Chinese in the en dictionary`);
        }
      }
    }
  }
  return problems;
}

test('no Chinese UI attribute escapes translation to English', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  assert.deepEqual(findUntranslatedAttributes(html, e.ctx.I18N_DICTIONARY), []);
});

test('the detector catches an unwired Chinese attribute', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  const broken = html + '<input placeholder="未标记中文测试" />';
  const problems = findUntranslatedAttributes(broken, e.ctx.I18N_DICTIONARY);
  assert.equal(problems.length, 1, JSON.stringify(problems));
  assert.match(problems[0], /未标记中文测试/);
});

test('the installer config editor placeholder resolves to English', async () => {
  const e = setup();
  e.ctx.I18N.initialize({ language: 'en', default_language: 'en' });
  const text = e.ctx.t('assets.configEditorPlaceholder', 'MISSING');
  assert.notEqual(text, 'MISSING');
  assert.equal(text, e.ctx.I18N_DICTIONARY.en['assets.configEditorPlaceholder']);
  assert.ok(!/[\u4e00-\u9fff]/.test(text), 'must not contain Chinese');

  await e.ctx.setLanguage('es', false);
  const es = e.ctx.t('assets.configEditorPlaceholder', 'MISSING');
  assert.equal(es, 'Editar líneas de configuración aquí...');
});

test('the aria-label handler applies translations to the dialog controls', async () => {
  const e = setup();
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) e.node(match[1]);
  e.run(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));

  // Mirror the markup: the Chinese value plus the key that must replace it.
  const closeBtn = e.node('assetDialogClose', { attributes: { 'aria-label': '关闭', 'data-i18n-aria-label': 'assets.close' } });
  const search = e.node('assetFileSearch', { attributes: { 'aria-label': '搜索文件名或路径', 'data-i18n-aria-label': 'assets.search' } });
  e.ctx.I18N.initialize({ language: 'en', default_language: 'en' });

  assert.equal(closeBtn.attributes['aria-label'], 'Close');
  assert.equal(search.attributes['aria-label'], 'Search filenames or paths');
  assert.deepEqual(e.errors, []);
});

// ---------------------------------------------------------------------------
// Hardcoded copy: the other half of the problem. A string that is written
// straight into the DOM in one language cannot follow a language switch.
// ---------------------------------------------------------------------------

const LOC_CALL = /\b(?:window\.)?(?:t|loc|pick|text|I18N\.(?:t|pick)|lineCountLabel|configLabel)\s*\(/;
const CJK = /[\u4e00-\u9fff]/;

function sourceLines(file) {
  return fs.readFileSync(path.join(web, file), 'utf8').split('\n');
}

test('no line-count text is hardcoded in the installer asset dialog', async () => {
  const lines = sourceLines('install-assets.js')
    .map((text, i) => ({ text, line: i + 1 }))
    .filter(({ text }) => !text.trim().startsWith('//'));

  // The old form: `${n} ${n === 1 ? "line" : "lines"}` and "N lines (modified)".
  for (const { text, line } of lines) {
    assert.doesNotMatch(text, /===\s*1\s*\?\s*["'`]line["'`]\s*:\s*["'`]lines["'`]/,
      `install-assets.js:${line} hardcodes the singular/plural pair`);
    assert.doesNotMatch(text, /lines?\s*\(modified\)/,
      `install-assets.js:${line} hardcodes the modified suffix`);
  }

  // The labels must come from the dictionary instead.
  const source = lines.map(l => l.text).join('\n');
  assert.match(source, /"assets\.linesCountOne"/);
  assert.match(source, /"assets\.linesCountMany"/);
  assert.match(source, /"assets\.modifiedSuffix"/);
});

test('no English UI literal is hardcoded in app.js render paths', async () => {
  const rawLines = sourceLines('app.js');
  const source = rawLines.join('\n');

  rawLines.forEach((text, i) => {
    const trimmed = text.trim();
    if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) return;

    // A bare "[Addon]" suffix. The translated form references the dictionary
    // key on the same line, so a key-free occurrence is the hardcoded one.
    if (/\[\s*Addon\s*\]/.test(text)) {
      assert.match(text, /install\.optionAddonTag/,
        `app.js:${i + 1} hardcodes the [Addon] suffix instead of translating it`);
    }
    // A Chinese ID label inside an English-only string, e.g. "ID: 待分配".
    assert.doesNotMatch(text, /["'`]\s*ID:\s*[\u4e00-\u9fff]/,
      `app.js:${i + 1} hardcodes a Chinese ID label`);
  });

  assert.match(source, /"install\.optionAddonTag"/);
  assert.match(source, /"veh\."\s*\+/, 'vehicle types must resolve through the veh.* keys');
});

test('Chinese copy in web scripts stays inside an i18n call', async () => {
  // Chinese is the inline fallback language for t(), and the zh branch of
  // loc({zh, en}). A bare Chinese literal leaks into English mode.
  const bare = [];
  for (const file of ['app.js', 'install-assets.js']) {
    const lines = sourceLines(file);
    let locDepth = 0;
    lines.forEach((text, i) => {
      const trimmed = text.trim();
      if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) return;
      if (!CJK.test(text)) return;
      // A line is safe when it opens/continues an i18n call, or is a
      // console.* developer log (never shown to the user).
      const inLoc = locDepth > 0 || LOC_CALL.test(text) || /\bconsole\.\w+\(/.test(text);
      if (!inLoc) bare.push(`${file}:${i + 1}  ${trimmed}`);
      locDepth += (text.match(/\bloc\s*\(/g) || []).length;
      const opens = (text.match(/\(/g) || []).length;
      const closes = (text.match(/\)/g) || []).length;
      locDepth = Math.max(0, locDepth - Math.max(0, closes - opens));
    });
  }
  assert.deepEqual(bare, [], 'bare Chinese literals found');
});

