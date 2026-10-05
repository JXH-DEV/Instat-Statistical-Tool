'use strict';
/* INSTAT Explorer front end: plain JavaScript, no framework. Everything the server sends is put in with
   textContent (via h()), except the chart SVG, which the server builds with every text value escaped. */

// Language. The server chooses it (the "lang" cookie, else the browser's preference) and sends the sentences for it.
// t() finds a sentence by its English text, so English needs no catalogue at all.
let LANG = 'en', WORDS = new Map();
const N_ = s => s;  // marks a sentence that is translated later, where it is shown (tables of words)
const t = (s, v) => (WORDS.get(s) ?? s).replace(/\{(\w+)\}/g, (m, k) => v && k in v ? v[k] : m);
const tn = (n, one, other, v) => t(n === 1 ? one : other, {n: fmt(n), ...v});

// Helpers
const $ = (sel, root = document) => root.querySelector(sel);
const h = (tag, props, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k.startsWith('aria-')) { if (v != null) e.setAttribute(k, String(v)); continue; }  // "false" is a real ARIA value
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k in e && k !== 'list' && k !== 'form' && k !== 'style') e[k] = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  put(e, kids);
  return e;
};
const flat = a => a.flat(Infinity).filter(x => x != null && x !== false);
const put = (parent, ...kids) => parent.append(...flat(kids));
const setkids = (parent, ...kids) => parent.replaceChildren(...flat(kids));
const fmt = v => v == null ? '' : typeof v === 'number' ? v.toLocaleString(LANG, {maximumFractionDigits: 4}) : String(v);
const debounce = (fn, ms) => { let timer; return (...a) => { clearTimeout(timer); timer = setTimeout(() => fn(...a), ms); }; };
const store = {
  get: k => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch { /* private mode */ } },
};

async function api(path, body, opt = {}) {
  const init = {method: opt.method || (body === undefined && !opt.raw ? 'GET' : 'POST'), headers: {'X-Requested-With': 'instat', ...opt.headers}};
  if (opt.raw) init.body = opt.raw;
  else if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = res.statusText || t('The request failed.');
    try { msg = (await res.json()).error || msg; } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return res;
}
const getJSON = async (path, body, opt) => (await api(path, body, opt)).json();

