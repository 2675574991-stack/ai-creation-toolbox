/* AssetNest 素材巢 — 前端应用 */
'use strict';

/* ============================ 基础工具 ============================ */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const enc = encodeURIComponent;
const debounce = (fn, ms = 200) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const icon = (n, cls = '') => `<svg class="${cls}"><use href="#i-${n}"/></svg>`;

function fmtSize(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + ' B';
  const u = ['KB', 'MB', 'GB', 'TB'];
  let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < 3);
  return n.toFixed(n < 10 ? 2 : 1) + ' ' + u[i];
}
function fmtDur(s) {
  s = Math.round(Number(s) || 0);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}` : `${m}:${String(x).padStart(2, '0')}`;
}
function fmtDate(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000), now = new Date();
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  if (d.toDateString() === now.toDateString()) return '今天 ' + hm;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${hm}`;
}
const kindLabel = (k) => ({ image: '图片', video: '视频', audio: '音频', text: '文本', model: '模型' }[k] || k || '文件');

async function apiGet(path, params) {
  const u = new URL(path, location.origin);
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '' && !(Array.isArray(v) && !v.length)) {
      u.searchParams.set(k, Array.isArray(v) ? v.join(',') : v);
    }
  });
  const r = await fetch(u, { cache: 'no-store' });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `请求失败 (${r.status})`);
  return j;
}
async function apiPost(path, body, params) {
  const u = new URL(path, location.origin);
  Object.entries(params || {}).forEach(([k, v]) => v != null && v !== '' && u.searchParams.set(k, v));
  const r = await fetch(u, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `请求失败 (${r.status})`);
  return j;
}

function toast(msg, kind = '', ms = 2400, action = null) {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.innerHTML = (kind === 'ok' ? icon('check') : kind === 'err' ? icon('close') : icon('tag')) +
    `<span>${esc(msg)}</span>`;
  if (action) {
    const b = document.createElement('button');
    b.className = 'toast-act';
    b.textContent = action.label;
    b.onclick = () => { try { action.fn(); } catch (e) { } el.remove(); };
    el.appendChild(b);
  }
  $('#toasts').appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .2s'; setTimeout(() => el.remove(), 220); }, ms);
}

async function copyText(text, okMsg = '已复制') {
  let ok = false;
  try { await navigator.clipboard.writeText(text); ok = true; }
  catch (e) {
    try {
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
      ok = true;
    } catch (e2) { ok = false; }
  }
  if (!ok) { try { ok = (await apiPost('/api/copy', { text })).ok; } catch (e) { ok = false; } }
  toast(ok ? okMsg : '复制失败', ok ? 'ok' : 'err');
  return ok;
}

/* ============================ 状态 ============================ */
const S = {
  app: {}, project: null, tree: null, settings: {}, categories: [], recent: [], ffmpeg: false,
  folder: null, items: [], shown: 0, sel: new Set(), active: null,
  q: '', kinds: [], sort: 'name_asc', recursive: false, view: 'grid', tile: 220,
  loading: false, genQueue: [], genActive: 0, metaCache: new Map(), expanded: new Set(),
  generating: new Set(), reloadQueued: false, rev: 0, importing: false,
};

const LS = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { } },
};

const thumbUrl = (it, bust) => `/api/thumb?p=${enc(it.path)}&v=${it.thumb_v || 0}${bust ? '&g=' + Date.now() : ''}`;
const fileUrl = (it) => `/api/file?p=${enc(it.path)}&v=${it.thumb_v || 0}`;
const cardsFor = (path) => $$('[data-path]').filter((el) => el.dataset.path === path);

/* ============================ 启动 ============================ */
async function boot() {
  bindChrome();
  const data = await apiGet('/api/bootstrap');
  Object.assign(S, {
    app: data.app, project: data.project, tree: data.tree, settings: data.settings || {},
    categories: data.categories || [], recent: data.recent || [], ffmpeg: data.ffmpeg,
  });
  S.tile = Number(S.settings.tile) || 220;
  S.view = LS.get('an.view', 'grid');
  S.sort = S.settings.sort || 'name_asc';
  S.expanded = new Set(LS.get('an.expanded', []));
  S.rev = data.rev || 0;
  $('#tileRange').value = S.tile;
  $('#sort').value = S.sort;
  setView(S.view, false);

  if (!S.project) { showWelcome(); return; }
  $('#welcome').hidden = true;
  setChromeEnabled(true);
  renderProject();
  const qp = new URLSearchParams(location.search);
  const wanted = qp.get('folder');
  if (wanted) await openFolder(wanted);
  else await restoreFolder();
}

function setChromeEnabled(on) {
  $('.toolbar').hidden = !on;
  $('.statusbar').hidden = !on;
  $('#btnImport').disabled = !on;
  $('#btnExport').disabled = !on;
  $('#btnNewFolder').disabled = !on;
}

function showWelcome() {
  $('#welcome').hidden = false;
  $('#rows').hidden = true;
  $('#listView').hidden = true;
  $('#empty').hidden = true;
  $('#dock').hidden = true;
  document.querySelector('.app').classList.remove('docked');
  setChromeEnabled(false);
  $('#projectName').textContent = '未打开项目';
  $('#projectPath').textContent = '选择一个项目文件夹开始';
  $('#tree').innerHTML = '';
  $('#crumbs').innerHTML = '';
  $('#stLeft').textContent = '—';
  renderRecent();
}

function renderRecent() {
  const box = $('#wRecent');
  if (!S.recent?.length) { box.innerHTML = ''; return; }
  box.innerHTML = S.recent.slice(0, 4).map((p) =>
    `<button class="recent-chip" data-path="${esc(p.path)}">${icon('project')}<span>${esc(p.name || p.path)}</span></button>`).join('');
  $$('.recent-chip', box).forEach((b) => b.onclick = () => openProject(b.dataset.path));
}

async function openProject(path) {
  const r = await apiPost('/api/project', { path });
  S.project = r.project; S.tree = r.tree; S.settings = { ...S.settings, ...(r.settings || {}) };
  S.rev = r.rev || S.rev;
  $('#welcome').hidden = true;
  setChromeEnabled(true);
  renderProject();
  if (r.created?.length) toast(`已创建分类目录：${r.created.join('、')}`, 'ok', 3200);
  const remember = LS.get('an.lastFolder:' + S.project.root, null);
  await openFolder(remember && findNode(S.tree, remember) ? remember : S.tree.path);
}

function findNode(node, path) {
  if (!node) return null;
  if (node.path === path) return node;
  for (const c of node.children || []) { const r = findNode(c, path); if (r) return r; }
  return null;
}

function renderProject() {
  $('#projectName').textContent = S.project?.name || '未打开项目';
  $('#projectPath').textContent = S.project?.root || '';
  $('#projectPath').title = S.project?.root || '';
  renderTree();
}

async function restoreFolder() {
  const remember = LS.get('an.lastFolder:' + S.project.root, null);
  const start = remember && findNode(S.tree, remember) ? remember : S.tree.path;
  await openFolder(start);
}

/* ============================ 文件夹树 ============================ */
function renderTree() {
  const box = $('#tree');
  if (!S.tree) { box.innerHTML = ''; return; }
  box.innerHTML = treeNodeHtml(S.tree, 0);
  $$('.trow', box).forEach((row) => {
    const node = row.closest('.tnode');
    row.addEventListener('click', (e) => {
      if (e.target.closest('.caret')) { toggleNode(node); return; }
      openFolder(node.dataset.path);
    });
    row.addEventListener('contextmenu', (e) => { e.preventDefault(); treeMenu(e, node.dataset.path); });
    row.addEventListener('dragover', (e) => {
      if (!S.project) return;
      const internal = isInternalDrag(e);
      if (!internal && !hasFiles(e)) return;
      if (internal && node.dataset.path === S.project.root) {
        setTreeHover(node, true);
        return; // 根目录不作为移动目标
      }
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = internal ? 'move' : 'copy';
      setTreeHover(node, internal);
    });
    row.addEventListener('dragleave', (e) => {
      if (!node.contains(e.relatedTarget)) row.classList.remove('dnd-over');
    });
    row.addEventListener('drop', (e) => {
      if (!S.project) return;
      e.preventDefault();
      e.stopPropagation();
      const internal = isInternalDrag(e);
      clearTreeHover();
      $('#dropmask').classList.remove('on');
      dragDepth = 0;
      if (internal) dropInternal(e, node.dataset.path);
      else handleDrop(e, node.dataset.path);
    });
  });
  if (S.folder) {
    const el = [...box.querySelectorAll('.tnode')].find((n) => n.dataset.path === S.folder);
    if (el) { el.classList.add('active'); el.scrollIntoView({ block: 'nearest' }); }
  }
  $$('#rows .card, #lvBody .lv-row').forEach((el) => el.classList.toggle('sel', S.sel.has(el.dataset.path)));
}

function treeNodeHtml(node, depth) {
  const kids = node.children || [];
  const open = depth === 0 || S.expanded.has(node.path) || (S.folder || '').startsWith(node.path + '\\');
  const active = S.folder === node.path;
  const ic = node.icon || 'folder';
  const cnt = node.total ?? node.count ?? 0;
  return `<div class="tnode ${open ? 'open' : ''} ${active ? 'active' : ''}" data-path="${esc(node.path)}">
    <div class="trow ${depth ? 'sub' : ''}" style="--c:${node.color || '#8b93a7'}">
      <svg class="caret ${kids.length ? '' : 'hidden'}"><use href="#i-caret"/></svg>
      <span class="ticon">${icon(ic)}</span>
      <span class="tname" title="${esc(node.rel || node.name)}">${esc(node.name)}</span>
      <span class="tcount">${cnt}</span>
    </div>
    ${kids.length ? `<div class="tchildren">${kids.map((c) => treeNodeHtml(c, depth + 1)).join('')}</div>` : ''}
  </div>`;
}

