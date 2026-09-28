/* Qualys Portal Hub - shared page logic.
 *
 * Data lives in CSV files so links can be edited straight from GitHub:
 *   modules.csv        one row per module tab (drives the sidebar, the dashboard grid and each module header)
 *   links/<id>.csv     title,link,category - the resource library for one module
 *   links/public.csv   title,link,category - public Qualys links shown on the dashboard
 *   links/whats-new.csv  week,published,module,title,link,category,source - appended by the weekly GitHub Action
 *
 * A module page only needs <body data-module="<id>">; everything else is rendered from the CSVs.
 */

const PLATFORM_LOGIN = 'https://qualysguard.qualys.com';
const COLLAPSE_AFTER = 12;

// ---------- helpers ----------

// RFC 4180 CSV parser: handles quoted fields, commas and quotes inside quotes, CRLF.
function parseCSV(text) {
    const rows = [];
    let row = [], field = '', inQuotes = false;
    text = text.replace(/^﻿/, '');
    for (let i = 0; i < text.length; i++) {
        const c = text[i];
        if (inQuotes) {
            if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
            else if (c === '"') inQuotes = false;
            else field += c;
        } else if (c === '"') inQuotes = true;
        else if (c === ',') { row.push(field); field = ''; }
        else if (c === '\n' || c === '\r') {
            if (c === '\r' && text[i + 1] === '\n') i++;
            row.push(field); rows.push(row); row = []; field = '';
        } else field += c;
    }
    if (field !== '' || row.length) { row.push(field); rows.push(row); }
    const nonEmpty = rows.filter(r => r.some(v => v.trim() !== ''));
    if (!nonEmpty.length) return [];
    const header = nonEmpty[0].map(h => h.trim().toLowerCase());
    return nonEmpty.slice(1).map(r => Object.fromEntries(header.map((h, i) => [h, (r[i] || '').trim()])));
}