function toast(msg, kind = 'info', ms = 7000) {
  const e = h('div', {class: 'toast ' + kind, role: kind === 'error' ? 'alert' : null, onclick: () => e.remove()}, msg);
  $('#status').append(e);
  if (kind !== 'error') setTimeout(() => e.remove(), ms);
  return e;
}
const fail = e => toast(e.message || String(e), 'error');
async function busy(msg, job) {
  const e = toast(msg, 'info', 1e9);
  try { return await job(m => { e.textContent = m; }); } finally { e.remove(); }
}
function download(blob, name) {
  const a = h('a', {href: URL.createObjectURL(blob), download: name});
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

// State
const S = {files: [], demos: [], key: null, i: 0, tab: 'insights', listing: null, picked: new Set(), sections: null, filter: '', seq: 0};
const cache = new Map();
const dropCached = key => { for (const k of [...cache.keys()]) if (!key || k.startsWith(key + '/')) cache.delete(k); };
const ROLES = [['title', N_('title')], ['header', N_('header')], ['label', N_('row labels')], ['attr', N_('attributes')],
  ['note', N_('footnote')], ['skip', N_('skipped')]];
const TABS = [['insights', N_('Insights')], ['explore', N_('Explore')], ['data', N_('Clean data')], ['read', N_('How it was read')],
  ['quality', N_('Quality')], ['export', N_('Export')]];
const VIEWS = {lines: N_('Lines over time'), bars: N_('Bars (latest)'), table: N_('Table')};

async function refresh(select) {
  const st = await getJSON('/api/state');
  S.files = st.files;
  S.demos = st.demos;
  if (select && S.files.some(f => f.key === select)) { S.key = select; S.i = 0; }
  if (!S.files.some(f => f.key === S.key)) { S.key = S.files.length ? S.files[S.files.length - 1].key : null; S.i = 0; }
  renderFiles();
  renderResults();
}

// Sidebar
function buildSide() {
  const modes = [['search', t('Search or paste')], ['upload', t('Upload')], ['demo', t('Demo')]];
  const panes = {};
  const bar = h('div', {class: 'modes', role: 'group', 'aria-label': t('Where to get data')});
  const show = m => { for (const [k, p] of Object.entries(panes)) p.hidden = k !== m; for (const b of bar.children) b.setAttribute('aria-pressed', b.dataset.m === m); };
  for (const [k, label] of modes) bar.append(h('button', {type: 'button', 'data-m': k, onclick: () => show(k)}, label));

  panes.search = h('div', {},
    h('label', {class: 'f', for: 'q'}, t('Topic or link')),
    h('input', {id: 'q', type: 'search', placeholder: t('e.g. inflation, unemployment, or paste a link'), autocomplete: 'off', oninput: debounce(e => suggest(e.target.value), 250)}),
    h('div', {id: 'suggest'}));
  const pick = h('input', {type: 'file', multiple: true, accept: '.xlsx,.xls,.csv', id: 'pick', onchange: e => uploadFiles(e.target.files)});
  const drop = h('div', {class: 'drop', ondragover: e => { e.preventDefault(); drop.classList.add('over'); }, ondragleave: () => drop.classList.remove('over'),
    ondrop: e => { e.preventDefault(); drop.classList.remove('over'); uploadFiles(e.dataTransfer.files); }},
    h('p', {}, t('Drop Excel or CSV files here, or')), h('label', {class: 'f', for: 'pick'}, t('choose files')), pick);
  panes.upload = h('div', {}, drop, h('p', {class: 'hint'}, t("Files stay on this computer. .xlsx, .xls (also INSTAT's Excel 2003 XML) and .csv are read.")));
  const demo = h('select', {id: 'demo', 'aria-label': t('Demo file')});
  panes.demo = h('div', {}, h('p', {class: 'hint'}, t('Invented numbers in the layout of an INSTAT table, not real INSTAT figures. A safe way to see what the program does.')), demo,
    h('p', {}, h('button', {type: 'button', onclick: () => loadDemo(demo.value)}, t('Open this demo'))));
  put($('#side'), h('section', {class: 'box'}, h('h2', {}, t('1 · Get data')), bar, Object.values(panes)),
    h('section', {class: 'box', id: 'open'}), h('p', {class: 'muted'}, t('Nothing is downloaded until you choose a file. The analysis follows fixed rules and runs on your computer.')));
  show('search');
  suggest('');
}

let suggestSeq = 0;
async function suggest(q) {
  const box = $('#suggest'), n = ++suggestSeq;
  if (!q.trim()) return setkids(box, h('p', {class: 'hint'}, t('Try a topic in English or Albanian: prices, papunësia, GDP, tourism, population, wages … or paste a link to an INSTAT page or file.')));
  let r;
  try { r = await getJSON('/api/resolve', {q}); } catch (e) { return fail(e); }
  if (n !== suggestSeq) return;
  const list = (items, name) => h('ul', {class: 'topics'}, items.map((x, k) => h('li', {},
    h('label', {}, h('input', {type: 'radio', name, value: x.url, checked: k === 0}), ' ', x.name + (x.theme ? ` (${x.theme})` : '')))));
  const go = (label, fn) => h('button', {type: 'button', class: 'primary', onclick: fn}, label);
  const chosen = name => ($(`input[name=${name}]:checked`) || {}).value;
  if (r.kind === 'topics') setkids(box, r.hits.length ? [list(r.hits, 'topic'), go(t('Show files for this topic'), () => openListing(chosen('topic')))] : h('p', {class: 'hint'}, r.message));
  else if (r.kind === 'theme') setkids(box, list(r.topics, 'theme'), go(t('Show files for this topic'), () => openListing(chosen('theme'))));
  else if (r.kind === 'topic' || r.kind === 'page') setkids(box, go(t('Show the files on this page'), () => openListing(r.url)));
  else if (r.kind === 'file') {
    const trust = h('input', {type: 'checkbox', id: 'trust'});
    setkids(box, h('p', {}, t('File:'), ' ', h('code', {}, r.url.split('/').pop())),
      r.external ? h('p', {class: 'warn-box'}, t('This file is not on instat.gov.al.'), ' ', h('label', {}, trust, ' ' + t('I trust the source'))) : null,
      go(t('Download and analyse this file'), () => loadFiles([{url: r.url, label: null}], r.external && trust.checked)));
  } else setkids(box, h('p', {class: 'hint'}, r.message || ''));
}

async function uploadFiles(list) {
  let last = null;
  for (const f of list) {
    try {
      const d = await busy(t('Reading {name} …', {name: f.name}), () => getJSON('/api/upload', undefined, {raw: f, headers: {'X-Filename': encodeURIComponent(f.name), 'Content-Type': 'application/octet-stream'}}));
      last = d.key;
    } catch (e) { fail(new Error(`${f.name}: ${e.message}`)); }
  }
  $('#pick').value = '';
  if (last) refresh(last);
}

async function loadDemo(name) {
  try { refresh((await busy(t('Building the demo …'), () => getJSON('/api/demo', {name}))).key); } catch (e) { fail(e); }
}

async function loadFiles(links, external) {
  let last = null;
  await busy(t('Starting …'), async say => {
    for (const [i, l] of links.entries()) {
      say(t('Downloading and analysing {name} ({i}/{n}) …', {name: l.filename || l.label || t('file'), i: i + 1, n: links.length}));
      try { last = (await getJSON('/api/load', {url: l.url, label: l.label, external})).key; } catch (e) { fail(new Error(`${l.label || l.filename || l.url}: ${e.message}`)); }
    }
  });
  if (last) refresh(last);
}

function renderFiles() {
  const box = $('#open');
  box.hidden = !S.files.length;
  setkids(box, h('h2', {}, t('2 · Your files')), h('ul', {class: 'files'}, S.files.map(f => h('li', {},
    h('button', {type: 'button', class: 'name', title: f.label, 'aria-current': f.key === S.key, onclick: () => { S.key = f.key; S.i = 0; renderFiles(); renderResults(); }}, f.label),
    h('button', {type: 'button', class: 'ghost', title: t('Close this file'), 'aria-label': t('Close {name}', {name: f.label}), onclick: () => closeFile(f.key)}, '✕')))),
    S.files.length > 1 ? h('button', {type: 'button', class: 'link', onclick: () => closeFile(null)}, t('Close all')) : null);
  const demo = $('#demo');
  if (demo && !demo.children.length) demo.append(...S.demos.map(([k, label]) => h('option', {value: k}, label)));
}

async function closeFile(key) {
  try { await getJSON('/api/close', {key}); } catch (e) { return fail(e); }
  dropCached(key);
  refresh();
}

// The INSTAT page's file list
async function openListing(url) {
  if (!url) return;
  S.listing = {url, loading: true};
  renderPicker();
  try {
    const L = await getJSON('/api/listing', {url});
    const names = [...new Set(L.files.map(f => f.section))];
    S.listing = L;
    S.sections = new Set(names.includes('Figures') ? ['Figures'] : names);
    S.picked.clear();
    S.filter = '';
  } catch (e) { S.listing = null; fail(e); }
  renderPicker();
}

function renderPicker() {
  const box = $('#picker'), L = S.listing;
  setkids(box);
  if (!L) return;
  const card = h('section', {class: 'card'}, h('div', {class: 'row'}, h('h2', {class: 'grow'}, t('Files on this INSTAT page')),
    h('button', {type: 'button', class: 'ghost', 'aria-label': t('Close the file list'), onclick: () => { S.listing = null; renderPicker(); }}, '✕')));
  put(box, card);
  if (L.loading) return put(card, h('p', {class: 'hint'}, t('Opening the page …')));
  put(card, h('p', {class: 'hint'}, h('a', {href: L.url, target: '_blank', rel: 'noopener noreferrer'}, L.title),
    `: ${tn(L.files.length, '{n} Excel or CSV file', '{n} Excel or CSV files')}, ${tn(L.pdfs, '{n} PDF link ignored', '{n} PDF links ignored')}. ${t('Nothing has been downloaded yet.')}`));
  if (!L.files.length) return put(card, h('p', {}, t('This page offers no Excel files. Try another topic.')));
  const names = [...new Set(L.files.map(f => f.section))];
  const rows = h('tbody'), btn = h('button', {type: 'button', class: 'primary', id: 'fetch-picked'});
  const sure = h('input', {type: 'checkbox', id: 'sure'}), sureRow = h('label', {hidden: true}, sure, ' ' + t('I understand that this downloads these files from instat.gov.al'));
  const visible = () => L.files.filter(f => S.sections.has(f.section) && f.label.toLowerCase().includes(S.filter.toLowerCase()));
  const paint = () => {
    rows.replaceChildren(...visible().map(f => h('tr', {}, h('td', {}, h('input', {type: 'checkbox', checked: S.picked.has(f.url), 'aria-label': t('Select {name}', {name: f.label}),
      onchange: e => { e.target.checked ? S.picked.add(f.url) : S.picked.delete(f.url); sync(); }})),
      h('td', {class: 't'}, f.label), h('td', {class: 't'}, f.ext.slice(1).toUpperCase()), h('td', {class: 't'}, f.section))));
    sync();
  };
  const sync = () => {
    const n = S.picked.size;
    sureRow.hidden = n <= 3;
    btn.textContent = tn(n, 'Download and analyse {n} selected file', 'Download and analyse {n} selected files');
    btn.disabled = !n || (n > 3 && !sure.checked);
  };
  sure.onchange = sync;
  btn.onclick = () => loadFiles(L.files.filter(f => S.picked.has(f.url)), false);
  put(card, h('div', {class: 'row'},
    names.map(n => h('label', {}, h('input', {type: 'checkbox', checked: S.sections.has(n), onchange: e => { e.target.checked ? S.sections.add(n) : S.sections.delete(n); paint(); }}), ' ' + n)),
    h('input', {type: 'search', 'aria-label': t('Filter by words in the title'), placeholder: t('Filter by words in the title'), value: S.filter,
      oninput: debounce(e => { S.filter = e.target.value; paint(); }, 200)})),
    h('div', {class: 'scroll'}, h('table', {class: 'data'}, h('thead', {}, h('tr', {}, h('th', {}, t('Select')), h('th', {}, t('Title')), h('th', {}, t('Type')), h('th', {}, t('Section')))), rows)),
    h('p', {}, sureRow), h('p', {}, btn));
  paint();
}

// Results
function moveTab(e) {
  const at = TABS.findIndex(x => x[0] === S.tab), to = at + (e.key === 'ArrowRight') - (e.key === 'ArrowLeft');
  if (to !== at && TABS[to]) { S.tab = TABS[to][0]; renderResults(); $('#tab-' + S.tab).focus(); }
}

function renderResults() {
  const box = $('#results'), f = S.files.find(x => x.key === S.key);
  document.title = f ? `${f.label} · INSTAT Explorer` : 'INSTAT Explorer';
  if (!f) return setkids(box, h('section', {class: 'card welcome'}, h('h2', {}, t("Find, clean and understand INSTAT's Excel tables")),
    h('ol', {}, h('li', {}, t('Search a topic (English or Albanian), paste a link, or upload a file you already downloaded. Use the panel on the left.')),
      h('li', {}, t('Choose the Excel files you want. Only the files you pick are downloaded.')),
      h('li', {}, t('Get clean data, findings in plain language, charts and data-quality checks, and export them as a report, CSV, Excel or SQLite.'))),
    h('p', {class: 'hint'}, t('No file at hand? Open the Demo tab on the left. Everything is worked out on this computer; the program contacts instat.gov.al only when you ask it to.'))));
  if (!f.ok) return setkids(box, f.errors.map(e => h('p', {class: 'warn-box'}, e)));
  S.i = Math.min(S.i, f.tables.length - 1);
  const pickTable = f.tables.length > 1 ? h('p', {}, h('label', {class: 'f', for: 'tbl'}, t('Table in this file')),
    h('select', {id: 'tbl', onchange: e => { S.i = +e.target.value; renderResults(); }}, f.tables.map(x => h('option', {value: x.i, selected: x.i === S.i}, `${x.title} · ${x.sheet}`)))) : null;
  const body = h('div', {id: 'tabbody', role: 'tabpanel', tabindex: 0});
  const tabs = h('div', {class: 'tabs', role: 'tablist'}, TABS.map(([id, label]) => h('button', {type: 'button', role: 'tab', id: 'tab-' + id, 'aria-selected': id === S.tab,
    tabindex: id === S.tab ? 0 : -1, onclick: () => { S.tab = id; renderResults(); },
    onkeydown: moveTab}, t(label))));
  const head = h('div', {id: 'head'});
  setkids(box, f.errors.length ? f.errors.map(e => h('p', {class: 'warn-box'}, e)) : null, pickTable, head, tabs, body);
  loadTab(f, head, body);
}

async function cached(url, body) {
  const k = `${S.key}/${S.i}/${url}`;
  if (!cache.has(k)) cache.set(k, await getJSON(url, body));
  return cache.get(k);
}

async function loadTab(f, head, body) {
  const n = ++S.seq, q = `key=${S.key}&i=${S.i}`;
  body.setAttribute('aria-busy', 'true');
  try {
    const s = await cached(`/api/table?${q}`);
    if (n !== S.seq) return;
    const c = s.confidence, src = s.source;
    setkids(head, h('h2', {class: 'title'}, s.title), h('p', {class: 'hint'}, s.subtitle),
      src.demo ? h('p', {class: 'warn-box'}, t('Demo data. The numbers are invented and only imitate the layout of INSTAT tables. They are not real INSTAT figures.')) : null,
      h('div', {class: 'chips'}, h('span', {class: 'chip'}, t('Source:'), ' ', src.url ? h('a', {href: src.url, target: '_blank', rel: 'noopener noreferrer'}, src.filename) : src.filename),
        h('span', {class: 'chip'}, t('retrieved {date}', {date: src.retrieved})), src.last_modified ? h('span', {class: 'chip'}, t('last modified {date}', {date: src.last_modified})) : null,
        src.published ? h('span', {class: 'chip'}, t('published {date}', {date: src.published})) : null,
        h('span', {class: 'badge ' + (c >= 0.85 ? 'good' : c >= 0.6 ? 'warn' : 'bad')}, t('Layout detection {pct}%', {pct: Math.round(c * 100)}))));
    body.setAttribute('aria-labelledby', 'tab-' + S.tab);
    const view = {insights: () => tabInsights(body, s), explore: () => tabExplore(body, q), data: () => tabData(body, q), read: () => tabRead(body, q, f),
      quality: () => tabQuality(body, q), export: () => tabExport(body, q, s)}[S.tab];
    setkids(body);
    await view();
  } catch (e) { fail(e); } finally { body.removeAttribute('aria-busy'); }
}

// Insights tab
function tabInsights(box, s) {
  put(box, h('p', {}, s.what),
    s.tiles.length ? h('div', {class: 'tiles'}, s.tiles.map(x => h('div', {class: 'tile'}, h('div', {class: 'l'}, x.label), h('div', {class: 'v'}, x.value), h('div', {class: 'd'}, x.delta)))) : null,
    s.sections.map(([name, bullets]) => h('section', {}, h('h3', {}, name), h('ul', {class: 'find'}, bullets.map(b => h('li', {}, b))))),
    s.evidence.length ? h('details', {}, h('summary', {}, t('Evidence behind each finding')),
      s.evidence.map(e => h('div', {}, h('p', {}, h('b', {}, e.kind), ': ' + e.text), h('pre', {class: 'muted'}, JSON.stringify(e.data))))) : null,
    s.charts.length ? h('h3', {}, t('Charts')) : null,
    s.charts.map(c => { const d = h('div', {class: 'chartbox'}); d.innerHTML = c.svg; return h('div', {}, h('h4', {}, c.title), h('p', {class: 'cap'}, c.caption), d); }),
    s.warnings.map(w => h('p', {class: 'warn-box'}, w)));
}

// Explore tab
async function tabExplore(box, q) {
  const E = {};
  const controls = h('div', {class: 'controls'}), out = h('div');
  put(box, controls, out);
  const run = async () => {
    const focus = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.ctl : null;
    let d;
    try { d = await getJSON('/api/explore?' + q, E); } catch (e) { return fail(e); }
    E.measure = d.measure; E.lo = d.lo; E.hi = d.hi; E.kind = d.kind; E.filters = Object.fromEntries(d.dims.map(x => [x.name, x.selected]));
    const again = debounce(() => {
      E.filters = Object.fromEntries(d.dims.map(x => [x.name, [...$(`[data-ctl="dim:${x.name}"]`).selectedOptions].map(o => o.value)]));
      run();
    }, 350);
    // options are [value, text] pairs: the value is what the server knows, the text is what is shown
    const sel = (ctl, opts, cur, onchange, label) => h('div', {}, h('label', {class: 'f'}, label),
      h('select', {'data-ctl': ctl, onchange: e => onchange(e.target.value)}, opts.map(([v, text]) => h('option', {value: v, selected: v === cur}, text))));
    setkids(controls,
      d.measures.length > 1 ? sel('measure', d.measures, d.measure, v => { E.measure = v; E.filters = undefined; run(); }, t('Measure')) : null,
      d.dims.map(x => h('div', {}, h('label', {class: 'f'}, x.label), h('select', {multiple: true, size: Math.min(7, x.options.length), 'data-ctl': 'dim:' + x.name, onchange: again},
        x.options.map(([v, text]) => h('option', {value: v, selected: x.selected.includes(v)}, text || t('(all)')))))),
      d.periods.length > 1 ? [sel('lo', d.periods, d.lo, v => { E.lo = v; run(); }, t('From')), sel('hi', d.periods, d.hi, v => { E.hi = v; run(); }, t('To'))] : null,
      h('div', {}, h('label', {class: 'f'}, t('Show as')), h('div', {class: 'seg'}, d.kinds.map(k => h('label', {},
        h('input', {type: 'radio', name: 'kind', checked: k === d.kind, 'data-ctl': 'kind:' + k, onchange: () => { E.kind = k; run(); }}),
        h('span', {}, t(VIEWS[k])))))));
    const chart = h('div', {class: 'chartbox'});
    chart.innerHTML = d.svg;
    setkids(out, d.svg ? chart : null, d.caption ? h('p', {class: 'cap'}, d.caption) : null,
      d.rows.length ? h('details', {open: d.kind === 'table'}, h('summary', {}, tn(d.total, 'Data behind this view ({n} row)', 'Data behind this view ({n} rows)')), table(d.columns, d.rows),
        h('p', {}, h('button', {type: 'button', onclick: async () => download(await (await api('/api/explore?' + q, {...E, csv: true})).blob(), 'view.csv')}, t('Download this view (CSV)')))) : null);
    if (focus) { const el = $(`[data-ctl="${focus}"]`); if (el) el.focus(); }
  };
  await run();
}

function table(cols, rows, onSort, sorted) {
  return h('div', {class: 'scroll'}, h('table', {class: 'data'},
    h('thead', {}, h('tr', {}, cols.map(c => h('th', {title: onSort ? t('Sort by {column}', {column: c}) : null, onclick: onSort ? () => onSort(c) : null},
      c + (sorted && sorted.col === c ? (sorted.desc ? ' ▼' : ' ▲') : ''))))),
    h('tbody', {}, rows.map(r => h('tr', {}, r.map(v => h('td', {class: typeof v === 'number' ? '' : 't'}, fmt(v))))))));
}

// Clean data tab
async function tabData(box, q) {
  const D = {layout: 'long', q: '', sort: '', desc: false, page: 0};
  const out = h('div');
  const load = async () => {
    const d = await getJSON(`/api/data?${q}&${new URLSearchParams({layout: D.layout, q: D.q, sort: D.sort, desc: D.desc ? 1 : '', page: D.page})}`);
    const pages = Math.max(1, Math.ceil(d.total / d.size));
    setkids(out, h('p', {class: 'hint'}, tn(d.total, '{n} row', '{n} rows')),
      table(d.columns, d.rows, c => { D.desc = D.sort === c && !D.desc; D.sort = c; D.page = 0; load(); }, {col: D.sort, desc: D.desc}),
      h('div', {class: 'pager'}, h('button', {type: 'button', disabled: D.page === 0, onclick: () => { D.page--; load(); }}, t('‹ Previous')),
        t('Page {page} of {pages}', {page: fmt(D.page + 1), pages: fmt(pages)}),
        h('button', {type: 'button', disabled: D.page + 1 >= pages, onclick: () => { D.page++; load(); }}, t('Next ›'))));
  };
  put(box, h('div', {class: 'row'}, h('div', {class: 'seg'}, [['long', t('Long (one row per observation)')], ['wide', t('Wide (one column per period)')]].map(([v, text]) =>
      h('label', {}, h('input', {type: 'radio', name: 'layout', checked: v === 'long', onchange: () => { D.layout = v; D.page = 0; D.sort = ''; load(); }}), h('span', {}, text)))),
    h('input', {type: 'search', placeholder: t('Filter rows (any text)'), 'aria-label': t('Filter rows'), oninput: debounce(e => { D.q = e.target.value; D.page = 0; load(); }, 300)}),
    h('a', {href: `/export?${q}&kind=tidy`}, t('CSV (one row per observation)')), h('a', {href: `/export?${q}&kind=wide`}, t('CSV (one column per period)'))), out);
  await load();
}

// How it was read tab
async function tabRead(box, q, f, part = 0) {
  const d = await getJSON(`/api/read?${q}&part=${part}`);
  setkids(box, h('p', {}, t('This is how the program understood the sheet. If something looks wrong, the colours show which rows and columns were taken as titles, headers, labels and values.')),
    d.parts.length > 1 ? h('p', {}, h('label', {class: 'f', for: 'part'}, t('This table combines {n} repeated tables. Show how this one was read:', {n: fmt(d.parts.length)})),
      h('select', {id: 'part', onchange: e => { setkids(box); tabRead(box, q, f, +e.target.value); }}, d.parts.map((p, k) => h('option', {value: k, selected: k === d.part}, p)))) : null,
    h('table', {class: 'kv'}, h('tbody', {}, d.rows.map(([k, v]) => h('tr', {}, h('th', {}, k), h('td', {}, v))))),
    d.grid ? [h('h3', {}, t('The original sheet, coloured by role')),
      h('div', {class: 'legend'}, ROLES.map(([c, text]) => h('span', {class: 'gv'}, h('span', {class: 'r-' + c}, t(text))))),
      h('div', {class: 'scroll'}, h('table', {class: 'gv'}, h('thead', {}, h('tr', {}, h('th'), d.grid.cols.map(c => h('th', {}, c)))),
        h('tbody', {}, d.grid.rows.map(r => h('tr', {}, h('th', {}, r.n), r.cells.map(([text, role]) => h('td', {class: role ? 'r-' + role : null, title: text}, text)))))))] : null,
    d.notes.length ? [h('h3', {}, t('Footnotes in the file')), h('ul', {class: 'find'}, d.notes.map(n => h('li', {}, n)))] : null,
    overridePanel(d.override, q, part),
    d.skipped.length ? h('details', {}, h('summary', {}, t('Sheets that were skipped')), h('ul', {class: 'find'}, d.skipped.map(([n, w]) => h('li', {}, h('b', {}, n), ': ' + w)))) : null);
}

function overridePanel(o, q, part) {
  const num = (id, label, v, min) => h('div', {}, h('label', {class: 'f', for: id}, label), h('input', {id, type: 'number', min, value: v}));
  const read = () => ({part, header_first: +$('#o-hf').value, header_last: +$('#o-hl').value, data_first: +$('#o-d1').value,
    data_last: +$('#o-d2').value, n_labels: +$('#o-nl').value, layout: $('#o-lay').value});
  const send = async body => {
    try {
      const st = await getJSON('/api/reread?' + q, body);
      S.files = st.files;
      dropCached(S.key);
      renderFiles();
      renderResults();
    } catch (e) { fail(e); }
  };
  return h('details', {open: o.active}, h('summary', {}, t('Something wrong? Correct how this table is read')),
    h('p', {class: 'hint'}, t('Row numbers are the ones you see in Excel. The table is read again at once; your file is not changed.')),
    h('div', {class: 'controls'},
      num('o-hf', t('Header: first row (0 = none)'), o.header_first, 0), num('o-hl', t('Header: last row'), o.header_last, 0),
      num('o-d1', t('Data: first row'), o.data_first, 1), num('o-d2', t('Data: last row'), o.data_last, 1),
      num('o-nl', t('Number of label columns'), o.n_labels, 0),
      h('div', {}, h('label', {class: 'f', for: 'o-lay'}, t('Layout')), h('select', {id: 'o-lay'}, Object.entries(o.layouts).map(([k, text]) => h('option', {value: k, selected: k === o.layout}, text))))),
    h('div', {class: 'row'}, h('button', {type: 'button', class: 'primary', onclick: () => send(read())}, t('Read again with these settings')),
      o.active ? h('button', {type: 'button', onclick: () => send({part, reset: true})}, t('Back to automatic detection')) : null));
}

// Quality tab
async function tabQuality(box, q) {
  const d = await getJSON('/api/quality?' + q);
  const icon = {pass: '✔', warn: '⚠', fail: '✖', info: 'ℹ'};
  put(box, h('p', {class: 'hint'}, t('Automatic checks of the table. They also catch mistakes in how the sheet was read: if parts no longer add up to a stated total, something is off.')),
    h('ul', {class: 'checks'}, d.checks.map(c => h('li', {class: c.status}, h('span', {class: 'ic', 'aria-hidden': 'true'}, icon[c.status]),
      h('span', {}, h('b', {}, c.name), ': ', h('em', {}, c.word), h('br'), c.detail, c.examples.length ? h('div', {class: 'muted'}, t('Examples: {list}', {list: c.examples.join('; ')})) : null)))));
  if (d.missing_svg) {
    const m = h('div', {class: 'chartbox'});
    m.innerHTML = d.missing_svg;
    put(box, h('h3', {}, t('Where values are missing')), m, h('p', {class: 'cap'}, t('Coloured cells are missing values (the file shows `..`, `-`, or nothing).')));
  }
}

// Export tab
function tabExport(box, q) {
  const link = (kind, text) => h('a', {href: `/export?${q}&kind=${kind}`}, text);
  put(box, h('p', {class: 'hint'}, t("Every export carries the source and the retrieval date. INSTAT's files say that they may be reproduced if the source is acknowledged.")),
    h('div', {class: 'exports'},
      h('div', {class: 'card'}, h('h3', {}, t('Report')), link('report', t('HTML report (one file, works offline)'))),
      h('div', {class: 'card'}, h('h3', {}, t('Clean data')), link('tidy', t('CSV (one row per observation)')), link('wide', t('CSV (one column per period)'))),
      h('div', {class: 'card'}, h('h3', {}, t('Workbooks and databases')), link('xlsx', t('Excel workbook')), link('sqlite', t('SQLite database'))),
      h('div', {class: 'card'}, h('h3', {}, t('Everything')), link('zip', t('All of the above in one ZIP')))),
    h('details', {}, h('summary', {}, t('Report a problem with how a file was read')),
      h('p', {class: 'hint'}, t('This file describes how the sheet was read and holds its first 80 rows, so that a developer can reproduce the problem. Do not send it if the file is confidential.')),
      link('diagnostic', t('Download the diagnostic file (JSON)'))));
}

// About, language, theme, start
async function about() {
  const d = $('#about');
  let info = {};
  try { info = await getJSON('/api/about'); } catch (e) { return fail(e); }
  const stop = async () => {
    try { await getJSON('/api/quit', {}); setkids(d, h('p', {}, t('The program has stopped. You can close this tab.'))); } catch (e) { fail(e); }
  };
  setkids(d, h('h2', {}, 'INSTAT Explorer ' + info.version),
    h('p', {}, t("A free tool that reads INSTAT's Excel tables, cleans them and explains what they say. It follows fixed rules, runs on this computer, and needs no account and does no tracking.")),
    h('p', {class: 'warn-box'}, t('An independent project, not affiliated with or endorsed by INSTAT. The data belong to the Institute of Statistics of Albania (INSTAT); reproduce them with the source acknowledged. The findings are written automatically, so check important figures against the original publication.')),
    h('p', {class: 'muted'}, `Python ${info.python} · ${info.platform}`, h('br'), t('Downloaded files and exports are kept in: {folder}', {folder: info.data_dir})),
    h('div', {class: 'row'}, h('button', {type: 'button', class: 'primary', onclick: () => d.close()}, t('Close')),
      h('button', {type: 'button', onclick: stop}, t('Stop the program'))));
  d.showModal();
}

function switchLanguage() {
  try { sessionStorage.setItem('view', JSON.stringify({key: S.key, i: S.i, tab: S.tab})); } catch { /* private mode */ }
  document.cookie = `lang=${LANG === 'sq' ? 'en' : 'sq'}; Path=/; Max-Age=31536000; SameSite=Strict`;
  location.reload();
}
function savedView() {  // what was on screen before the language was switched
  try {
    const v = JSON.parse(sessionStorage.getItem('view'));
    sessionStorage.removeItem('view');
    return v && TABS.some(x => x[0] === v.tab) ? v : null;
  } catch { return null; }
}

function theme() {
  const order = ['', 'light', 'dark'], cur = store.get('theme') || '';
  const next = order[(order.indexOf(cur) + 1) % order.length];
  store.set('theme', next);
  applyTheme();
  toast({'': t('Theme: follows your computer'), light: t('Theme: light'), dark: t('Theme: dark')}[next], 'info', 2000);
}
function applyTheme() {
  const v = store.get('theme');
  v ? document.documentElement.dataset.theme = v : delete document.documentElement.dataset.theme;
}

async function start() {
  const view = savedView();
  const lang = await getJSON('/api/lang');
  LANG = lang.language;
  WORDS = new Map(Object.entries(lang.catalog));
  applyTheme();
  $('#theme').onclick = theme;
  $('#lang').onclick = switchLanguage;
  $('#about-btn').onclick = about;
  $('#main').append(h('div', {id: 'picker'}), h('div', {id: 'results'}));
  if (view) Object.assign(S, view);
  buildSide();
  await refresh();
}
start().catch(fail);