function toggleNode(node) {
  const open = node.classList.toggle('open');
  if (open) S.expanded.add(node.dataset.path); else S.expanded.delete(node.dataset.path);
  LS.set('an.expanded', [...S.expanded]);
}

/* ---------- 拖到左侧分类节点 ---------- */
function hasFiles(e) { return [...(e.dataTransfer?.types || [])].includes('Files'); }

function setTreeHover(node, internal) {
  $$('.trow.dnd-over').forEach((r) => r.classList.remove('dnd-over'));
  const row = node.querySelector('.trow');
  if (row) row.classList.add('dnd-over');
  const isRoot = node.dataset.path === S.project.root;
  const name = node.querySelector('.tname')?.textContent || '';
  const verb = $('#dmVerb');
  if (internal) {
    verb.textContent = isRoot ? '无法移动到根目录' : '松开以移动';
    $('#dmTarget').textContent = isRoot ? '请拖到具体分类或子文件夹' : `「${name}」`;
  } else {
    verb.textContent = '松开以导入';
    $('#dmTarget').textContent = isRoot ? '项目根目录（按类型自动分类）' : `「${name}」`;
  }
  $('#dropmask').classList.add('on');
}

/* 内部拖拽：从右侧拖到左侧树 */
function isInternalDrag(e) {
  const t = [...(e.dataTransfer?.types || [])].map((x) => String(x).toLowerCase());
  return t.includes('application/x-assetnest');
}

function onDragStart(e) {
  const el = e.target.closest('.card, .lv-row');
  if (!el) return;
  if (e.target.closest('.card-star')) { e.preventDefault(); return; }
  const path = el.dataset.path;
  const paths = S.sel.has(path) ? [...S.sel] : [path];
  try {
    e.dataTransfer.setData('application/x-assetnest', JSON.stringify(paths));
    e.dataTransfer.setData('text/plain', paths.join('\n'));
  } catch (err) { }
  e.dataTransfer.effectAllowed = 'move';
}

function onDragEnd() {
  clearTreeHover();
  $('#dropmask').classList.remove('on');
  dragDepth = 0;
}

async function dropInternal(e, target) {
  let paths = [];
  try { paths = JSON.parse(e.dataTransfer.getData('application/x-assetnest') || '[]'); } catch (err) { paths = []; }
  if (!paths.length) return;
  if (target === S.project.root) { toast('请拖到具体的分类或子文件夹'); return; }
  await movePaths(paths, target);
}

async function movePaths(paths, target) {
  try {
    const r = await apiPost('/api/move', { paths, target });
    if (r.rev) S.rev = r.rev;
    S.tree = r.tree;
    renderTree();
    S.sel.clear(); S.active = null; closeDock();
    await loadFiles(true);
    const name = target.split('\\').pop();
    if (r.moved) {
      const action = r.ops?.length ? { label: '撤销', fn: () => undoMove(r.ops) } : null;
      toast(`已移动 ${r.moved} 项到「${name}」`, 'ok', 7000, action);
    } else if (r.skipped) {
      toast(`已在「${name}」里，无需移动`, '', 1800);
    }
    if (r.errors?.length) toast(r.errors[0], 'err', 3200);
  } catch (e) { toast(e.message, 'err', 3200); }
}

async function undoMove(pairs) {
  try {
    const r = await apiPost('/api/move/undo', { pairs });
    if (r.rev) S.rev = r.rev;
    S.tree = r.tree;
    renderTree();
    await loadFiles(true);
    toast(`已撤销 ${r.restored} 项移动`, 'ok', 1800);
  } catch (e) { toast(e.message, 'err', 3200); }
}

function clearTreeHover() {
  $$('.trow.dnd-over').forEach((r) => r.classList.remove('dnd-over'));
}

/* ============================ 打开文件夹 ============================ */
async function openFolder(path) {
  if (!S.project) return;
  S.folder = path;
  S.sel.clear(); S.active = null;
  S.recursive = path === S.project.root;
  $('#recursive').checked = S.recursive;
  $('#recursive').disabled = S.recursive;
  LS.set('an.lastFolder:' + S.project.root, path);
  if (path !== S.project.root) S.expanded.add(path);
  renderTree();
  renderCrumbs();
  closeDock();
  await loadFiles(true);
}

function renderCrumbs() {
  const box = $('#crumbs');
  if (!S.project) { box.innerHTML = ''; return; }
  const rel = S.folder === S.project.root ? '' : (findNode(S.tree, S.folder)?.rel || '');
  const parts = rel ? rel.split('/') : [];
  let acc = S.project.root;
  const out = [`<span class="cb ${parts.length ? '' : 'cur'}" data-path="${esc(S.project.root)}">${esc(S.project.name)}</span>`];
  parts.forEach((p, i) => {
    acc = acc + '\\' + p;
    out.push('<span class="sep">/</span>');
    out.push(`<span class="cb ${i === parts.length - 1 ? 'cur' : ''}" data-path="${esc(acc)}">${esc(p)}</span>`);
  });
  box.innerHTML = out.join('');
  $$('.cb', box).forEach((b) => b.onclick = () => openFolder(b.dataset.path));
}

/* ============================ 文件列表 ============================ */
async function loadFiles(reset = false) {
  if (!S.project || !S.folder) return;
  if (S.loading) { S.reloadQueued = true; return; }
  S.loading = true;
  $('#rows').hidden = S.view !== 'grid';
  if (reset) { S.items = []; S.shown = 0; rowSigs = []; }
  try {
    const data = await apiGet('/api/files', {
      folder: S.folder, recursive: S.recursive ? 1 : 0, sort: S.sort,
      q: S.q, kinds: S.kinds.join(','),
    });
    S.items = data.items || [];
    S.metaCache.clear();
    S.shown = Math.min(S.items.length, 120);
    $('#welcome').hidden = true;
    $('#empty').hidden = S.items.length !== 0;
    if (!S.items.length) {
      const folderName = S.folder.split('\\').pop();
      $('#emptyHint').textContent = S.q
        ? `没有匹配「${S.q}」的素材，换个关键词试试。`
        : `「${folderName}」里还没有素材，把文件拖进来就能导入。`;
      $('#rows').innerHTML = '';
      $('#lvBody').innerHTML = '';
    }
    await renderAll();
    updateStatus();
    applyDeepLink();
  } catch (e) {
    toast(e.message, 'err', 3600);
  } finally {
    S.loading = false;
    if (S.reloadQueued) { S.reloadQueued = false; setTimeout(() => loadFiles(true), 10); }
  }
}

async function renderAll() {
  if (S.view === 'grid') await renderGrid();
  else renderList();
  probeVideoDurations();
}

/* 视频没有时长信息时，用 <video> 元数据补一次（也兼容 ffmpeg 生成的旧封面） */
function probeVideoDurations() {
  const todo = S.items.slice(0, S.shown)
    .filter((i) => i.kind === 'video' && !i.duration && !i._probed).slice(0, 3);
  for (const it of todo) {
    it._probed = 1;
    enqueueGen(() => new Promise((resolve) => {
      const v = document.createElement('video');
      v.preload = 'metadata'; v.muted = true; v.src = fileUrl(it);
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        v.removeAttribute('src'); v.load();
        resolve();
      };
      const timer = setTimeout(finish, 6000);
      v.onloadedmetadata = async () => {
        const d = isFinite(v.duration) ? v.duration : 0;
        finish();
        if (d > 0) {
          it.duration = d;
          updateCardDur(it);
          try { await apiPost('/api/meta', { path: it.path, duration: d }); } catch (e) { }
        }
      };
      v.onerror = finish;
    }));
  }
}