async function loadCSV(path) {
    const res = await fetch(path, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
    return parseCSV(await res.text());
}

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const safeUrl = u => /^https?:\/\//i.test(u) ? u : '#';
const byTitle = (a, b) => a.title.localeCompare(b.title, undefined, { numeric: true, sensitivity: 'base' });

// ---------- sidebar ----------

function renderSidebar(modules, current) {
    const aside = document.getElementById('global-sidebar');
    const link = (href, icon, label, active) => `
        <a href="${esc(href)}" class="nav-item flex items-center gap-3 px-6 py-2.5 font-bold text-slate-600 hover:bg-slate-50 border-l-4 border-transparent transition-all${active ? ' active' : ''}">
            <i class="fa-solid ${esc(icon)} fa-fw text-center"></i> ${esc(label)}
        </a>`;
    let html = `<nav class="space-y-0.5">
        <p class="px-6 mb-2 text-[10px] font-black text-slate-400 uppercase tracking-widest">Main</p>
        ${link('index.html', 'fa-house', 'Dashboard', current === 'index')}
        ${link('whats-new.html', 'fa-bolt', "What's New", current === 'whats-new')}`;
    const groups = [...new Set(modules.map(m => m.group))];
    for (const g of groups) {
        html += `<p class="px-6 mt-6 mb-2 text-[10px] font-black text-slate-400 uppercase tracking-widest">${esc(g)}</p>`;
        for (const m of modules.filter(x => x.group === g)) html += link(`${m.id}.html`, m.icon, m.name, m.id === current);
    }
    aside.innerHTML = html + '</nav>';
    aside.querySelector('.nav-item.active')?.scrollIntoView({ block: 'center' });
}

// ---------- quick-access tiles ----------

function quickTile(href, icon, color, title, sub) {
    return `
        <a href="${esc(safeUrl(href))}" target="_blank" rel="noopener" class="tile-card p-6 rounded-3xl flex items-center gap-5 group">
            <div class="h-12 w-12 bg-${color}-50 rounded-2xl flex items-center justify-center text-${color}-500 text-xl group-hover:bg-${color}-600 group-hover:text-white transition-all shrink-0">
                <i class="fa-solid ${icon}"></i>
            </div>
            <div>
                <h3 class="font-bold text-slate-800">${esc(title)}</h3>
                <p class="text-slate-500 text-[11px] font-semibold">${esc(sub)}</p>
            </div>
        </a>`;
}

// ---------- resource library (search + pills + category cards) ----------

function renderLibrary(rows, { grid, pills, search }) {
    const data = {};
    rows.forEach(r => {
        if (!r.title || !r.link) return;
        const cat = r.category || 'General';
        (data[cat] = data[cat] || []).push(r);
    });

    grid.innerHTML = '';
    pills.innerHTML = `<button data-cat="All" class="pill-active px-6 py-2 rounded-full text-[11px] font-black uppercase tracking-widest border border-blue-300 bg-white text-slate-600 shadow-sm transition-all">All</button>`;

    Object.keys(data).sort((a, b) => a.localeCompare(b)).forEach(cat => {
        pills.innerHTML += `<button data-cat="${esc(cat)}" class="px-6 py-2 rounded-full text-[11px] font-black uppercase tracking-widest border border-blue-300 bg-white text-slate-600 hover:border-blue-500 shadow-sm transition-all whitespace-nowrap">${esc(cat)}</button>`;

        const items = data[cat].sort(byTitle);
        const lis = items.map((item, i) => `
            <li class="${i >= COLLAPSE_AFTER ? 'overflow-item hidden' : ''}">
                <a href="${esc(safeUrl(item.link))}" target="_blank" rel="noopener" class="article-item flex items-start gap-3 group">
                    <div class="h-6 w-6 rounded bg-slate-50 flex items-center justify-center shrink-0 group-hover:bg-red-50 transition-colors">
                        <i class="fa-regular fa-file-lines text-slate-400 group-hover:text-red-500 text-xs transition-colors"></i>
                    </div>
                    <span class="text-[13px] font-medium text-slate-700 group-hover:text-slate-900 leading-tight transition-colors">${esc(item.title)}</span>
                </a>
            </li>`).join('');
        const more = items.length > COLLAPSE_AFTER
            ? `<button class="show-more mt-5 self-start text-[11px] font-black uppercase tracking-widest text-blue-700 hover:text-red-600">Show all ${items.length} <i class="fa-solid fa-chevron-down text-[9px]"></i></button>`
            : '';
        grid.insertAdjacentHTML('beforeend', `
            <div class="category-card tile-card rounded-[2rem] p-8 flex flex-col" data-category="${esc(cat)}">
                <div class="flex items-center justify-between mb-6">
                    <h3 class="font-black text-slate-900 text-[12px] uppercase tracking-[0.25em] flex items-center gap-2">
                        <i class="fa-solid fa-folder-tree text-blue-500"></i> ${esc(cat)}
                    </h3>
                    <span class="text-[11px] bg-blue-100 px-3 py-1 rounded-full text-blue-800 font-black border border-blue-200">${items.length}</span>
                </div>
                <ul class="space-y-4 flex-1">${lis}</ul>
                ${more}
            </div>`);
    });

    grid.onclick = e => {
        const btn = e.target.closest('.show-more');
        if (!btn) return;
        const card = btn.closest('.category-card');
        const open = card.classList.toggle('expanded');
        card.querySelectorAll('.overflow-item').forEach(li => li.classList.toggle('hidden', !open));
        btn.innerHTML = open ? 'Show less <i class="fa-solid fa-chevron-up text-[9px]"></i>'
                             : `Show all ${card.querySelectorAll('li').length} <i class="fa-solid fa-chevron-down text-[9px]"></i>`;
    };

    pills.onclick = e => {
        const btn = e.target.closest('button');
        if (!btn) return;
        pills.querySelectorAll('button').forEach(b => b.classList.remove('pill-active'));
        btn.classList.add('pill-active');
        search.value = '';
        applySearch(grid, '');
        grid.querySelectorAll('.category-card').forEach(card => {
            card.style.display = (btn.dataset.cat === 'All' || card.dataset.category === btn.dataset.cat) ? 'flex' : 'none';
        });
    };

    search.oninput = e => {
        pills.querySelectorAll('button').forEach((b, i) => b.classList.toggle('pill-active', i === 0));
        applySearch(grid, e.target.value.toLowerCase().trim());
    };
}

function applySearch(grid, term) {
    grid.querySelectorAll('.category-card').forEach(card => {
        let visible = 0;
        card.querySelectorAll('li').forEach((li, i) => {
            const match = !term || li.innerText.toLowerCase().includes(term);
            // While searching, show every match; otherwise respect the collapsed/expanded state.
            const collapsed = !term && i >= COLLAPSE_AFTER && !card.classList.contains('expanded');
            li.classList.toggle('hidden', !match || collapsed);
            if (match) visible++;
        });
        const more = card.querySelector('.show-more');
        if (more) more.style.display = term ? 'none' : '';
        card.style.display = visible ? 'flex' : 'none';
    });
}

// ---------- pages ----------

async function initModulePage(modules, id) {
    const m = modules.find(x => x.id === id);
    const main = document.getElementById('module-root');
    if (!m) { main.innerHTML = `<p class="text-red-600">Unknown module "${esc(id)}". Add it to modules.csv.</p>`; return; }
    document.title = `${m.name} | Qualys Hub`;

    const tiles = [quickTile(PLATFORM_LOGIN, 'fa-right-to-bracket', 'red', 'Platform Login', 'Cloud Console')];
    if (m.docs) tiles.push(quickTile(m.docs, 'fa-book', 'blue', 'User Guides', 'Technical Docs'));
    if (m.api) tiles.push(quickTile(m.api, 'fa-code', 'purple', 'API Center', 'Automation'));
    if (m.release_notes) tiles.push(quickTile(m.release_notes, 'fa-clipboard-list', 'amber', 'Release Notes', "What's New"));
    else if (m.product) tiles.push(quickTile(m.product, 'fa-cube', 'amber', 'Product Page', 'qualys.com'));

    main.innerHTML = `
        <header class="mb-10">
            <h2 class="text-4xl font-black text-slate-900 tracking-tight">${esc(m.name)} Resource Library</h2>
            <p class="text-slate-700 mt-2 font-medium opacity-80">${esc(m.full_name)} &mdash; centralized documentation and quick-access tools.</p>
        </header>
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6 mb-12">${tiles.join('')}</div>
        <div class="mb-8 space-y-5">
            <div class="relative max-w-md">
                <i class="fa-solid fa-magnifying-glass absolute left-4 top-1/2 -translate-y-1/2 text-slate-400"></i>
                <input type="text" id="articleSearch" placeholder="Search resources..."
                       class="w-full pl-11 pr-4 py-4 rounded-2xl border border-blue-200 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/20 shadow-inner outline-none transition-all">
            </div>
            <div id="category-pills" class="flex gap-2 overflow-x-auto pb-2 no-scrollbar"></div>
        </div>
        <div id="article-grid" class="grid grid-cols-1 lg:grid-cols-2 gap-8 pb-24"></div>`;

    const grid = document.getElementById('article-grid');
    try {
        const rows = await loadCSV(`links/${m.id}.csv`);
        renderLibrary(rows, { grid, pills: document.getElementById('category-pills'), search: document.getElementById('articleSearch') });
    } catch (err) {
        grid.innerHTML = `<div class="col-span-full p-12 text-center text-red-500 bg-white rounded-3xl border border-red-200">Error: could not load <b>links/${esc(m.id)}.csv</b>. (${esc(err.message)})</div>`;
    }
}

async function initDashboard(modules) {
    // Module grid
    const mg = document.getElementById('module-grid');
    const groups = [...new Set(modules.map(m => m.group))];
    mg.innerHTML = groups.map(g => `
        <div class="mb-8">
            <h3 class="font-black text-slate-900 text-[12px] uppercase tracking-[0.25em] mb-4">${esc(g)}</h3>
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                ${modules.filter(m => m.group === g).map(m => `
                <a href="${esc(m.id)}.html" class="tile-card p-5 rounded-2xl flex items-center gap-4 group">
                    <div class="h-11 w-11 bg-blue-50 rounded-xl flex items-center justify-center text-blue-600 group-hover:bg-blue-600 group-hover:text-white transition-all shrink-0">
                        <i class="fa-solid ${esc(m.icon)}"></i>
                    </div>
                    <div class="min-w-0">
                        <h4 class="font-bold text-slate-800 group-hover:text-red-600 transition-colors">${esc(m.name)}</h4>
                        <p class="text-slate-500 text-[11px] font-semibold truncate">${esc(m.full_name)}</p>
                    </div>
                </a>`).join('')}
            </div>
        </div>`).join('');

    // Public link library + search across every module
    const grid = document.getElementById('article-grid');
    const pills = document.getElementById('category-pills');
    const search = document.getElementById('articleSearch');
    let publicRows = [];
    try {
        publicRows = await loadCSV('links/public.csv');
        renderLibrary(publicRows, { grid, pills, search });
    } catch (err) {
        grid.innerHTML = `<div class="col-span-full p-12 text-center text-red-500 bg-white rounded-3xl border border-red-200">Error: could not load <b>links/public.csv</b>. (${esc(err.message)})</div>`;
    }

    const scope = document.getElementById('search-scope');
    let everything = null;
    scope.onchange = async () => {
        if (scope.value === 'all') {
            if (!everything) {
                scope.disabled = true;
                const sets = await Promise.all(modules.map(m => loadCSV(`links/${m.id}.csv`)
                    .then(rows => rows.map(r => ({ ...r, category: m.name })))
                    .catch(() => [])));
                everything = publicRows.map(r => ({ ...r, category: `Public: ${r.category}` })).concat(...sets);
                scope.disabled = false;
            }
            renderLibrary(everything, { grid, pills, search });
            document.getElementById('library-title').textContent = 'Search Every Module';
        } else {
            renderLibrary(publicRows, { grid, pills, search });
            document.getElementById('library-title').textContent = 'Public Qualys Resources';
        }
        search.dispatchEvent(new Event('input'));
    };
}

// ---------- what's new ----------

const SOURCE_STYLE = {
    'Qualys Blog': ['fa-newspaper', 'amber'],
    'Qualys Notifications': ['fa-bell', 'orange'],
    'Qualys Newsletters': ['fa-envelope-open-text', 'cyan'],
    'ThreatPROTECT': ['fa-skull-crossbones', 'rose'],
};
const fmtDate = iso => iso ? new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '';

async function initWhatsNew(modules) {
    const main = document.getElementById('module-root');
    main.innerHTML = `
        <header class="mb-10">
            <h2 class="text-4xl font-black text-slate-900 tracking-tight">What's New</h2>
            <p class="text-slate-700 mt-2 font-medium opacity-80">Links added by the weekly refresh (blog, notifications, newsletters and ThreatPROTECT).</p>
        </header>
        <div class="flex flex-col sm:flex-row gap-3 mb-8 max-w-2xl">
            <select id="week-picker" class="px-4 py-4 rounded-2xl border border-blue-200 bg-white font-bold text-slate-700 outline-none focus:border-blue-500"></select>
            <div class="relative flex-1">
                <i class="fa-solid fa-magnifying-glass absolute left-4 top-1/2 -translate-y-1/2 text-slate-400"></i>
                <input type="text" id="articleSearch" placeholder="Filter this week..."
                       class="w-full pl-11 pr-4 py-4 rounded-2xl border border-blue-200 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/20 shadow-inner outline-none transition-all">
            </div>
        </div>
        <div id="wn-stats" class="grid grid-cols-2 xl:grid-cols-4 gap-6 mb-10"></div>
        <div id="article-grid" class="grid grid-cols-1 lg:grid-cols-2 gap-8 pb-24"></div>`;

    const grid = document.getElementById('article-grid');
    let rows;
    try { rows = (await loadCSV('links/whats-new.csv')).filter(r => r.week && r.title && r.link); }
    catch { rows = []; }
    if (!rows.length) {
        grid.innerHTML = `<div class="col-span-full p-12 text-center text-slate-500 bg-white rounded-3xl border border-blue-200">Nothing yet. The weekly refresh runs every Saturday.</div>`;
        return;
    }

    const byId = Object.fromEntries(modules.map(m => [m.id, m]));
    const groupInfo = id => id === 'public' ? { name: 'Public Resources', icon: 'fa-globe', href: 'index.html' }
        : id === 'threatprotect' ? { name: 'ThreatPROTECT Advisories', icon: 'fa-skull-crossbones', href: 'https://threatprotect.qualys.com/' }
        : byId[id] ? { name: byId[id].name, icon: byId[id].icon, href: `${id}.html` }
        : { name: id, icon: 'fa-folder', href: '#' };
    // Modules in sidebar order, then public, then ThreatPROTECT.
    const order = id => id === 'threatprotect' ? 1e6 : id === 'public' ? 1e6 - 1 : (modules.findIndex(m => m.id === id) + 1 || 1e5);

    const weeks = [...new Set(rows.map(r => r.week))].sort().reverse();
    const picker = document.getElementById('week-picker');
    picker.innerHTML = weeks.map((w, i) => `<option value="${esc(w)}">${i === 0 ? 'Latest: ' : ''}Week of ${esc(fmtDate(w))}</option>`).join('');

    const render = () => {
        const week = rows.filter(r => r.week === picker.value);
        const count = src => new Set(week.filter(r => r.source === src).map(r => r.link)).size;
        // Unique links, so a post filed under three modules counts once.
        const unique = new Set(week.map(r => r.link)).size;
        const stat = (icon, color, n, label) => `
            <div class="tile-card p-6 rounded-3xl flex items-center gap-5">
                <div class="h-12 w-12 bg-${color}-50 rounded-2xl flex items-center justify-center text-${color}-500 text-xl shrink-0"><i class="fa-solid ${icon}"></i></div>
                <div><p class="text-2xl font-black text-slate-900">${n}</p><p class="text-slate-500 text-[11px] font-semibold uppercase tracking-widest">${esc(label)}</p></div>
            </div>`;
        document.getElementById('wn-stats').innerHTML =
            stat('fa-bolt', 'blue', unique, 'New links') +
            stat('fa-newspaper', 'amber', count('Qualys Blog'), 'Blog posts') +
            stat('fa-bell', 'orange', count('Qualys Notifications') + count('Qualys Newsletters'), 'Notifications') +
            stat('fa-skull-crossbones', 'rose', count('ThreatPROTECT'), 'Advisories');

        const groups = {};
        week.forEach(r => (groups[r.module] = groups[r.module] || []).push(r));
        grid.innerHTML = Object.keys(groups).sort((a, b) => order(a) - order(b)).map(id => {
            const g = groupInfo(id);
            const items = groups[id].sort((a, b) => (b.published || '').localeCompare(a.published || '') || byTitle(a, b));
            const ext = /^https?:/.test(g.href) ? ' target="_blank" rel="noopener"' : '';
            return `
            <div class="category-card tile-card rounded-[2rem] p-8 flex flex-col" data-category="${esc(id)}">
                <div class="flex items-center justify-between mb-6">
                    <a href="${esc(g.href)}"${ext} class="font-black text-slate-900 hover:text-red-600 text-[12px] uppercase tracking-[0.25em] flex items-center gap-2">
                        <i class="fa-solid ${esc(g.icon)} text-blue-500"></i> ${esc(g.name)}
                    </a>
                    <span class="text-[11px] bg-blue-100 px-3 py-1 rounded-full text-blue-800 font-black border border-blue-200">${items.length}</span>
                </div>
                <ul class="space-y-4 flex-1">${items.map(item => {
                    const [icon, color] = SOURCE_STYLE[item.source] || ['fa-file-lines', 'slate'];
                    return `
                    <li>
                        <a href="${esc(safeUrl(item.link))}" target="_blank" rel="noopener" class="article-item flex items-start gap-3 group">
                            <div class="h-6 w-6 rounded bg-${color}-50 flex items-center justify-center shrink-0">
                                <i class="fa-solid ${icon} text-${color}-500 text-xs"></i>
                            </div>
                            <div class="min-w-0">
                                <span class="block text-[13px] font-medium text-slate-700 group-hover:text-slate-900 leading-tight transition-colors">${esc(item.title)}</span>
                                <span class="block mt-1 text-[11px] font-semibold text-slate-400">${esc(item.category)}${item.published ? ` &middot; ${esc(fmtDate(item.published))}` : ''}</span>
                            </div>
                        </a>
                    </li>`;
                }).join('')}</ul>
            </div>`;
        }).join('');
        applySearch(grid, document.getElementById('articleSearch').value.toLowerCase().trim());
    };

    picker.onchange = render;
    document.getElementById('articleSearch').oninput = e => applySearch(grid, e.target.value.toLowerCase().trim());
    render();
}

// Dashboard banner pointing at the latest weekly refresh.
async function renderWhatsNewBanner() {
    const el = document.getElementById('whats-new-banner');
    if (!el) return;
    let rows;
    try { rows = (await loadCSV('links/whats-new.csv')).filter(r => r.week); } catch { return; }
    if (!rows.length) return;
    const latest = rows.reduce((m, r) => r.week > m ? r.week : m, '');
    const n = new Set(rows.filter(r => r.week === latest).map(r => r.link)).size;
    el.innerHTML = `
        <a href="whats-new.html" class="tile-card p-5 rounded-2xl flex items-center gap-4 group mb-10">
            <div class="h-11 w-11 bg-red-50 rounded-xl flex items-center justify-center text-red-500 group-hover:bg-red-600 group-hover:text-white transition-all shrink-0">
                <i class="fa-solid fa-bolt"></i>
            </div>
            <div class="flex-1 min-w-0">
                <h4 class="font-bold text-slate-800 group-hover:text-red-600 transition-colors">${n} new link${n === 1 ? '' : 's'} this week</h4>
                <p class="text-slate-500 text-[11px] font-semibold">Weekly refresh of ${esc(fmtDate(latest))} &mdash; see what's new</p>
            </div>
            <i class="fa-solid fa-chevron-right text-slate-400 group-hover:text-red-600"></i>
        </a>`;
}

// ---------- boot ----------

(async function boot() {
    document.getElementById('nav-toggle')?.addEventListener('click', () => document.body.classList.toggle('nav-open'));
    const current = document.body.dataset.module || 'index';
    let modules = [];
    try { modules = (await loadCSV('modules.csv')).filter(m => m.id); }
    catch (err) { document.getElementById('global-sidebar').innerHTML = `<p class="px-6 text-red-600 text-xs">modules.csv not found</p>`; }
    renderSidebar(modules, current);
    if (current === 'index') { initDashboard(modules); renderWhatsNewBanner(); }
    else if (current === 'whats-new') initWhatsNew(modules);
    else initModulePage(modules, current);
})();