/* 支持 #p=<路径> 直接定位素材（也便于外部调用） */
function applyDeepLink() {
  const m = location.hash.match(/#p=(.+)$/);
  if (!m) return;
  let target = '';
  try { target = decodeURIComponent(m[1]); } catch (e) { return; }
  history.replaceState(null, '', location.pathname);
  const it = S.items.find((i) => i.path === target);
  if (it) selectOnly(it.path);
}

/* ---------- 网格（justified 等高行） ---------- */
let rowSigs = [];

function computeRows(items, width, targetH, gap = 10) {
  const rows = [];
  let cur = [], ratio = 0;
  for (const it of items) {
    const ar = clamp(Number(it.ar) || 1, 0.42, 3.2);
    cur.push(it); ratio += ar;
    const h = (width - gap * (cur.length - 1)) / ratio;
    if (h <= targetH) { rows.push({ items: cur, h: Math.round(h) }); cur = []; ratio = 0; }
  }
  if (cur.length) rows.push({ items: cur, h: Math.round(targetH) });
  return rows;
}

function cardHtml(it, h) {
  const ar = clamp(Number(it.ar) || 1, 0.42, 3.2);
  const w = Math.max(72, Math.round(h * ar));
  const sel = S.sel.has(it.path) ? 'sel' : '';
  const plain = it.kind === 'text' || it.kind === 'model' || it.kind === 'other';
  const hasMedia = it.kind === 'image' || it.kind === 'video' || it.kind === 'audio';
  const badge = it.kind === 'video' ? `<span class="badge video">${icon('video')}视频</span>`
    : it.kind === 'audio' ? `<span class="badge audio">${icon('audio')}音频</span>`
      : it.kind === 'text' ? `<span class="badge script">${icon('text')}文本</span>`
        : it.kind === 'model' ? `<span class="badge model">${icon('prop')}模型</span>` : '';
  const ph = it.kind === 'audio' ? icon('audio') : it.kind === 'video' ? icon('video')
    : it.kind === 'text' ? icon('text') : it.kind === 'model' ? icon('prop') : icon('image');
  const sub = it.kind === 'image' && it.w ? `${it.w}×${it.h}` : it.size_text || '';
  return `<div class="card ${sel} ${it.favorite ? 'fav' : ''} ${it.duration ? 'has-dur' : ''} ${plain || !it.thumb ? 'always-cap' : ''}"
      draggable="true" style="width:${w}px;height:${h}px" data-path="${esc(it.path)}" title="${esc(it.name)}">
    <div class="ph">${ph}</div>
    ${hasMedia ? `<img loading="lazy" decoding="async" src="${thumbUrl(it)}" alt="" draggable="false">` : ''}
    <div class="card-badges">${badge}</div>
    <button class="card-star ${it.favorite ? 'on' : ''}" title="收藏">${icon('star')}</button>
    <div class="card-check">${icon('check')}</div>
    ${it.kind === 'video' ? `<div class="play-hint">${icon('play')}</div>` : ''}
    <div class="card-dur">${it.duration ? fmtDur(it.duration) : ''}</div>
    <div class="card-cap">
      <div class="card-name">${esc(it.name)}</div>
      <div class="card-sub"><span>${esc(sub)}</span>${it.tags?.length ? `<span>· ${esc(it.tags.slice(0, 2).join(' / '))}</span>` : ''}</div>
    </div>
  </div>`;
}

async function renderGrid() {
  const box = $('#rows');
  const width = Math.max(240, box.clientWidth - 40);
  const items = S.items.slice(0, S.shown);
  const rows = computeRows(items, width, S.tile);
  const sigs = rows.map((r) => r.h + '|' + r.items.map((i) => i.path).join('|'));

  if (!rowSigs.length || rowSigs.length > sigs.length) {
    box.innerHTML = rows.map((r) => `<div class="jrow" style="height:${r.h}px">${r.items.map((it) => cardHtml(it, r.h)).join('')}</div>`).join('');
  } else {
    for (let i = 0; i < rows.length; i++) {
      if (rowSigs[i] !== sigs[i]) {
        const html = `<div class="jrow" style="height:${rows[i].h}px">${rows[i].items.map((it) => cardHtml(it, rows[i].h)).join('')}</div>`;
        if (box.children[i]) box.children[i].outerHTML = html;
        else box.insertAdjacentHTML('beforeend', html);
      }
    }
  }
  rowSigs = sigs;
  box.hidden = false;
  attachCardEvents(box);
}

function attachCardEvents(box) {
  $$('img', box).forEach((img) => {
    if (img.dataset.bound) return;
    img.dataset.bound = '1';
    img.addEventListener('error', () => onThumbError(img), { once: true });
  });
}

/* ---------- 列表 ---------- */
function renderList() {
  const body = $('#lvBody');
  $('#listView').hidden = false;
  $('#rows').hidden = true;
  const items = S.items.slice(0, S.shown);
  body.innerHTML = items.map((it) => {
    const ic = it.kind === 'video' ? icon('video') : it.kind === 'audio' ? icon('audio')
      : it.kind === 'text' ? icon('text') : it.kind === 'model' ? icon('prop') : icon('image');
    const dim = it.kind === 'image' ? `${it.w || '?'}×${it.h || '?'}` : it.duration ? fmtDur(it.duration) : '—';
    return `<div class="lv-row ${S.sel.has(it.path) ? 'sel' : ''}" draggable="true" data-path="${esc(it.path)}">
      <span class="lv-c1"><span class="lv-thumb">${ic}${it.kind !== 'text' && it.kind !== 'model' ? `<img loading="lazy" src="${thumbUrl(it)}" alt="">` : ''}</span>
      <span class="lv-name" title="${esc(it.name)}">${esc(it.name)}</span></span>
      <span class="lv-dim">${esc(kindLabel(it.kind))}</span>
      <span class="lv-dim">${fmtSize(it.size)}</span>
      <span class="lv-dim">${dim}</span>
      <span class="lv-dim">${fmtDate(it.mtime)}</span>
      <span class="lv-tags">${(it.tags || []).slice(0, 3).map((t) => `<span class="lv-tag">${esc(t)}</span>`).join('')}</span>
    </div>`;
  }).join('');
  attachCardEvents(body);
}

/* ---------- 缩略图兜底：视频抽帧 / 音频波形 ---------- */
function onThumbError(img) {
  const card = img.closest('[data-path]');
  if (!card) return;
  const it = S.items.find((x) => x.path === card.dataset.path);
  img.style.display = 'none';
  if (!it || img.dataset.gen) return;
  img.dataset.gen = '1';
  if (it.kind === 'video') enqueueGen(() => generatePoster(it));
  else if (it.kind === 'audio') enqueueGen(() => generatePeaks(it));
}

function enqueueGen(fn) { S.genQueue.push(fn); pumpGen(); }
function pumpGen() {
  while (S.genActive < 2 && S.genQueue.length) {
    const fn = S.genQueue.shift();
    S.genActive++;
    Promise.resolve().then(fn).catch(() => { }).finally(() => { S.genActive--; pumpGen(); });
  }
}

function markThumb(it) {
  it.thumb = 1;
  cardsFor(it.path).forEach((card) => {
    card.classList.remove('always-cap');
    const img = card.querySelector('img');
    if (!img) return;
    img.style.display = '';
    img.dataset.gen = '';
    img.src = thumbUrl(it, true);
  });
}

async function generatePoster(it) {
  if (S.generating.has(it.path)) return;
  S.generating.add(it.path);
  try {
    const res = await captureVideoFrame(fileUrl(it));
    if (!res) return;
    const r = await apiPost('/api/poster', { path: it.path, data: res.data, duration: res.duration || 0 });
    if (r.ok) {
      if (r.duration) { it.duration = r.duration; updateCardDur(it); }
      markThumb(it);
    }
  } catch (e) { /* 静默 */ } finally { S.generating.delete(it.path); }
}

function captureVideoFrame(src) {
  return new Promise((resolve) => {
    const v = document.createElement('video');
    v.muted = true; v.playsInline = true; v.preload = 'auto'; v.src = src;
    let settled = false;
    const finish = (val) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      v.removeAttribute('src'); v.load();
      resolve(val);
    };
    const timer = setTimeout(() => finish(null), 12000);
    v.onerror = () => finish(null);
    v.onloadeddata = () => {
      try {
        const t = isFinite(v.duration) && v.duration > 1 ? Math.min(1.2, v.duration * 0.15) : 0.1;
        v.currentTime = t;
      } catch (e) { draw(); }
    };
    v.onseeked = draw;
    function draw() {
      try {
        const w = v.videoWidth, h = v.videoHeight;
        if (!w || !h) return finish(null);
        const scale = Math.min(1, 720 / Math.max(w, h));
        const c = document.createElement('canvas');
        c.width = Math.round(w * scale); c.height = Math.round(h * scale);
        c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
        finish({ data: c.toDataURL('image/webp', 0.82), duration: isFinite(v.duration) ? v.duration : 0 });
      } catch (e) { finish(null); }
    }
  });
}

async function generatePeaks(it) {
  if (S.generating.has(it.path)) return;
  S.generating.add(it.path);
  try {
    const res = await fetch(fileUrl(it));
    const buf = await res.arrayBuffer();
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    const ctx = new AC();
    const audio = await ctx.decodeAudioData(buf);
    const ch = audio.getChannelData(0);
    const N = 180, step = Math.max(1, Math.floor(ch.length / N));
    const peaks = [];
    for (let i = 0; i < N; i++) {
      let max = 0;
      const start = i * step;
      for (let j = 0; j < step; j += 4) { const v = Math.abs(ch[start + j] || 0); if (v > max) max = v; }
      peaks.push(Math.min(1, max));
    }
    const max = Math.max(...peaks, 0.001);
    const norm = peaks.map((p) => p / max);
    const r = await apiPost('/api/peaks', { path: it.path, peaks: norm, duration: audio.duration });
    it.duration = audio.duration || 0;
    if (r.ok) markThumb(it);
    ctx.close();
  } catch (e) { /* 忽略解码失败 */ } finally { S.generating.delete(it.path); }
}

/* ============================ 选择 / 检查器 ============================ */
function findItem(path) { return S.items.find((i) => i.path === path); }

function selectOnly(path) {
  S.sel.clear();
  if (path) S.sel.add(path);
  S.active = path || null;
  paintSelection();
  if (path) openDock(findItem(path)); else closeDock();
}
function toggleSelect(path) {
  if (S.sel.has(path)) S.sel.delete(path); else S.sel.add(path);
  S.active = path;
  paintSelection();
  if (S.sel.size === 1) openDock(findItem([...S.sel][0]));
  else if (!S.sel.size) closeDock();
  else renderDockMulti();
}
function paintSelection() {
  $$('#rows .card, #lvBody .lv-row').forEach((el) => el.classList.toggle('sel', S.sel.has(el.dataset.path)));
  updateStatus();
}
function updateStatus() {
  const total = S.items.length;
  const size = S.items.reduce((a, i) => a + (i.size || 0), 0);
  $('#stLeft').textContent = total
    ? `共 ${total} 个文件 · ${fmtSize(size)}${S.folder === S.project?.root ? ' · 全部资产' : ''}`
    : '空文件夹';
  $('#stSel').textContent = S.sel.size > 1 ? `已选 ${S.sel.size} 项` : '';
}

function queueLayout() {
  if (S.view !== 'grid' || !S.items.length) return;
  setTimeout(() => { rowSigs = []; renderGrid(); }, 240);
}

const dock = {
  el: null,
  init() { this.el = $('#dock'); },
  open(item) {
    if (!item) return;
    document.querySelector('.app').classList.add('docked');
    this.el.hidden = false;
    this.render(item);
    queueLayout();
  },
  close() {
    document.querySelector('.app').classList.remove('docked');
    this.el.hidden = true;
    this.el.innerHTML = '';
    queueLayout();
  },
  render(item) {
    const cached = S.metaCache.get(item.path);
    this.el.innerHTML = `<div class="dock-inner">
      <div class="dock-head"><span class="dh-title">素材信息</span>
        <button class="icon-btn tiny" data-dock="folder" title="在资源管理器中显示">${icon('folder')}</button>
        <button class="icon-btn tiny" data-dock="close" title="关闭 (Esc)">${icon('close')}</button></div>
      <div class="dock-scroll">
        <div class="dock-preview" id="dockPreview">${this.previewHtml(item)}</div>
        <div class="dock-body" id="dockBody">${this.bodyHtml(item, cached)}</div>
      </div></div>`;
    this.bind(item);
    if (!cached) this.loadMeta(item);
  },
  previewHtml(it) {
    if (it.kind === 'image' || it.kind === 'video') {
      return `<img src="${thumbUrl(it)}" alt="" data-preview>
        <button class="expand" title="放大预览 (空格)">${icon('maximize')}</button>`;
    }
    if (it.kind === 'audio') {
      return `<img src="${thumbUrl(it)}" alt="" data-preview>
        <button class="expand" title="播放 (空格)">${icon('play')}</button>`;
    }
    return `<div class="ph-big">${icon(it.kind === 'text' ? 'text' : 'file')}<span>${esc((it.ext || '').toUpperCase() || '文件')}</span></div>`;
  },
  bodyHtml(it, m) {
    const tags = m?.tags || it.tags || [];
    const bits = [`<span class="meta-pill">${esc(kindLabel(it.kind))}</span>`,
      `<span class="meta-pill"><b>${fmtSize(it.size)}</b></span>`];
    if (it.w && it.h) bits.push(`<span class="meta-pill">${it.w}×${it.h}</span>`);
    if (it.duration) bits.push(`<span class="meta-pill">${fmtDur(it.duration)}</span>`);
    bits.push(`<span class="meta-pill">${fmtDate(it.mtime)}</span>`);
    const fav = (m?.favorite ?? it.favorite);
    return `
      <h2 class="file-title" title="${esc(it.name)}">${esc(it.name)}</h2>
      <div class="file-path" data-dock="copypath" title="点击复制完整路径">${esc(it.path)}</div>
      <div class="meta-row">${bits.join('')}</div>
      <div class="rate-row">
        <span class="lab">评分</span>
        ${[1, 2, 3, 4, 5].map((n) => `<button class="star-btn ${(m?.rating ?? it.rating ?? 0) >= n ? 'on' : ''}" data-rate="${n}">${icon('star')}</button>`).join('')}
        <span style="flex:1"></span>
        <button class="btn" data-dock="fav" style="height:26px;font-size:11px">${icon('star')}<span>${fav ? '已收藏' : '收藏'}</span></button>
      </div>
      <div class="dock-actions">
        <button class="btn primary" data-dock="open">${icon('external')}打开</button>
        <button class="btn" data-dock="reveal">${icon('folder')}定位</button>
        <button class="btn" data-dock="copypath">${icon('copy')}复制路径</button>
      </div>
      <div id="dockMeta">${this.metaHtml(it, m)}</div>
      <div class="sec">
        <div class="sec-h"><b>标签</b></div>
        <div class="tags-box" id="tagBox">
          ${tags.map((t) => this.tagChip(t)).join('')}
          <input class="tag-input" id="tagInput" placeholder="+ 标签" maxlength="24">
        </div>
      </div>
      <div class="sec">
        <div class="sec-h"><b>备注</b></div>
        <textarea class="note-area" id="noteArea" placeholder="记录这一版的想法、出处、待修改点…">${esc(m?.note ?? it.note ?? '')}</textarea>
      </div>`;
  },
  tagChip(t) { return `<span class="tag-chip">${esc(t)}<button data-tagdel="${esc(t)}" title="移除">×</button></span>`; },
  metaHtml(it, m) {
    if (!m) return '';
    const out = [];
    if (m.positive) {
      out.push(`<div class="sec"><div class="sec-h"><b>正面提示词</b>
        <button class="copy-mini" data-copy="pos">${icon('copy')}复制</button></div>
        <div class="prompt">${esc(m.positive)}</div></div>`);
    }
    if (m.negative) {
      out.push(`<div class="sec"><div class="sec-h"><b>负面提示词</b>
        <button class="copy-mini" data-copy="neg">${icon('copy')}复制</button></div>
        <div class="prompt neg">${esc(m.negative)}</div></div>`);
    }
    if (m.text) {
      out.push(`<div class="sec"><div class="sec-h"><b>内容预览</b>
        <button class="copy-mini" data-copy="text">${icon('copy')}复制</button></div>
        <div class="prompt" style="max-height:220px">${esc(m.text)}</div></div>`);
    }
    const ps = [];
    if (m.model) ps.push(['模型', m.model]);
    if (m.steps) ps.push(['步数', m.steps]);
    if (m.sampler) ps.push(['采样器', m.sampler]);
    if (m.cfg) ps.push(['CFG', m.cfg]);
    if (m.seed) ps.push(['种子', m.seed]);
    if (m.loras?.length) ps.push(['LoRA', Array.isArray(m.loras) ? m.loras.join(', ') : m.loras]);
    if (ps.length) {
      out.push(`<div class="sec"><div class="sec-h"><b>生成参数</b>
        <button class="copy-mini" data-copyall>${icon('copy')}全部</button></div>
        <div class="params">${ps.map(([k, v]) => `<div class="param"><i>${esc(k)}</i><b title="${esc(v)}">${esc(v)}</b></div>`).join('')}</div></div>`);
    }
    return out.join('');
  },
  bind(item) {
    const el = this.el;
    const m = () => S.metaCache.get(item.path) || {};
    $('[data-dock="close"]', el).onclick = () => this.close();
    $('[data-dock="folder"]', el).onclick = () => reveal(item.path);
    $$('[data-dock="open"]', el).forEach((b) => b.onclick = () => openFile(item));
    $$('[data-dock="reveal"]', el).forEach((b) => b.onclick = () => reveal(item.path));
    $$('[data-dock="copypath"]', el).forEach((b) => b.onclick = () => copyText(item.path, '路径已复制'));
    $$('[data-dock="fav"]', el).forEach((b) => b.onclick = () => toggleFav(item));
    $$('[data-rate]', el).forEach((b) => b.onclick = () => rate(item, Number(b.dataset.rate)));
    $('#dockPreview', el).onclick = () => openLightbox(item);
    const tagInput = $('#tagInput', el);
    if (tagInput) {
      tagInput.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter' && tagInput.value.trim()) {
          e.preventDefault();
          const t = tagInput.value.trim(); tagInput.value = '';
          await addTag(item, t);
        }
      });
    }
    $$('[data-tagdel]', el).forEach((b) => b.onclick = () => removeTag(item, b.dataset.tagdel));
    const note = $('#noteArea', el);
    if (note) {
      note.addEventListener('blur', () => saveNote(item, note.value));
      note.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); note.blur(); }
      });
    }
    const cp = (b) => {
      const k = b.dataset.copy;
      const md = m();
      copyText(k === 'pos' ? md.positive : k === 'neg' ? md.negative : md.text, '已复制到剪贴板');
    };
    $$('[data-copy]', el).forEach((b) => b.onclick = (e) => { e.stopPropagation(); cp(b); });
    $$('[data-copyall]', el).forEach((b) => b.onclick = () => copyAllParams(m()));
  },
  async loadMeta(item) {
    try {
      const md = await apiGet('/api/meta', { p: item.path });
      S.metaCache.set(item.path, md);
      if (S.active !== item.path) return;
      const box = $('#dockMeta');
      if (box) {
        box.innerHTML = this.metaHtml(item, md);
        $$('#dockMeta [data-copy]').forEach((b) => b.onclick = (e) => {
          e.stopPropagation();
          const k = b.dataset.copy;
          copyText(k === 'pos' ? md.positive : k === 'neg' ? md.negative : md.text, '已复制到剪贴板');
        });
        $$('#dockMeta [data-copyall]').forEach((b) => b.onclick = () => copyAllParams(md));
      }
      if (md.duration && !item.duration) { item.duration = md.duration; updateCardDur(item); }
    } catch (e) { /* 忽略 */ }
  },
};

function copyAllParams(md) {
  if (!md) return;
  const txt = [
    md.positive && `Positive: ${md.positive}`,
    md.negative && `Negative: ${md.negative}`,
    md.model && `Model: ${md.model}`,
    md.steps && `Steps: ${md.steps}`,
    md.sampler && `Sampler: ${md.sampler}`,
    md.cfg && `CFG: ${md.cfg}`,
    md.seed && `Seed: ${md.seed}`,
  ].filter(Boolean).join('\n');
  if (txt) copyText(txt, '生成参数已复制'); else toast('这个文件没有生成参数');
}

function updateCardDur(it) {
  cardsFor(it.path).forEach((el) => {
    el.classList.toggle('has-dur', !!it.duration);
    const d = el.querySelector('.card-dur');
    if (d) d.textContent = it.duration ? fmtDur(it.duration) : '';
  });
}

function openDock(item) { dock.init(); dock.open(item); }
function closeDock() { dock.init(); dock.close(); }

function renderDockMulti() {
  const n = S.sel.size;
  document.querySelector('.app').classList.add('docked');
  const el = $('#dock'); el.hidden = false;
  el.innerHTML = `<div class="dock-inner"><div class="dock-head"><span class="dh-title">批量操作</span>
    <button class="icon-btn tiny" data-dock="close">${icon('close')}</button></div>
    <div class="dock-body"><h2 class="file-title">已选择 ${n} 项</h2>
    <div class="dock-actions" style="flex-wrap:wrap">
      <button class="btn" data-batch="fav">${icon('star')}收藏</button>
      <button class="btn" data-batch="copy">${icon('copy')}复制路径</button>
      <button class="btn" data-batch="tag">${icon('tag')}加标签</button>
      <button class="btn danger" data-batch="del">${icon('trash')}删除</button>
    </div>
    <p style="font-size:11.5px;color:var(--mut);line-height:1.7">Ctrl / Shift 可加选，双击任意素材用系统程序打开。删除会先放入回收站。</p>
    </div></div>`;
  $('[data-dock="close"]', el).onclick = () => closeDock();
  $$('[data-batch]', el).forEach((b) => b.onclick = () => batchAction(b.dataset.batch));
  queueLayout();
}

/* ============================ 元数据编辑 ============================ */
async function patchItem(item, patch) {
  const r = await apiPost('/api/meta', { path: item.path, ...patch });
  Object.assign(item, { favorite: r.favorite, rating: r.rating, tags: r.tags, note: r.note });
  const md = S.metaCache.get(item.path);
  if (md) Object.assign(md, r);
  refreshCards(item);
  return r;
}
function refreshCards(item) {
  cardsFor(item.path).forEach((el) => {
    el.classList.toggle('fav', !!item.favorite);
    const star = el.querySelector('.card-star');
    if (star) star.classList.toggle('on', !!item.favorite);
  });
}
async function toggleFav(item) {
  try {
    item.favorite = item.favorite ? 0 : 1;
    await patchItem(item, { favorite: item.favorite });
    if (S.active === item.path) openDock(item);
    toast(item.favorite ? '已收藏' : '已取消收藏', 'ok', 1400);
  } catch (e) { toast(e.message, 'err'); }
}
async function rate(item, n) {
  try {
    item.rating = item.rating === n ? 0 : n;
    await patchItem(item, { rating: item.rating });
    if (S.active === item.path) openDock(item);
  } catch (e) { toast(e.message, 'err'); }
}
async function addTag(item, t) {
  if (!t) return;
  try {
    await patchItem(item, { tags: [...new Set([...(item.tags || []), t])] });
    if (S.active === item.path) openDock(item);
    toast(`已添加标签「${t}」`, 'ok', 1200);
  } catch (e) { toast(e.message, 'err'); }
}
async function removeTag(item, t) {
  try {
    await patchItem(item, { tags: (item.tags || []).filter((x) => x !== t) });
    if (S.active === item.path) openDock(item);
  } catch (e) { toast(e.message, 'err'); }
}
const saveNote = debounce(async (item, v) => {
  if ((item.note || '') === v) return;
  try { await patchItem(item, { note: v }); toast('备注已保存', 'ok', 1200); } catch (e) { toast(e.message, 'err'); }
}, 400);

/* ============================ 文件操作 ============================ */
async function openFile(item) {
  try { await apiPost('/api/reveal', { path: item.path, open: true }); }
  catch (e) { toast(e.message, 'err'); }
}
async function reveal(path) {
  try { await apiPost('/api/reveal', { path }); }
  catch (e) { toast(e.message, 'err'); }
}
async function renamePath(path, oldName) {
  const name = await promptDialog({ title: '重命名', label: '新名称', value: oldName, hint: '扩展名可以省略，会自动保留。' });
  if (!name || name === oldName) return;
  try {
    const r = await apiPost('/api/rename', { path, name });
    S.tree = r.tree;
    if (r.rev) S.rev = r.rev;
    renderTree();
    toast('已重命名', 'ok', 1400);
    await loadFiles(true);
  } catch (e) { toast(e.message, 'err', 3200); }
}
async function deletePaths(paths) {
  if (!paths.length) return;
  const names = paths.length === 1 ? `「${paths[0].split('\\').pop()}」` : `${paths.length} 项`;
  const ok = await confirmDialog({
    title: '删除素材',
    text: `确定删除 ${names} 吗？文件会放入系统回收站，可以从回收站还原。`,
    confirm: '删除', danger: true,
  });
  if (!ok) return;
  try {
    const r = await apiPost('/api/delete', { paths });
    S.tree = r.tree; renderTree();
    if (r.rev) S.rev = r.rev;
    S.sel.clear(); S.active = null; closeDock();
    await loadFiles(true);
    toast(`已删除 ${r.deleted} 项`, 'ok', 1600);
    if (r.errors?.length) toast(r.errors[0], 'err', 3000);
  } catch (e) { toast(e.message, 'err'); }
}
async function newFolder(parent) {
  if (!S.project) { toast('请先打开项目', 'err'); return; }
  const def = parent || (S.folder && findNode(S.tree, S.folder) ? S.folder : S.project.root);
  const choice = await newFolderDialog(def);
  if (!choice) return;
  try {
    const r = await apiPost('/api/mkdir', { parent: choice.parent, name: choice.name });
    const made = r.path.split('\\').pop();
    if (r.outside) {
      toast(`已创建「${made}」（不在当前项目中）`, 'ok', 8000, {
        label: '设为项目', fn: () => openProject(r.path),
      });
      return;
    }
    S.tree = r.tree;
    if (r.rev) S.rev = r.rev;
    S.expanded.add(choice.parent);
    renderTree();
    toast(`已创建「${made}」`, 'ok', 1600);
    await openFolder(r.path);
  } catch (e) { toast(e.message, 'err', 3200); }
}

function newFolderHere() { newFolder(null); }

/* 新建文件夹对话框：名称 + 从「此电脑」开始的位置浏览 */
function newFolderDialog(defaultParent) {
  return new Promise((resolve) => {
    modal(`<div class="m-head"><h3>新建文件夹</h3></div>
      <div class="m-body">
        <label class="m-label">名称</label>
        <input class="m-input" id="nfName" value="新建文件夹" spellcheck="false">
        <div class="m-label" style="display:flex;align-items:center;gap:2px;margin-top:12px">
          <span>位置</span><span style="flex:1"></span>
          <button class="mini-link" id="nfHome">项目目录</button>
          <button class="mini-link" id="nfComputer">此电脑</button>
        </div>
        <div class="fsb">
          <div class="fsb-bar">
            <button class="icon-btn tiny" id="nfUp" title="上一级">↑</button>
            <div class="fsb-crumbs" id="nfCrumbs"></div>
          </div>
          <div class="fsb-list" id="nfList"></div>
        </div>
        <div class="m-hint" id="nfPath"></div>
      </div>
      <div class="m-foot"><button class="btn" data-x>取消</button><button class="btn primary" data-ok>创建</button></div>`,
      (m) => {
        let cur = defaultParent || S.project.root;
        const nameEl = $('#nfName', m);
        const listEl = $('#nfList', m);
        const crumbsEl = $('#nfCrumbs', m);
        const hint = $('#nfPath', m);
        const upBtn = $('#nfUp', m);

        const updateHint = () => {
          const nm = nameEl.value.trim() || '未命名';
          if (!cur) { hint.textContent = '请选择一个位置'; return; }
          const outside = !cur.toLowerCase().startsWith((S.project.root || '').toLowerCase());
          hint.innerHTML = `将创建：${esc(cur)}${cur.endsWith('\\') ? '' : '\\'}${esc(nm)}` +
            (outside ? ' <span style="color:#ffb3b9">（不在当前项目中）</span>' : '');
        };

        const renderCrumbs = (path) => {
          const parts = [{ label: '此电脑', path: '' }];
          if (path) {
            const segs = path.split('\\').filter(Boolean);
            let acc = '';
            segs.forEach((s, i) => {
              acc += i === 0 ? s : '\\' + s;
              parts.push({ label: s, path: i === 0 ? acc + '\\' : acc });
            });
          }
          crumbsEl.innerHTML = parts.map((p, i) =>
            `<button class="fsb-crumb ${i === parts.length - 1 ? 'cur' : ''}" data-path="${esc(p.path)}">${esc(p.label)}</button>`)
            .join('<span class="fsb-sep">›</span>');
          $$('.fsb-crumb', crumbsEl).forEach((b) => b.onclick = () => nav(b.dataset.path));
        };

        const nav = async (path) => {
          listEl.innerHTML = '<div class="fsb-empty">读取中…</div>';
          try {
            const r = await apiGet('/api/fs', { path: path || '' });
            cur = r.path;
            renderCrumbs(r.path);
            upBtn.disabled = !r.path;
            if (!r.dirs.length) {
              listEl.innerHTML = '<div class="fsb-empty">没有子文件夹</div>';
            } else {
              listEl.innerHTML = r.dirs.map((d) =>
                `<div class="fsb-item" data-path="${esc(d.path)}">${icon('folder')}<span title="${esc(d.path)}">${esc(d.name)}</span></div>`).join('');
              $$('.fsb-item', listEl).forEach((el) => el.onclick = () => nav(el.dataset.path));
            }
            updateHint();
          } catch (e) {
            listEl.innerHTML = `<div class="fsb-empty">${esc(e.message)}</div>`;
          }
        };

        upBtn.onclick = async () => {
          try { const r = await apiGet('/api/fs', { path: cur }); nav(r.parent); } catch (e) { }
        };
        $('#nfHome', m).onclick = () => nav(S.project.root);
        $('#nfComputer', m).onclick = () => nav('');
        nameEl.addEventListener('input', updateHint);
        nameEl.focus(); nameEl.select();
        nav(cur);

        const done = (v) => { closeModal(); resolve(v); };
        $('[data-ok]', m).onclick = () => {
          const nm = nameEl.value.trim();
          if (!nm) { nameEl.focus(); toast('请输入文件夹名称', 'err', 1600); return; }
          if (!cur) { toast('请先选择一个位置', 'err', 1600); return; }
          done({ name: nm, parent: cur });
        };
        $('[data-x]', m).onclick = () => done(null);
        nameEl.onkeydown = (e) => {
          if (e.key === 'Enter') $('[data-ok]', m).click();
          if (e.key === 'Escape') done(null);
        };
      });
  });
}
async function batchAction(kind) {
  const ids = [...S.sel];
  if (!ids.length) return;
  if (kind === 'fav') {
    const allFav = ids.every((p) => findItem(p)?.favorite);
    for (const p of ids) {
      const it = findItem(p); if (!it) continue;
      it.favorite = allFav ? 0 : 1;
      try { await patchItem(it, { favorite: it.favorite }); } catch (e) { }
    }
    toast(allFav ? '已取消收藏' : '已收藏', 'ok', 1400);
  } else if (kind === 'copy') {
    copyText(ids.join('\n'), `已复制 ${ids.length} 条路径`);
  } else if (kind === 'tag') {
    const t = await promptDialog({ title: '批量添加标签', label: '标签名', value: '' });
    if (!t) return;
    for (const p of ids) {
      const it = findItem(p); if (!it) continue;
      try { await patchItem(it, { tags: [...new Set([...(it.tags || []), t])] }); } catch (e) { }
    }
    toast('标签已添加', 'ok', 1400);
  } else if (kind === 'del') {
    await deletePaths(ids);
  }
}

/* ============================ 导入 ============================ */
function targetFolderFor() {
  if (!S.project) return null;
  if (S.folder && S.folder !== S.project.root) return S.folder;
  return null; // 由服务端按类型归档
}
function targetLabel() {
  if (S.folder && S.folder !== S.project.root) return S.folder.split('\\').pop();
  return '自动分类（图片→人物 / 视频→视频 / 音频→音频 / 文本→剧本）';
}

function openFilePicker() {
  const inp = document.createElement('input');
  inp.type = 'file'; inp.multiple = true;
  inp.onchange = () => { if (inp.files?.length) uploadFiles([...inp.files]); };
  inp.click();
}

async function uploadFiles(list, target) {
  if (!S.project) { toast('请先打开项目', 'err'); return; }
  const entries = list.map((f) => (f && f.file) ? f : { file: f, rel: f.webkitRelativePath || f.name });
  if (!entries.length) return;
  // target: undefined = 当前文件夹/自动分类；具体路径 = 拖到了某个分类节点
  const folder = target === undefined ? targetFolderFor() : (target === S.project.root ? null : target);
  const destLabel = folder ? folder.split('\\').pop() : '自动分类';
  S.importing = true;
  const panel = $('#transfer');
  panel.hidden = false;
  $('#trTitle').textContent = `正在导入 ${entries.length} 个文件到「${destLabel}」…`;
  const listEl = $('#trList'); listEl.innerHTML = '';
  let done = 0, failed = 0, sentBytes = 0, lastRev = S.rev;
  const rows = new Map();
  for (const en of entries) {
    const el = document.createElement('div');
    el.className = 'tr-item';
    el.innerHTML = `<span class="n">${esc(en.file.name)}</span><span class="s">等待</span>`;
    listEl.appendChild(el);
    rows.set(en, el);
  }
  const totalBytes = entries.reduce((a, en) => a + en.file.size, 0) || 1;

  const worker = async (en) => {
    const el = rows.get(en);
    const f = en.file;
    try {
      const res = await uploadOne(f, en.rel, folder, (loaded) => {
        el.querySelector('.s').textContent = Math.round((loaded / Math.max(f.size, 1)) * 100) + '%';
      });
      if (res?.rev) lastRev = res.rev;
      el.classList.add('done');
      el.querySelector('.s').textContent = '完成';
      sentBytes += f.size;
      done++;
    } catch (e) {
      failed++;
      el.classList.add('err');
      el.querySelector('.s').textContent = '失败';
      console.warn(e);
    }
    $('#trFill').style.width = clamp(Math.round((sentBytes / totalBytes) * 100), 0, 100) + '%';
    $('#trMeta').textContent = `${done + failed}/${entries.length} · 成功 ${done}${failed ? ` · 失败 ${failed}` : ''}`;
  };

  const queue = [...entries];
  await Promise.all(Array.from({ length: 2 }, async () => {
    while (queue.length) await worker(queue.shift());
  }));

  $('#trTitle').textContent = failed
    ? `导入完成，${failed} 个失败`
    : `已导入 ${done} 个文件到「${destLabel}」`;
  S.rev = lastRev;
  S.importing = false;
  setTimeout(() => { panel.hidden = true; }, 3200);
  await refreshTree();
  await loadFiles(true);
  if (done) toast(`已导入 ${done} 个文件到「${destLabel}」`, 'ok', 1800);
}

function uploadOne(file, rel, folder, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const url = '/api/import' + (folder ? `?folder=${enc(folder)}` : '');
    xhr.open('POST', url, true);
    xhr.setRequestHeader('X-File-Rel', enc(rel));
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(e.loaded); };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
      else {
        let msg = 'HTTP ' + xhr.status;
        try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) { }
        reject(new Error(msg));
      }
    };
    xhr.onerror = () => reject(new Error('网络错误'));
    xhr.send(file);
  });
}

async function refreshTree() {
  try {
    const r = await apiGet('/api/tree');
    S.tree = r.tree; S.project = r.project;
    renderTree();
    $('#projectPath').textContent = S.project.root;
  } catch (e) { }
}

/* ---------- 拖拽导入（可拖到左侧分类节点，也可拖进窗口） ---------- */
let dragDepth = 0;

function bindDrag() {
  const mask = $('#dropmask');
  window.addEventListener('dragenter', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth++;
    if (!S.project) return;
    mask.classList.add('on');
    const cur = S.folder && S.folder !== S.project.root ? S.folder.split('\\').pop() : '';
    $('#dmTarget').textContent = cur ? `「${cur}」` : '按类型自动分类（或拖到左侧分类）';
  });
  window.addEventListener('dragover', (e) => {
    if (!S.project || !hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  });
  window.addEventListener('dragleave', (e) => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) { mask.classList.remove('on'); clearTreeHover(); }
  });
  window.addEventListener('drop', async (e) => {
    if (!S.project) return;
    e.preventDefault();
    dragDepth = 0;
    mask.classList.remove('on');
    clearTreeHover();
    if (isInternalDrag(e)) return; // 内部拖拽只接受左侧文件夹作为目标
    handleDrop(e, null);
  });
}

async function handleDrop(e, targetPath) {
  const items = [...(e.dataTransfer?.items || [])];
  let entries = [];
  try { entries = items.map((i) => i.webkitGetAsEntry?.()).filter(Boolean); } catch (err) { entries = []; }
  if (entries.length) {
    const files = [];
    for (const en of entries) await walkEntry(en, '', files);
    if (files.length) uploadFiles(files, targetPath);
  } else if (e.dataTransfer?.files?.length) {
    uploadFiles([...e.dataTransfer.files], targetPath);
  }
}

function walkEntry(entry, prefix, out) {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((f) => { out.push({ file: f, rel: prefix + entry.name }); resolve(); }, () => resolve());
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const all = [];
      const read = () => {
        reader.readEntries(async (batch) => {
          if (!batch.length) {
            for (const en of all) await walkEntry(en, prefix + entry.name + '/', out);
            resolve();
          } else { all.push(...batch); read(); }
        }, () => resolve());
      };
      read();
    } else resolve();
  });
}

/* ============================ 灯箱 ============================ */
const LB = { items: [], i: 0, zoom: 1, x: 0, y: 0, drag: null };

function openLightbox(item) {
  const list = S.items.filter((i) => ['image', 'video', 'audio'].includes(i.kind));
  const i = list.findIndex((x) => x.path === item.path);
  if (i < 0) { toast('该类型暂不支持内置预览，双击可用系统程序打开'); return; }
  LB.items = list; LB.i = i; LB.zoom = 1; LB.x = LB.y = 0;
  $('#lightbox').hidden = false;
  renderLightbox();
}
function closeLightbox() {
  $('#lightbox').hidden = true;
  $('#lbStage').innerHTML = '';
}
function renderLightbox() {
  const it = LB.items[LB.i];
  if (!it) return closeLightbox();
  $('#lbName').textContent = `${it.name}　·　${LB.i + 1}/${LB.items.length}`;
  $('#lbFoot').innerHTML = `${esc(it.rel || '')} · ${fmtSize(it.size)}${it.w ? ` · ${it.w}×${it.h}` : ''}`;
  const stage = $('#lbStage');
  if (it.kind === 'image') {
    stage.innerHTML = `<img src="/api/file?p=${enc(it.path)}&v=${it.thumb_v || 0}" alt="" draggable="false">`;
    const img = $('img', stage);
    img.style.transform = 'translate(0,0) scale(1)';
    bindZoom(img);
  } else if (it.kind === 'video') {
    stage.innerHTML = `<video src="/api/file?p=${enc(it.path)}" controls autoplay playsinline></video>`;
  } else if (it.kind === 'audio') {
    stage.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;gap:18px">
      <img src="${thumbUrl(it, true)}" style="max-height:58vh;border-radius:16px" alt="">
      <audio src="/api/file?p=${enc(it.path)}" controls autoplay style="width:min(560px,70vw)"></audio></div>`;
  }
}
function bindZoom(img) {
  const apply = () => { img.style.transform = `translate(${LB.x}px,${LB.y}px) scale(${LB.zoom})`; };
  img.addEventListener('wheel', (e) => {
    e.preventDefault();
    LB.zoom = clamp(LB.zoom * (e.deltaY < 0 ? 1.12 : 0.89), 0.4, 8);
    apply();
  }, { passive: false });
  img.addEventListener('mousedown', (e) => {
    LB.drag = { x: e.clientX - LB.x, y: e.clientY - LB.y };
    img.style.cursor = 'grabbing';
  });
  const onMove = (e) => {
    if (!LB.drag) return;
    LB.x = e.clientX - LB.drag.x; LB.y = e.clientY - LB.drag.y; apply();
  };
  const onUp = () => {
    LB.drag = null; img.style.cursor = 'grab';
    window.removeEventListener('mousemove', onMove);
    window.removeEventListener('mouseup', onUp);
  };
  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', onUp);
  img.addEventListener('dblclick', () => { LB.zoom = 1; LB.x = LB.y = 0; apply(); });
}
function lbStep(d) {
  if (!LB.items.length) return;
  LB.i = (LB.i + d + LB.items.length) % LB.items.length;
  LB.zoom = 1; LB.x = LB.y = 0;
  renderLightbox();
}

/* ============================ 右键菜单 ============================ */
function showMenu(x, y, items) {
  const m = $('#ctxmenu');
  m.innerHTML = items.map((it) => it === '-' ? '<div class="ctx-sep"></div>'
    : `<div class="ctx-item ${it.danger ? 'danger' : ''}" data-k="${it.k}">${it.icon ? icon(it.icon) : ''}<span>${esc(it.label)}</span>${it.key ? `<span class="k">${it.key}</span>` : ''}</div>`).join('');
  m.hidden = false;
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(x, window.innerWidth - r.width - 8) + 'px';
  m.style.top = Math.min(y, window.innerHeight - r.height - 8) + 'px';
  $$('.ctx-item', m).forEach((el) => el.onclick = () => {
    const it = items.find((i) => i.k === el.dataset.k);
    m.hidden = true;
    it?.fn?.();
  });
}
function hideMenu() { $('#ctxmenu').hidden = true; }

function fileMenu(e, item) {
  const items = [
    { k: 'open', label: '用默认程序打开', icon: 'external', fn: () => openFile(item) },
    { k: 'preview', label: '在此预览', icon: 'maximize', fn: () => openLightbox(item) },
    { k: 'reveal', label: '在资源管理器中显示', icon: 'folder', fn: () => reveal(item.path) },
    '-',
    { k: 'copy', label: '复制路径', icon: 'copy', fn: () => copyText(item.path, '路径已复制') },
    { k: 'copyname', label: '复制文件名', icon: 'copy', fn: () => copyText(item.name, '文件名已复制') },
    {
      k: 'copyprompt', label: '复制提示词', icon: 'text', fn: async () => {
        const md = S.metaCache.get(item.path) || await apiGet('/api/meta', { p: item.path });
        S.metaCache.set(item.path, md);
        if (md.positive) copyText(md.positive, '提示词已复制'); else toast('这个文件没有提示词信息');
      }
    },
    '-',
    { k: 'fav', label: item.favorite ? '取消收藏' : '收藏', icon: 'star', fn: () => toggleFav(item) },
    { k: 'rename', label: '重命名', icon: 'edit', key: 'F2', fn: () => renamePath(item.path, item.name) },
    { k: 'delete', label: '删除', icon: 'trash', key: 'Del', danger: true, fn: () => deletePaths([item.path]) },
  ];
  if (S.sel.size > 1) {
    items.splice(0, 0, {
      k: 'batch', label: `删除选中的 ${S.sel.size} 项`, icon: 'trash', danger: true,
      fn: () => deletePaths([...S.sel]),
    });
  }
  showMenu(e.clientX, e.clientY, items);
}

function treeMenu(e, path) {
  const isRoot = path === S.project.root;
  showMenu(e.clientX, e.clientY, [
    { k: 'open', label: '打开此文件夹', icon: 'folder', fn: () => openFolder(path) },
    { k: 'reveal', label: '在资源管理器中打开', icon: 'external', fn: () => reveal(path) },
    { k: 'copy', label: '复制文件夹路径', icon: 'copy', fn: () => copyText(path, '路径已复制') },
    '-',
    { k: 'mkdir', label: '新建子文件夹', icon: 'plus', fn: () => newFolder(path) },
    ...(isRoot ? [] : [
      { k: 'rename', label: '重命名', icon: 'edit', fn: () => renamePath(path, path.split('\\').pop()) },
      { k: 'delete', label: '删除文件夹', icon: 'trash', danger: true, fn: () => deletePaths([path]) },
    ]),
  ]);
}

/* ============================ 弹窗 ============================ */
function modal(html, onBind) {
  const root = $('#modals');
  root.innerHTML = `<div class="modal">${html}</div>`;
  root.classList.add('on');
  onBind?.($('.modal', root));
  return root;
}
function closeModal() {
  $('#modals').classList.remove('on');
  $('#modals').innerHTML = '';
}

function promptDialog({ title, label, value = '', hint = '' }) {
  return new Promise((resolve) => {
    modal(`<div class="m-head"><h3>${esc(title)}</h3></div>
      <div class="m-body"><label class="m-label">${esc(label || '')}</label>
      <input class="m-input" id="mInput" value="${esc(value)}" spellcheck="false">
      ${hint ? `<div class="m-hint">${esc(hint)}</div>` : ''}</div>
      <div class="m-foot"><button class="btn" data-x>取消</button><button class="btn primary" data-ok>确定</button></div>`,
      (m) => {
        const inp = $('#mInput', m);
        inp.focus(); inp.select();
        const done = (v) => { closeModal(); resolve(v); };
        $('[data-ok]', m).onclick = () => done(inp.value.trim());
        $('[data-x]', m).onclick = () => done(null);
        inp.onkeydown = (e) => {
          if (e.key === 'Enter') done(inp.value.trim());
          if (e.key === 'Escape') done(null);
        };
      });
  });
}

function confirmDialog({ title, text, confirm = '确定', danger = false }) {
  return new Promise((resolve) => {
    modal(`<div class="m-head"><h3>${esc(title)}</h3></div>
      <div class="m-body"><p>${esc(text)}</p></div>
      <div class="m-foot"><button class="btn" data-x>取消</button>
      <button class="btn ${danger ? 'danger' : 'primary'}" data-ok>${esc(confirm)}</button></div>`,
      (m) => {
        $('[data-x]', m).onclick = () => { closeModal(); resolve(false); };
        $('[data-ok]', m).onclick = () => { closeModal(); resolve(true); };
      });
  });
}

function settingsDialog() {
  const s = S.settings;
  modal(`<div class="m-head"><h3>设置</h3></div>
    <div class="m-body">
      <div class="m-grid">
        <div class="m-field"><span>默认缩略图高度（像素）</span><input id="sTile" type="number" min="150" max="360" value="${s.tile || 220}"></div>
        <div class="m-field"><span>默认排序</span><select id="sSort">
          ${[['name_asc', '名称 A→Z'], ['mtime_desc', '最新优先'], ['mtime_asc', '最早优先'], ['size_desc', '体积从大到小']]
      .map(([v, l]) => `<option value="${v}" ${s.sort === v ? 'selected' : ''}>${l}</option>`).join('')}
        </select></div>
      </div>
      <div class="m-field" style="margin-top:10px"><span>FFmpeg 路径（可选，用于视频抽帧；留空自动查找）</span>
        <input id="sFfmpeg" value="${esc(s.ffmpeg || '')}" placeholder="C:\\ffmpeg\\bin\\ffmpeg.exe"></div>
      <div class="m-hint">没有 FFmpeg 时，应用会用浏览器解码视频并抓取首帧，同样能生成封面。</div>
      <div class="m-hint">数据目录：${esc(S.app.data_dir || '')}</div>
    </div>
    <div class="m-foot"><button class="btn" data-x>关闭</button><button class="btn primary" data-ok>保存</button></div>`,
    (m) => {
      $('[data-x]', m).onclick = closeModal;
      $('[data-ok]', m).onclick = async () => {
        try {
          const body = {
            tile: Number($('#sTile', m).value) || 220,
            sort: $('#sSort', m).value,
            ffmpeg: $('#sFfmpeg', m).value.trim(),
          };
          const r = await apiPost('/api/settings', body);
          S.settings = r;
          S.tile = body.tile; S.sort = body.sort;
          $('#tileRange').value = S.tile; $('#sort').value = S.sort;
          closeModal();
          rowSigs = [];
          await loadFiles(true);
          toast('设置已保存', 'ok', 1600);
        } catch (e) { toast(e.message, 'err'); }
      };
    });
}

/* ============================ 视图控制 ============================ */
function setView(v, reload = true) {
  S.view = v;
  LS.set('an.view', v);
  $$('.viewtoggle button').forEach((b) => b.classList.toggle('on', b.dataset.view === v));
  $('#rows').hidden = v !== 'grid';
  $('#listView').hidden = v !== 'list';
  rowSigs = [];
  if (reload) renderAll();
}

function bindChrome() {
  $('#btnSwitch').onclick = pickProject;
  $('#projectCard').ondblclick = pickProject;
  $('#wOpen').onclick = pickProject;
  $('#wDemo').onclick = async () => {
    try {
      const r = await apiPost('/api/project/demo', {});
      S.project = r.project; S.tree = r.tree;
      $('#welcome').hidden = true;
      setChromeEnabled(true);
      renderProject();
      await openFolder(S.tree.path);
      toast('示例项目已创建', 'ok', 2200);
    } catch (e) { toast(e.message, 'err'); }
  };

  $('#search').addEventListener('input', debounce((e) => { S.q = e.target.value.trim(); loadFiles(true); }, 240));
  $$('#kindSeg button').forEach((b) => b.onclick = () => {
    $$('#kindSeg button').forEach((x) => x.classList.toggle('on', x === b));
    S.kinds = b.dataset.kind ? [b.dataset.kind] : [];
    loadFiles(true);
  });
  $('#sort').onchange = (e) => { S.sort = e.target.value; loadFiles(true); };
  $('#recursive').onchange = (e) => { S.recursive = e.target.checked; loadFiles(true); };
  $('#tileRange').oninput = (e) => { S.tile = Number(e.target.value); };
  $('#tileRange').onchange = () => { rowSigs = []; renderGrid(); };
  $$('.viewtoggle button').forEach((b) => b.onclick = () => setView(b.dataset.view));

  $('#btnImport').onclick = openFilePicker;
  $('#emptyImport').onclick = openFilePicker;
  $('#btnNewFolder').onclick = newFolderHere;
  $('#btnExport').onclick = () => {
    const u = new URL('/api/export', location.origin);
    u.searchParams.set('folder', S.folder || S.project.root);
    u.searchParams.set('recursive', '1');
    location.href = u.toString();
  };
  $('#btnSettings').onclick = settingsDialog;
  $('#btnReload').onclick = async () => { await refreshTree(); await loadFiles(true); toast('已刷新', 'ok', 1200); };
  $('#btnQuit').onclick = async () => {
    const ok = await confirmDialog({ title: '退出 AssetNest', text: '关闭本地服务并退出程序。', confirm: '退出', danger: true });
    if (!ok) return;
    try { await apiPost('/api/quit', {}); } catch (e) { }
    setTimeout(() => { try { window.open('', '_self'); window.close(); } catch (e) { } }, 350);
  };

  const content = $('#content');
  content.addEventListener('scroll', () => {
    if (content.scrollTop + content.clientHeight > content.scrollHeight - 420 && S.shown < S.items.length) {
      S.shown = Math.min(S.items.length, S.shown + 160);
      renderAll();
    }
  });

  $('#rows').addEventListener('click', onCardClick);
  $('#listView').addEventListener('click', onCardClick);
  $('#rows').addEventListener('dblclick', onCardDblClick);
  $('#listView').addEventListener('dblclick', onCardDblClick);
  for (const sel of ['#rows', '#listView']) {
    $(sel).addEventListener('dragstart', onDragStart);
    $(sel).addEventListener('dragend', onDragEnd);
  }
  for (const sel of ['#rows', '#listView']) {
    $(sel).addEventListener('contextmenu', (e) => {
      const el = e.target.closest('.card, .lv-row');
      if (!el) return;
      e.preventDefault();
      const it = findItem(el.dataset.path);
      if (it) { if (!S.sel.has(it.path)) selectOnly(it.path); fileMenu(e, it); }
    });
  }

  $('#lbClose').onclick = closeLightbox;
  $('#lbPrev').onclick = () => lbStep(-1);
  $('#lbNext').onclick = () => lbStep(1);
  $('#lbReveal').onclick = () => reveal(LB.items[LB.i]?.path);
  $('#lbCopy').onclick = () => copyText(LB.items[LB.i]?.path || '', '路径已复制');
  $('#lightbox').addEventListener('click', (e) => {
    if (e.target.id === 'lightbox' || e.target.id === 'lbStage') closeLightbox();
  });
  $('#trClose').onclick = () => { $('#transfer').hidden = true; };

  window.addEventListener('click', (e) => { if (!$('#ctxmenu').contains(e.target)) hideMenu(); });
  window.addEventListener('keydown', onKey);
  window.addEventListener('resize', debounce(() => {
    if (S.view === 'grid' && S.items.length) { rowSigs = []; renderGrid(); }
  }, 160));
  if (window.ResizeObserver) {
    new ResizeObserver(debounce(() => {
      if (S.view === 'grid' && S.items.length) { rowSigs = []; renderGrid(); }
    }, 240)).observe(content);
  }

  bindDrag();
  dock.init();
  setInterval(pollRev, 2000);
}

/* ============================ 本地文件夹实时同步 ============================ */
let lastSyncToast = 0;

async function pollRev() {
  if (!S.project || document.hidden || S.importing || S.loading || dragDepth > 0) return;
  if ($('#modals').classList.contains('on') || !$('#ctxmenu').hidden) return;
  const ae = document.activeElement;
  if (ae && /INPUT|TEXTAREA/.test(ae.tagName)) return;
  try {
    const r = await apiGet('/api/rev');
    if (r.rev === S.rev) return;
    S.rev = r.rev;
    await syncFromDisk();
  } catch (e) { /* 项目可能被移动或删除 */ }
}

async function syncFromDisk() {
  if (!S.project) return;
  const active = S.active;
  const scroll = $('#content').scrollTop;
  try {
    const t = await apiGet('/api/tree');
    S.tree = t.tree;
    if (t.project) S.project = t.project;
    if (S.folder && S.folder !== S.tree.path && !findNode(S.tree, S.folder)) {
      S.folder = S.tree.path;
      S.recursive = true;
      S.sel.clear();
      S.active = null;
    }
    renderTree();
    $('#projectPath').textContent = S.project.root;
    await loadFiles(true);
  } catch (e) {
    return;
  }
  if (active && findItem(active)) {
    S.sel.add(active);
    S.active = active;
    paintSelection();
    if (!$('#dock').hidden) openDock(findItem(active));
  } else if (active) {
    closeDock();
  }
  $('#content').scrollTop = scroll;
  if (Date.now() - lastSyncToast > 8000) {
    lastSyncToast = Date.now();
    toast('已同步本地文件夹变化', 'ok', 1600);
  }
}

function onCardClick(e) {
  const star = e.target.closest('.card-star');
  const card = e.target.closest('.card, .lv-row');
  if (!card) return;
  const path = card.dataset.path;
  if (star) { e.stopPropagation(); const it = findItem(path); if (it) toggleFav(it); return; }
  if (e.ctrlKey || e.metaKey) { toggleSelect(path); return; }
  if (e.shiftKey && S.active) {
    const idxA = S.items.findIndex((i) => i.path === S.active);
    const idxB = S.items.findIndex((i) => i.path === path);
    if (idxA >= 0 && idxB >= 0) {
      const [a, b] = idxA < idxB ? [idxA, idxB] : [idxB, idxA];
      S.sel = new Set(S.items.slice(a, b + 1).map((i) => i.path));
      S.active = path;
      paintSelection();
      renderDockMulti();
      return;
    }
  }
  selectOnly(path);
}

function onCardDblClick(e) {
  const card = e.target.closest('.card, .lv-row');
  if (!card) return;
  const it = findItem(card.dataset.path);
  if (it) openFile(it);
}

function onKey(e) {
  const inField = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '');
  if (!$('#lightbox').hidden) {
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') lbStep(-1);
    if (e.key === 'ArrowRight') lbStep(1);
    return;
  }
  if (e.key === 'Escape') {
    if ($('#modals').classList.contains('on')) return closeModal();
    if (!$('#ctxmenu').hidden) return hideMenu();
    if (document.querySelector('.app').classList.contains('docked')) return closeDock();
    if (S.sel.size) { S.sel.clear(); S.active = null; paintSelection(); closeDock(); }
    return;
  }
  if (inField) return;
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'n') {
    e.preventDefault(); newFolderHere(); return;
  }
  if (e.key === '/') { e.preventDefault(); $('#search').focus(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
    e.preventDefault();
    S.sel = new Set(S.items.slice(0, S.shown).map((i) => i.path));
    paintSelection();
    if (S.sel.size > 1) renderDockMulti();
    return;
  }
  const it = S.active ? findItem(S.active) : null;
  if (!it) return;
  if (e.key === 'Enter') { e.preventDefault(); openFile(it); }
  else if (e.key === ' ') { e.preventDefault(); openLightbox(it); }
  else if (e.key === 'f' || e.key === 'F') { toggleFav(it); }
  else if (e.key === 'F2') { renamePath(it.path, it.name); }
  else if (e.key === 'Delete') { deletePaths(S.sel.size ? [...S.sel] : [it.path]); }
  else if (/^[1-5]$/.test(e.key)) { rate(it, Number(e.key)); }
  else if (['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp'].includes(e.key)) {
    const idx = S.items.findIndex((i) => i.path === it.path);
    if (idx < 0) return;
    const step = e.key === 'ArrowDown' ? 4 : e.key === 'ArrowUp' ? -4 : e.key === 'ArrowRight' ? 1 : -1;
    const next = S.items[clamp(idx + step, 0, S.items.length - 1)];
    if (next) selectOnly(next.path);
    e.preventDefault();
  }
}

/* ============================ 项目选择 ============================ */
async function pickProject() {
  try {
    toast('正在打开文件夹选择框…', '', 900);
    const r = await apiPost('/api/pick-folder', { title: '选择或新建项目文件夹' });
    if (r.path) { await openProject(r.path); return; }
    // 系统选择框不可用时，退回到手动输入路径
    const typed = await promptDialog({
      title: '打开项目文件夹',
      label: '文件夹完整路径',
      value: 'D:\\',
      hint: '例如 D:\\项目\\雨夜归途。路径不存在时会提示；已存在的文件夹会自动补建七个分类目录。',
    });
    if (typed) await openProject(typed);
  } catch (e) { toast(e.message, 'err', 3200); }
}

/* ============================ 启动 ============================ */
boot().catch((e) => {
  console.error(e);
  toast('启动失败：' + e.message, 'err', 6000);
});
window.S = S;
