document.addEventListener('DOMContentLoaded', () => { App.init(); GlobalRuns.startPolling(); Theme.init(); QueueStatus.reconnect(); });

// ─── Date helpers ────────────────────────────────
function _dateKey(dateVal) {
    if (!dateVal) return '';
    const d = new Date(typeof dateVal === 'string' && dateVal.includes(' ') ? dateVal.replace(' ', 'T') + 'Z' : dateVal);
    return isNaN(d) ? '' : d.toISOString().substring(0, 10);
}
function _dateHeader(key) {
    const today = new Date().toISOString().substring(0, 10);
    const yesterday = new Date(Date.now() - 864e5).toISOString().substring(0, 10);
    if (key === today) return 'Today';
    if (key === yesterday) return 'Yesterday';
    return new Date(key + 'T12:00:00Z').toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' });
}
function _fmtTime(dateVal) {
    const d = new Date(typeof dateVal === 'string' && dateVal.includes(' ') ? dateVal.replace(' ', 'T') + 'Z' : dateVal);
    return isNaN(d) ? '' : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: true });
}
function _fmtDateTime(dateVal) {
    const d = new Date(typeof dateVal === 'string' && dateVal.includes(' ') ? dateVal.replace(' ', 'T') + 'Z' : dateVal);
    if (isNaN(d)) return '';
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' +
        d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: true });
}

// Mirror of backend inferSection — used to group legacy tests that don't have
// section saved yet, and to suggest sections in the create/edit modal.
const SECTION_OPTIONS = [
    'Homepage', 'Header / Nav', 'Search', 'PLP', 'PDP',
    'Cart', 'Mini Cart', 'Checkout', 'Orders',
    'Account', 'Wishlist', 'Compare', 'Newsletter', 'Coupons',
    'Footer', 'Contact', 'SEO / Meta', 'Responsive',
    'Accessibility', 'Security', 'Performance', 'Errors / Logs', 'General',
];

function _inferSection(name) {
    const n = String(name || '').toLowerCase();
    // IMPORTANT: Order matters! More specific patterns must come before less specific ones.
    // e.g., 'Mini Cart' before 'Cart', 'Checkout' before 'Cart'
    const rules = [
        [/\b(homepage|home page|home\b|landing)\b|\bpage loads\b/, 'Homepage'],
        [/\bmini ?cart\b|\bminicart\b/, 'Mini Cart'],
        [/\bcheckout\b|\bplace order\b|\bshipping (?:method|info)\b|\bpayment method\b/, 'Checkout'],
        [/\bcart\b|\badd to cart\b|\bcart counter\b/, 'Cart'],
        [/\b(pdp|product detail|product page)\b/, 'PDP'],
        [/\b(plp|category page|product list|listing|collection)\b/, 'PLP'],
        [/\bsearch\b|\bsearch bar\b/, 'Search'],
        [/\bwishlist\b|\bfavou?rite\b/, 'Wishlist'],
        [/\bcompare\b/, 'Compare'],
        [/\bnewsletter\b|\bsubscribe\b/, 'Newsletter'],
        [/\baccount\b|\bregister\b|\bsign[- ]?up\b|\blog ?in\b|\bsign[- ]?in\b|\bmy profile\b/, 'Account'],
        [/\border\b|\border confirmation\b|\border history\b/, 'Orders'],
        [/\bfooter\b/, 'Footer'],
        [/\bheader\b|\btop bar\b|\bnavigation\b|\bnav\s+menu\b/, 'Header / Nav'],
        [/\bcontact\b|\bcontact us\b|\bsupport\b/, 'Contact'],
        [/\bcoupon\b|\bdiscount\b|\bpromo\b/, 'Coupons'],
        [/\b(meta description|page title|viewport|favicon|alt text|seo)\b/, 'SEO / Meta'],
        [/\bresponsive\b|\bmobile view\b|\btablet\b/, 'Responsive'],
        [/\baccessibility\b|\baria\b/, 'Accessibility'],
        [/\bsecurity\b|\bxss\b|\bsql\b|\bcsrf\b/, 'Security'],
        [/\b(performance|web vitals|core web vitals|lcp|cls|fcp)\b/, 'Performance'],
        [/\bconsole error\b|\bjs error\b|\bbroken link\b/, 'Errors / Logs'],
    ];
    for (const [re, section] of rules) {
        if (re.test(n)) return section;
    }
    return 'General';
}

// Lightbox: delegate click on any result screenshot
document.addEventListener('click', (e) => {
    const img = e.target.closest('.result-step-screenshot img');
    if (img) {
        e.preventDefault();
        e.stopPropagation();
        const lb = document.getElementById('lightbox');
        document.getElementById('lightbox-img').src = img.src;
        lb.style.display = 'flex';
    }
});

// ─────────────────────────────────────────────
// APP — hash-based routing
// ─────────────────────────────────────────────
const App = {
    currentPage: null,

    init() {
        window.addEventListener('hashchange', () => this._route());
        this._refreshProjectCount();
        // Restore active run if any
        if (sessionStorage.getItem('activeRun')) {
            Workspace._restoreActiveRun();
        }
        this._route();
    },

    async _refreshProjectCount() {
        try {
            const res = await Api.getProjects();
            const badge = document.getElementById('sidebar-project-count');
            if (badge) badge.textContent = (res.data || []).length > 0 ? (res.data || []).length : '';
        } catch (e) { /* ignore */ }
    },

    navigate(page, id, sub) {
        let hash = '#' + page;
        if (id) hash += '/' + id;
        if (sub) hash += '/' + sub;
        window.location.hash = hash;
    },

    _route() {
        const hash = (window.location.hash || '#dashboard').substring(1);
        const parts = hash.split('/');
        const page = parts[0] || 'dashboard';
        const id = parts[1] || null;
        const sub = parts.slice(2).join('/') || null;

        // Update sidebar
        document.querySelectorAll('.sidebar-link').forEach(l => l.classList.remove('active'));
        const activeLink = document.querySelector(`.sidebar-link[data-page="${page === 'workspace' ? 'projects' : page}"]`);
        if (activeLink) activeLink.classList.add('active');

        // Update topbar title
        const titles = { dashboard: 'Dashboard', projects: 'Projects', workspace: 'Workspace', results: 'Test Results', help: 'Help & Resources', settings: 'Settings' };
        document.getElementById('topbar-title').textContent = titles[page] || page;

        // Show page
        document.querySelectorAll('.page-section').forEach(s => s.style.display = 'none');

        // Determine which section to show
        let sectionId = 'page-' + page;
        if (page === 'result') sectionId = 'page-result-detail';
        if (page === 'workspace' && sub && sub.startsWith('result/')) sectionId = 'page-result-detail';

        const section = document.getElementById(sectionId);
        if (section) section.style.display = 'block';

        // Load page data
        if (page === 'dashboard') Dashboard.load();
        else if (page === 'projects') Projects.load();
        else if (page === 'workspace' && sub && sub.startsWith('result/')) {
            Workspace.projectId = id; // keep project context
            ResultDetail.load(sub.replace('result/', ''), id);
        }
        else if (page === 'workspace' && id) Workspace.load(id, sub);
        else if (page === 'results') Results.load();
        else if (page === 'result' && id) ResultDetail.load(id);
        else if (page === 'help') { /* static content, no load needed */ }
        else if (page === 'settings') Config.load();

        this.currentPage = page;
    },
};

// ─────────────────────────────────────────────
// DASHBOARD — overview page
// ─────────────────────────────────────────────
const Dashboard = {
    async load() {
        try {
            const [dashRes, projRes] = await Promise.all([
                Api.getDashboard(),
                Api.getProjects(),
            ]);
            const d = dashRes.data;
            document.getElementById('ds-projects').textContent = d.total_projects;
            document.getElementById('ds-cases').textContent = d.total_test_cases;
            document.getElementById('ds-passrate').textContent = d.pass_rate + '%';
            document.getElementById('ds-passrate').style.color = d.pass_rate >= 70 ? 'var(--success)' : 'var(--danger)';
            document.getElementById('ds-failures').textContent = d.total_failed;
            document.getElementById('ds-passrate-sub').innerHTML = `<span class="green">${d.total_passed} passed</span> of ${d.total_executed}`;
            document.getElementById('ds-failures-sub').innerHTML = `<span class="red">${d.total_blocked} blocked</span>`;

            // Update sidebar badge
            const badge = document.getElementById('sidebar-project-count');
            if (badge) badge.textContent = d.total_projects != null ? d.total_projects : '';

            // Recent runs
            this._renderRecent(d.recent_results || []);
            // Projects health
            this._renderHealth(projRes.data || []);
        } catch (e) {
            document.getElementById('dash-recent-runs').innerHTML = `<div class="empty-state-sm">Failed to load: ${e.message}</div>`;
        }
    },

    _renderRecent(results) {
        const el = document.getElementById('dash-recent-runs');
        if (!results.length) { el.innerHTML = '<div class="empty-state-sm">No test runs yet</div>'; return; }
        el.innerHTML = `<table class="mini-table"><thead><tr><th>Test</th><th>Status</th><th>Date</th></tr></thead><tbody>
            ${results.map(r => {
                const statusText = (r.status || (r.failed > 0 ? 'fail' : 'pass')).toUpperCase();
                const statusCls = r.status || (r.failed > 0 ? 'fail' : 'pass');
                const viewId = r.filename || r.id || '';
                return `<tr style="cursor:pointer" onclick="App.navigate('result','${esc(viewId)}')"><td>${esc(r.title || r.filename)}</td><td><span class="status-pill ${statusCls}">${statusText}</span></td><td style="color:var(--text-muted)">${esc(r.date || '')}</td></tr>`;
            }).join('')}
        </tbody></table>`;
    },

    _renderHealth(projects) {
        const el = document.getElementById('dash-projects-health');
        if (!projects.length) { el.innerHTML = '<div class="empty-state-sm">No projects yet</div>'; return; }
        el.innerHTML = projects.map(p => {
            const total = (p.recentPassed || 0) + (p.recentFailed || 0) + (p.recentBlocked || 0);
            const passW = total > 0 ? (p.recentPassed / total * 100) : 0;
            return `<div style="padding:8px 4px;border-bottom:1px solid var(--border);cursor:pointer" onclick="App.navigate('workspace','${p._id}')">
                <div style="display:flex;justify-content:space-between;margin-bottom:4px">
                    <span style="font-size:13px;font-weight:600;color:var(--text)">${esc(p.name)}</span>
                    <span style="font-size:12px;color:var(--text-muted)">${total > 0 ? Math.round(passW) + '% pass' : 'no runs'}</span>
                </div>
                <div style="display:flex;height:4px;border-radius:2px;overflow:hidden;background:var(--border)">
                    <div style="width:${passW}%;background:var(--success)"></div>
                    <div style="width:${total > 0 ? (p.recentFailed / total * 100) : 0}%;background:var(--danger)"></div>
                </div>
            </div>`;
        }).join('');
    },
};

// ─────────────────────────────────────────────
// PROJECTS
// ─────────────────────────────────────────────
const Projects = {
    async load() {
        const grid = document.getElementById('projects-grid');
        grid.innerHTML = '<div class="empty-state-sm">Loading projects...</div>';
        try {
            const { data } = await Api.getProjects();
            if (!data.length) {
                grid.innerHTML = '<div class="empty-state-sm">No projects yet. Click <strong>+ New Project</strong> to get started.</div>';
            } else {
                grid.innerHTML = data.map(p => this._card(p)).join('');
            }
        } catch (e) {
            grid.innerHTML = `<div class="empty-state-sm" style="color:var(--danger)">Failed: ${e.message}</div>`;
        }
    },

    _card(p) {
        const passed = p.recentPassed || 0, failed = p.recentFailed || 0, blocked = p.recentBlocked || 0;
        const total = passed + failed + blocked;
        const passW = total > 0 ? (passed / total * 100) : 0;
        const failW = total > 0 ? (failed / total * 100) : 0;
        const blockW = total > 0 ? (blocked / total * 100) : 0;
        const recentRuns = p.recentStatuses || [];
        const sparkline = recentRuns.length > 0
            ? `<div class="project-sparkline">${recentRuns.slice(0, 5).map(s => `<span class="sparkline-dot ${s}"></span>`).join('')}</div>` : '';
        const healthBar = total > 0
            ? `<div class="project-health-bar"><div class="bar-pass" style="width:${passW}%"></div><div class="bar-fail" style="width:${failW}%"></div><div class="bar-blocked" style="width:${blockW}%"></div></div>`
            : '<div class="project-health-bar"></div>';
        return `<div class="project-card" onclick="App.navigate('workspace','${p._id}')">
            <div class="project-card-header"><span class="project-card-icon">📁</span><div class="project-card-meta"><div class="project-card-name">${esc(p.name)}</div><span class="project-card-url">${esc(p.url || '')}</span></div><button class="btn-edit-project" title="Edit project" onclick="event.stopPropagation(); Projects._showEdit('${p._id}')">✎</button><button class="btn-delete-project" title="Delete project" onclick="event.stopPropagation(); Projects._confirmDelete('${p._id}', '${esc(p.name).replace(/'/g, "\\'")}')">✕</button></div>
            ${healthBar}
            <div class="project-card-footer"><span>${p.testCaseCount ?? 0} tests · ${total > 0 ? Math.round(passW) + '% pass' : 'no runs'}</span>${sparkline}</div>
        </div>`;
    },

    showCreate() {
        openModal('New Project', `
            <div class="form-group"><label class="form-label">Project Name</label><input class="form-input" id="new-proj-name" placeholder="My E-Commerce Site" autofocus></div>
            <div class="form-group"><label class="form-label">Base URL</label><input class="form-input" id="new-proj-url" placeholder="https://example.com" type="url"></div>
        `, `<button class="btn btn-primary" onclick="Projects._create()">Create</button><button class="btn btn-ghost" onclick="closeModal()">Cancel</button>`);
    },

    async _create() {
        const name = document.getElementById('new-proj-name').value.trim();
        const url = document.getElementById('new-proj-url').value.trim();
        if (!name || !url) { toast('Name and URL required', 'warning'); return; }
        try {
            const { data } = await Api.createProject({ name, url });
            closeModal();
            toast(`Project "${name}" created`, 'success');
            App._refreshProjectCount();
            App.navigate('workspace', data._id);
        } catch (e) { toast(e.message, 'error'); }
    },

    async _showEdit(id) {
        try {
            const { data } = await Api.getProject(id);
            openModal('Edit Project', `
                <div class="form-group"><label class="form-label">Project Name</label><input class="form-input" id="edit-proj-name" value="${esc(data.name)}" autofocus></div>
                <div class="form-group"><label class="form-label">Base URL</label><input class="form-input" id="edit-proj-url" value="${esc(data.url || '')}" type="url"></div>
                <div class="form-group"><label class="form-label">Platform / Folder Label</label><input class="form-input" id="edit-proj-platform" value="${esc(data.platform || '')}" placeholder="e.g. Shopify, WooCommerce"></div>
            `, `<button class="btn btn-primary" onclick="Projects._saveEdit('${id}')">Save</button><button class="btn btn-ghost" onclick="closeModal()">Cancel</button>`);
        } catch (e) { toast(e.message, 'error'); }
    },

    async _saveEdit(id) {
        const name = document.getElementById('edit-proj-name').value.trim();
        const url = document.getElementById('edit-proj-url').value.trim();
        const platform = document.getElementById('edit-proj-platform').value.trim();
        if (!name) { toast('Name is required', 'warning'); return; }
        try {
            await Api.updateProject(id, { name, url, platform });
            closeModal();
            toast('Project updated', 'success');
            Projects.load();
        } catch (e) { toast(e.message, 'error'); }
    },

    _confirmDelete(id, name) {
        openModal('Delete Project', `
            <p style="margin-bottom:8px">Are you sure you want to delete <strong>${name}</strong>?</p>
            <p style="color:var(--danger);font-size:13px">This will permanently remove the project and all its test cases and results.</p>
        `, `<button class="btn btn-danger" onclick="Projects._delete('${id}')">Delete</button><button class="btn btn-ghost" onclick="closeModal()">Cancel</button>`);
    },

    async _delete(id) {
        try {
            await Api.deleteProject(id);
            closeModal();
            toast('Project deleted', 'success');
            App._refreshProjectCount();
            Projects.load();
        } catch (e) { toast(e.message, 'error'); }
    },
};

// ─────────────────────────────────────────────
// WORKSPACE — project detail
// ─────────────────────────────────────────────
const Workspace = {
    projectId: null, project: null, testCases: [],
    activeRunId: null, _timer: null, _timerStart: null, _sseSource: null,

    async load(projectId, sub) {
        this.projectId = projectId;
        // Clear stale selections from other projects so a bulk delete can't
        // accidentally remove test cases that belong to a different project.
        this._selectedTcIds.clear();
        document.querySelectorAll('.page-section').forEach(s => s.style.display = 'none');
        document.getElementById('page-workspace').style.display = 'block';
        document.getElementById('topbar-title').textContent = 'Workspace';

        try {
            const [projRes, tcRes, resRes] = await Promise.all([
                Api.getProject(projectId), Api.getTestCases(projectId), Api.getProjectResults(projectId),
            ]);
            this.project = projRes.data;
            this.testCases = tcRes.data || [];
            document.getElementById('ws-project-name').textContent = this.project.name;
            document.getElementById('topbar-title').textContent = this.project.name;
            const urlEl = document.getElementById('ws-project-url');
            urlEl.textContent = this.project.url; urlEl.href = this.project.url;
            this._populateTcSelect(); this._renderTestCases(); this._renderResults(resRes.data || []);
            this._populatePlanSelect(); this._loadAnalytics();
            this._reconnectDiscovery();

            // Handle sub-route: auto-open result
            if (sub && sub.startsWith('result/')) {
                const resultId = sub.replace('result/', '');
                setTimeout(() => this._viewResult(resultId), 300);
            }
        } catch (e) { toast(e.message, 'error'); }
    },

    editProject() {
        // Delegate to Projects._showEdit to avoid code duplication
        if (this.projectId) {
            Projects._showEdit(this.projectId);
        }
    },

    _populateTcSelect() {
        const sel = document.getElementById('ws-tc-select');
        sel.innerHTML = '<option value="">— select test case —</option>';
        this.testCases.forEach(tc => { const o = document.createElement('option'); o.value = tc._id; o.textContent = tc.name; sel.appendChild(o); });
    },

    _populatePlanSelect() { /* removed — "Run a Test Plan" panel replaced by "Run Selected" */ },

    // Selected test case IDs (for bulk-run from workspace)
    _selectedTcIds: new Set(),
    // Sections collapsed by user (persisted per project in localStorage)
    _collapsedSections: new Set(),

    _sectionOf(tc) {
        return tc.section || _inferSection(tc.name) || 'General';
    },

    _groupBySection(testCases) {
        const groups = new Map();
        testCases.forEach(tc => {
            const sec = this._sectionOf(tc);
            if (!groups.has(sec)) groups.set(sec, []);
            groups.get(sec).push(tc);
        });
        // Stable section order — prefer SECTION_OPTIONS order, unknowns at end
        const ordered = new Map();
        SECTION_OPTIONS.forEach(s => { if (groups.has(s)) ordered.set(s, groups.get(s)); });
        // Any other section names (custom) sorted alphabetically
        for (const [k, v] of [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
            if (!ordered.has(k)) ordered.set(k, v);
        }
        return ordered;
    },

    _loadCollapsedState() {
        try {
            const raw = localStorage.getItem(`collapsedSections:${this.projectId}`);
            this._collapsedSections = new Set(raw ? JSON.parse(raw) : []);
        } catch { this._collapsedSections = new Set(); }
    },

    _saveCollapsedState() {
        try { localStorage.setItem(`collapsedSections:${this.projectId}`, JSON.stringify([...this._collapsedSections])); } catch {}
    },

    toggleSection(name) {
        if (this._collapsedSections.has(name)) this._collapsedSections.delete(name);
        else this._collapsedSections.add(name);
        this._saveCollapsedState();
        this._renderTestCases();
    },

    toggleSectionSelectAll(name) {
        const ids = this.testCases.filter(tc => this._sectionOf(tc) === name).map(tc => tc._id);
        const allSelected = ids.every(id => this._selectedTcIds.has(id));
        ids.forEach(id => {
            if (allSelected) this._selectedTcIds.delete(id);
            else this._selectedTcIds.add(id);
        });
        this._renderTestCases();
        this._updateSelectedCount();
    },

    toggleTcSelected(id) {
        if (this._selectedTcIds.has(id)) this._selectedTcIds.delete(id);
        else this._selectedTcIds.add(id);
        this._updateSelectedCount();
    },

    _updateSelectedCount() {
        const btn = document.getElementById('ws-run-selected-btn');
        const delBtn = document.getElementById('ws-bulk-delete-btn');
        const countEls = document.querySelectorAll('.ws-selected-count');
        const summary = document.getElementById('ws-selected-summary');
        const n = this._selectedTcIds.size;
        const total = this.testCases.length;
        if (btn) btn.disabled = n === 0;
        if (delBtn) delBtn.disabled = n === 0;
        if (countEls) countEls.forEach(el => el.textContent = n);
        if (summary) {
            const option = summary.querySelector('option');
            if (option) option.textContent = `${n} selected of ${total} test(s) selected`;
        }
    },

    selectAllTc() {
        this.testCases.forEach(tc => this._selectedTcIds.add(tc._id));
        this._renderTestCases();
        this._updateSelectedCount();
    },

    clearSelectedTc() {
        this._selectedTcIds.clear();
        this._renderTestCases();
        this._updateSelectedCount();
    },

    async deleteSelectedTc() {
        const validIds = new Set(this.testCases.map(tc => tc._id));
        const ids = [...this._selectedTcIds].filter(id => validIds.has(id));
        if (ids.length === 0) { toast('No test cases selected', 'warning'); return; }
        if (!confirm(`Delete ${ids.length} selected test case(s)? This cannot be undone.`)) return;
        let ok = 0;
        for (const id of ids) {
            try {
                const res = await Api.deleteTestCase(id);
                if (res.success || res.data) ok++;
            } catch (e) { console.warn('Delete skip:', id, e); }
        }
        if (ok > 0) toast(`Deleted ${ok} test case(s)`, ok === ids.length ? 'success' : 'warning');
        this._selectedTcIds.clear();
        this._updateSelectedCount();
        const tcRes = await Api.getTestCases(this.projectId);
        this.testCases = tcRes.data || [];
        this._populateTcSelect();
        this._renderTestCases();
    },

    async runSelected() {
        if (this._selectedTcIds.size === 0) { toast('No test cases selected', 'warning'); return; }
        const ids = [...this._selectedTcIds];
        const mode = document.getElementById('ws-run-mode')?.value || 'graph';
        const device = this._getDevice();
        try {
            const res = await Api.runSelected(this.projectId, ids, mode, device);
            const { queueId, total } = res.data;
            toast(`Started queue: ${total} test${total !== 1 ? 's' : ''}`);
            this._selectedTcIds.clear();
            this._updateSelectedCount();
            this._renderTestCases();
            QueueStatus.start(queueId, this.projectId, total);
        } catch (e) { toast(e.message, 'error'); }
    },

    async _renderTestCases() {
        const container = document.getElementById('ws-test-cases');
        if (!container) return;

        // Lazy-fetch protection
        if (this.testCases.length === 0 && this.projectId) {
            try {
                const res = await Api.getTestCases(this.projectId);
                this.testCases = res.data || [];
            } catch (e) {
                console.error("Failed to fetch test cases:", e);
            }
        }

        document.getElementById('ws-tc-count').textContent = this.testCases.length;

        // Clear existing content fully
        container.innerHTML = '';

        if (!this.testCases.length) {
            container.innerHTML = '<div class="empty-state-sm">No test cases yet. Click <strong>+ Add Test</strong> to create one.</div>';
            this._updateSelectedCount();
            return;
        }

        this._loadCollapsedState();
        const groups = this._groupBySection(this.testCases);

        // Toolbar
        const toolbar = `<div class="tc-toolbar">
            <span class="tc-toolbar-info"><strong class="ws-selected-count">${this._selectedTcIds.size}</strong> selected of ${this.testCases.length}</span>
            <button class="btn btn-sm btn-danger-outline" id="ws-bulk-delete-btn" onclick="Workspace.deleteSelectedTc()" ${this._selectedTcIds.size ? '' : 'disabled'} title="Delete selected test cases">🗑 Delete Selected</button>
            <button class="btn btn-sm btn-ghost" onclick="Workspace.selectAllTc()">Select all</button>
            <button class="btn btn-sm btn-ghost" onclick="Workspace.clearSelectedTc()">Clear</button>
        </div>`;

        let html = toolbar;
        let globalIdx = 0;
        for (const [section, tests] of groups.entries()) {
            const collapsed = this._collapsedSections.has(section);
            const sectionIds = tests.map(t => t._id);
            const allSelected = sectionIds.length > 0 && sectionIds.every(id => this._selectedTcIds.has(id));   
            const someSelected = sectionIds.some(id => this._selectedTcIds.has(id));
            const sectionSelCls = allSelected ? 'all' : (someSelected ? 'some' : '');
            const chevron = collapsed ? '▸' : '▾';

            html += `<div class="tc-section ${collapsed ? 'collapsed' : ''}" data-section="${esc(section)}">    
                <div class="tc-section-header">
                    <span class="tc-section-toggle" onclick="Workspace.toggleSection('${esc(section)}')">${chevron}</span>
                    <input type="checkbox" class="tc-section-checkbox ${sectionSelCls}" ${allSelected ? 'checked' : ''} ${someSelected && !allSelected ? 'data-indeterminate="1"' : ''} onchange="Workspace.toggleSectionSelectAll('${esc(section)}')" title="Select all in this section">
                    <span class="tc-section-name">${esc(section)}</span>
                    <span class="tc-section-count">${tests.length}</span>
                </div>
                <div class="tc-section-body">`;

            tests.forEach(tc => {
                globalIdx++;
                const checked = this._selectedTcIds.has(tc._id) ? 'checked' : '';
                html += `<div class="tc-row" draggable="true" data-tc-id="${tc._id}" data-tc-idx="${globalIdx - 1}">
                    <span class="tc-drag-handle" title="Drag to reorder">⠿</span>
                    <input type="checkbox" class="tc-checkbox" ${checked} onclick="event.stopPropagation();Workspace.toggleTcSelected('${tc._id}')">
                    <span class="tc-row-num">${globalIdx}</span>
                    <div class="tc-row-info">
                        <span class="tc-row-name">${esc(tc.name)}</span>
                        <span class="tc-row-meta">${esc(tc.category || 'general')} · ${tc.steps?.length ?? 0} steps</span>
                    </div>
                    <div class="tc-row-actions">
                        <button class="btn-icon" onclick="Workspace._runTc('${tc._id}')" title="Run this test">▶</button>
                        <button class="btn-icon" onclick="Workspace.editTestCase('${tc._id}')" title="Edit">✎</button>
                        <button class="btn-icon del" onclick="Workspace.deleteTestCase('${tc._id}')" title="Delete">✕</button>
                    </div>
                </div>`;
            });

            html += `</div></div>`;
        }

        container.insertAdjacentHTML('beforeend', html);

        // Apply indeterminate state
        container.querySelectorAll('.tc-section-checkbox[data-indeterminate]').forEach(cb => { cb.indeterminate = true; });

        this._initDragReorder(container);
        this._updateSelectedCount();
    },

    _initDragReorder(container) {
        let dragEl = null;

        // Find the nearest row to cursor Y, and whether cursor is above/below its midpoint
        function getDropTarget(y) {
            const rows = [...container.querySelectorAll('.tc-row:not(.tc-dragging)')];
            if (!rows.length) return { row: null, before: true };
            for (const row of rows) {
                const rect = row.getBoundingClientRect();
                if (y < rect.top + rect.height / 2) return { row, before: true };
            }
            return { row: rows[rows.length - 1], before: false };
        }

        container.addEventListener('dragstart', e => {
            dragEl = e.target.closest('.tc-row');
            if (!dragEl) return;
            e.dataTransfer.effectAllowed = 'move';
            requestAnimationFrame(() => dragEl.classList.add('tc-dragging'));
        });

        container.addEventListener('dragover', e => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            if (!dragEl) return;
            container.querySelectorAll('.tc-drag-above, .tc-drag-below').forEach(r => r.classList.remove('tc-drag-above', 'tc-drag-below'));
            const { row, before } = getDropTarget(e.clientY);
            if (row && row !== dragEl) row.classList.add(before ? 'tc-drag-above' : 'tc-drag-below');
        });

        container.addEventListener('dragend', () => {
            if (dragEl) dragEl.classList.remove('tc-dragging');
            container.querySelectorAll('.tc-drag-above, .tc-drag-below').forEach(r => r.classList.remove('tc-drag-above', 'tc-drag-below'));
            dragEl = null;
        });

        container.addEventListener('drop', e => {
            e.preventDefault();
            container.querySelectorAll('.tc-drag-above, .tc-drag-below').forEach(r => r.classList.remove('tc-drag-above', 'tc-drag-below'));
            if (!dragEl) return;
            const { row, before } = getDropTarget(e.clientY);
            if (row && row !== dragEl) {
                if (before) row.before(dragEl);
                else row.after(dragEl);
            } else if (!row) {
                container.appendChild(dragEl);
            }
            dragEl.classList.remove('tc-dragging');
            // Save new order
            const orderedIds = [...container.querySelectorAll('.tc-row')].map(r => r.dataset.tcId);
            container.querySelectorAll('.tc-row-num').forEach((el, i) => el.textContent = i + 1);
            Api.reorderTestCases(this.projectId, orderedIds).then(() => {
                const idMap = {};
                this.testCases.forEach(tc => idMap[tc._id] = tc);
                this.testCases = orderedIds.map(id => idMap[id]).filter(Boolean);
                this._populateTcSelect();
            }).catch(() => toast('Reorder failed', 'error'));
            dragEl = null;
        });
    },

    _renderResults(results) {
        const container = document.getElementById('ws-results-list');
        if (!results.length) { container.innerHTML = '<div class="empty-state-sm">No runs yet</div>'; return; }

        // Group by calendar day (show up to 30 most recent)
        const shown = results.slice(0, 30);
        const groups = {};
        shown.forEach(r => {
            const key = _dateKey(r.createdAt || r.executedAt);
            if (!groups[key]) groups[key] = [];
            groups[key].push(r);
        });

        let html = '';
        for (const [dateKey, dayResults] of Object.entries(groups).sort((a, b) => b[0].localeCompare(a[0]))) {
            html += `<div class="ws-date-header">${_dateHeader(dateKey)}</div>`;
            dayResults.forEach(r => {
                const cls = r.status === 'pass' ? 'pass' : r.status === 'fail' ? 'fail' : r.status === 'maintenance' ? 'maintenance' : 'blocked';
                const dur = r.duration ? `${(r.duration / 1000).toFixed(0)}s` : '';
                const time = _fmtTime(r.createdAt || r.executedAt);
                const p = r.passed || 0, f = r.failed || 0;
                html += `<div class="result-row" onclick="Workspace._viewResult('${r._id}')">
                    <span class="result-dot ${cls}"></span>
                    <div class="result-row-info">
                        <span class="result-row-name">${esc(r.testCaseName || 'Run')}</span>
                        <span class="result-row-meta">${p}✓ ${f}✗${dur ? ' · ' + dur : ''} · ${time}</span>
                    </div>
                    <span class="result-badge ${cls}">${r.status}</span>
                    <button class="result-row-delete" title="Delete result" onclick="event.stopPropagation();Workspace._deleteResult('${r._id}',this)">✕</button>
                </div>`;
            });
        }

        container.innerHTML = html;
    },

    async _refreshResults() { try { const { data } = await Api.getProjectResults(this.projectId); this._renderResults(data || []); } catch {} },

    // ── Run ──
    async runTest() {
        const id = document.getElementById('ws-tc-select').value;
        if (!id) { toast('Select a test case first', 'warning'); return; }
        const mode = document.getElementById('ws-run-mode').value || 'standard';
        const device = this._getDevice();
        await this._runTc(id, mode, device);
    },

    async _runTc(testCaseId, mode = 'graph', device) {
        try {
            const res = await Api.runTest(testCaseId, mode, device || this._getDevice());
            const label = mode === 'graph' ? ' [Graph]' : '';
            this._startProgress(res.data.runId, (res.data.testCaseName || 'Test') + label, res.data.totalSteps || 0);
        } catch (e) { toast(e.message, 'error'); }
    },

    // runPlan removed — "Run a Test Plan" panel replaced by "Run Selected".

    async runAllRegression() {
        if (!this.testCases.length) { toast('No test cases', 'warning'); return; }
        const regTests = this.testCases.filter(tc => tc.isRegression);
        if (!regTests.length) { toast('No regression test cases marked', 'warning'); return; }
        const device = this._getDevice();
        toast(`Starting regression: ${regTests.length} tests...`);
        try {
            const res = await Api.runProject(this.projectId, 'graph', device);
            const { queueId, total } = res.data;
            QueueStatus.start(queueId, this.projectId, total);
        } catch (e) { toast(e.message, 'error'); }
    },

    cancelRun() {
        if (this.activeRunId) Api.cancelRun(this.activeRunId).catch(() => {});
        clearInterval(this._timer);
        if (this._sseSource) { this._sseSource.close(); this._sseSource = null; }
        this.activeRunId = null;
        const dot = document.querySelector('.dot-pulse');
        if (dot) { dot.style.animation = ''; dot.style.background = 'var(--warning)'; }
        const label = document.getElementById('ws-progress-label');
        if (label) label.textContent = `Cancelled: ${label.textContent.replace('Running: ', '')}`;
        this._appendTerminal(''); this._appendTerminal('$ Cancelled by user');
        this._showResult({ status: 'fail', summary: 'Cancelled by user' });
        document.getElementById('ws-progress-close').style.display = 'inline-flex';
        toast('Run cancelled');
    },

    closeProgress() { document.getElementById('ws-progress').style.display = 'none'; },
    toggleTerminal() { document.getElementById('ws-terminal').classList.toggle('collapsed'); },

    // ── SSE ──
    _startProgress(runId, name, totalSteps) {
        this.activeRunId = runId;
        this._totalSteps = totalSteps;
        this._completedSteps = 0;
        sessionStorage.setItem('activeRun', JSON.stringify({ runId, name, totalSteps, projectId: this.projectId, startedAt: Date.now() }));
        const panel = document.getElementById('ws-progress');
        panel.style.display = 'block';
        document.getElementById('ws-progress-label').textContent = `Running: ${name}`;
        document.getElementById('ws-progress-bar-fill').style.width = '0%';
        document.getElementById('ws-progress-steps').innerHTML = '';
        document.getElementById('ws-progress-result').style.display = 'none';
        document.getElementById('ws-progress-close').style.display = 'none';
        document.getElementById('ws-progress-cancel').disabled = false;
        const termEl = document.getElementById('ws-terminal-output');
        if (termEl) termEl.textContent = '';
        document.getElementById('ws-terminal').classList.remove('collapsed');
        this._timerStart = Date.now();
        clearInterval(this._timer);
        this._timer = setInterval(() => { document.getElementById('ws-progress-timer').textContent = `${Math.floor((Date.now() - this._timerStart) / 1000)}s`; }, 1000);
        this._connectSSE(runId);
    },

    _connectSSE(runId) {
        if (this._sseSource) this._sseSource.close();
        const src = new EventSource(Api.withKey(`/api/run/stream/${runId}`));
        this._sseSource = src;
        src.addEventListener('log', (e) => {
            try { const ev = JSON.parse(e.data); this._appendTerminal(ev.text); } catch {}
        });
        src.addEventListener('step', (e) => {
            try {
                const ev = JSON.parse(e.data);
                this._addProgressStep(ev);
                this._completedSteps = Math.max(this._completedSteps, ev.step || 0);
                const pct = this._totalSteps > 0 ? Math.min(100, Math.round((this._completedSteps / this._totalSteps) * 100)) : 50;
                document.getElementById('ws-progress-bar-fill').style.width = `${pct}%`;
            } catch {}
        });
        src.addEventListener('complete', (e) => {
            try {
                const ev = JSON.parse(e.data);
                this._finishRun(ev.status === 'pass' ? 'var(--success)' : 'var(--danger)', 'Completed', ev);
                this._checkNextRun(ev);
            } catch {}
        });
        src.addEventListener('error', (e) => {
            try {
                const ev = typeof e.data === 'string' ? { message: e.data } : JSON.parse(e.data);
                this._finishRun('var(--danger)', 'Failed', { status: 'fail', summary: ev.message || ev.error || 'Unknown error' });
            } catch {}
        });
        src.addEventListener('cancelled', () => {
            this._finishRun('var(--warning)', 'Cancelled', { status: 'fail', summary: 'Cancelled' });
        });
        src.onerror = () => { if (this.activeRunId === runId) clearInterval(this._timer); };
    },

    _restoreActiveRun() {
        const saved = sessionStorage.getItem('activeRun');
        if (!saved) return;
        try {
            const { runId, name, totalSteps, projectId, startedAt } = JSON.parse(saved);
            Api.getRunStatus(runId).then(res => {
                const run = res.data;
                if (!run || run.status !== 'running') { sessionStorage.removeItem('activeRun'); return; }
                if (projectId) {
                    App.navigate('workspace', projectId);
                    setTimeout(() => {
                        this.activeRunId = runId; this._totalSteps = totalSteps; this._completedSteps = run.currentStep || 0;
                        const panel = document.getElementById('ws-progress');
                        panel.style.display = 'block';
                        document.getElementById('ws-progress-label').textContent = `Running: ${name}`;
                        document.getElementById('ws-progress-close').style.display = 'none';
                        document.getElementById('ws-progress-cancel').disabled = false;
                        const pct = totalSteps > 0 ? Math.min(100, Math.round((this._completedSteps / totalSteps) * 100)) : 0;
                        document.getElementById('ws-progress-bar-fill').style.width = `${pct}%`;
                        this._timerStart = startedAt;
                        clearInterval(this._timer);
                        this._timer = setInterval(() => { document.getElementById('ws-progress-timer').textContent = `${Math.floor((Date.now() - this._timerStart) / 1000)}s`; }, 1000);
                        if (run.progress) run.progress.forEach(p => this._addProgressStep(p));
                        this._connectSSE(runId);
                    }, 500);
                }
            }).catch(() => sessionStorage.removeItem('activeRun'));
        } catch { sessionStorage.removeItem('activeRun'); }
    },

    _finishRun(dotColor, prefix, ev) {
        clearInterval(this._timer);
        if (this._sseSource) { this._sseSource.close(); this._sseSource = null; }
        sessionStorage.removeItem('activeRun');
        document.getElementById('ws-progress-bar-fill').style.width = '100%';
        const dot = document.querySelector('.dot-pulse');
        if (dot) { dot.style.animation = ''; dot.style.background = dotColor; }
        const label = document.getElementById('ws-progress-label');
        if (label) label.textContent = `${prefix}: ${label.textContent.replace('Running: ', '')}`;
        document.getElementById('ws-progress-close').style.display = 'inline-flex';
        document.getElementById('ws-progress-cancel').disabled = true;
        this._showResult(ev);
        this._refreshResults();
        this.activeRunId = null;
    },

    async _checkNextRun(ev) {
        // After a run completes, check if there's a new active run (Run All mode)
        // Wait a moment for the next run to start
        if (ev.resultId && this.projectId) {
            setTimeout(async () => {
                try {
                    const res = await Api.getActiveRuns();
                    const runs = (res.data || []).filter(r => r.projectId === this.projectId && r.status === 'running');
                    if (runs.length > 0) {
                        const next = runs[0];
                        this._appendTerminal(`\n$ Next test: ${next.testCaseName}`);
                        this._startProgress(next.runId, next.testCaseName, next.totalSteps);
                    } else {
                        // No more runs — navigate to result
                        App.navigate('workspace', this.projectId, 'result/' + ev.resultId);
                    }
                } catch {
                    if (ev.resultId) App.navigate('workspace', this.projectId, 'result/' + ev.resultId);
                }
            }, 2000);
        }
    },

    _appendTerminal(text) {
        const el = document.getElementById('ws-terminal-output');
        if (!el) return;
        let cls = '';
        if (text.startsWith('$')) cls = 'term-cmd';
        else if (text.startsWith('>')) cls = 'term-tool';
        else if (text.startsWith('  ')) cls = 'term-output';
        else if (/\*\*PASS\*\*/i.test(text)) cls = 'term-pass';
        else if (/\*\*ADAPTED\*\*/i.test(text)) cls = 'term-adapted';
        else if (/\*\*FAIL\*\*/i.test(text)) cls = 'term-fail';
        if (cls) { const s = document.createElement('span'); s.className = cls; s.textContent = text + '\n'; el.appendChild(s); }
        else { el.appendChild(document.createTextNode(text + '\n')); }
        el.scrollTop = el.scrollHeight;
    },

    _addProgressStep(ev) {
        const list = document.getElementById('ws-progress-steps');
        const icon = ev.status === 'pass' ? '✓' : ev.status === 'adapted' ? '~' : ev.status === 'fail' ? '✗' : ev.status === 'running' ? '◐' : '○';
        const cls = ev.status || '';
        let row = list.querySelector(`[data-step="${ev.step}"]`);
        if (!row) { row = document.createElement('div'); row.className = 'exec-step'; row.dataset.step = ev.step; list.appendChild(row); }
        row.innerHTML = `<span class="step-icon" style="color:${cls === 'pass' ? 'var(--success)' : cls === 'fail' ? 'var(--danger)' : cls === 'adapted' ? 'var(--adapted)' : 'var(--warning)'}">${icon}</span><span class="step-note">${esc(ev.note || '')}</span>`;
        list.scrollTop = list.scrollHeight;
    },

    _showResult(ev) {
        const el = document.getElementById('ws-progress-result');
        el.style.display = 'block';
        el.className = 'exec-result ' + (ev.status || 'fail');
        const icon = ev.status === 'pass' ? '✓' : '✗';
        let text = `${icon} ${ev.summary || ev.status}`;
        const extras = [];
        if (ev.duration) extras.push(`${(ev.duration / 1000).toFixed(1)}s`);
        if (ev.totalTokens) extras.push(`${ev.totalTokens.toLocaleString()} tokens`);
        if (ev.toolCalls) extras.push(`${ev.toolCalls} tools`);
        if (extras.length) text += ` — ${extras.join(', ')}`;
        el.textContent = text;
    },

    // ── Analytics ──
    async _loadAnalytics() {
        if (!this.projectId) return;
        try {
            const { data } = await Api.getProjectAnalytics(this.projectId);
            const container = document.getElementById('ws-analytics');
            if (!container || !data.total) { if (container) container.innerHTML = ''; return; }
            const trendHtml = data.recentTrend?.length > 0 ? `<span class="trend-sparkline">${data.recentTrend.map(t => `<span class="trend-dot ${t.status}"></span>`).join('')}</span>` : '';
            container.innerHTML = `<div class="analytics-grid">
                <div class="analytics-card"><div class="analytics-card-label">Pass Rate</div><div class="analytics-card-value" style="color:${data.passRate >= 70 ? 'var(--success)' : 'var(--danger)'}">${data.passRate}%</div><div class="analytics-card-sub">${data.passed}/${data.total} passed</div></div>
                <div class="analytics-card"><div class="analytics-card-label">Total Runs</div><div class="analytics-card-value">${data.total}</div><div class="analytics-card-sub">${data.failed} failed · ${data.blocked} blocked</div></div>
                <div class="analytics-card"><div class="analytics-card-label">Avg Duration</div><div class="analytics-card-value">${data.avgDuration ? (data.avgDuration / 1000).toFixed(0) + 's' : '—'}</div></div>
                <div class="analytics-card"><div class="analytics-card-label">Trend</div><div style="margin-top:8px">${trendHtml}</div></div>
            </div>`;
        } catch {}
    },

    // ── Result detail — navigates to full page ──
    async _viewResult(resultId) {
        if (this.projectId) {
            App.navigate('workspace', this.projectId, 'result/' + resultId);
        } else {
            App.navigate('result', resultId);
        }
    },

    async _deleteResult(resultId, btn) {
        if (!confirm('Delete this test result permanently? Pass rate will be recalculated.')) return;
        if (btn) { btn.disabled = true; btn.textContent = '…'; }
        try {
            await Api.deleteResult(resultId);
            toast('Result deleted', 'info');
            const row = btn?.closest('.result-row');
            if (row) row.remove();
            // Reload project results + analytics to recompute pass rate
            this._refreshResults();
            this._loadAnalytics();
            if (typeof Dashboard !== 'undefined' && Dashboard.load) Dashboard.load();
        } catch (e) {
            if (btn) { btn.disabled = false; btn.textContent = '✕'; }
            toast('Failed to delete: ' + e.message, 'error');
        }
    },

    _viewResultData(data) {
        ResultDetail.render(data);
    },

    // ── CRUD ──

    _device: 'standard',

    setDevice(mode) {
        this._device = mode;
        document.querySelectorAll('#ws-device-toggle .device-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });
    },

    _getDevice() {
        return this._device || 'standard';
    },

    importBulk() {
        openModal('Import Test Cases (Bulk)', `
            <div class="form-group">
                <label class="form-label">Paste JSON array of test cases</label>
                <textarea class="form-input form-textarea" id="bulk-import-data" rows="12" placeholder='Format 1: [{"name":"Login","category":"positive","steps":[{"action":"navigate","target":"https://example.com"}]}]
Format 2: [{"test_case_id":"TC001","feature":"Login","description":"Verify login","steps":["1. Navigate to page","2. Click button"],"expected_result":"Logged in"}]'></textarea>
            </div>
            <div class="form-group">
                <label class="form-label">Or paste from Chrome Extension format</label>
                <textarea class="form-input form-textarea" id="bulk-import-ext" rows="8" placeholder='Paste recorded steps here...'></textarea>
            </div>
        `, `<button class="btn btn-primary" onclick="Workspace._saveBulkImport()">Import</button><button class="btn btn-ghost" onclick="closeModal()">Cancel</button>`);
    },

    async _saveBulkImport() {
        const el1 = document.getElementById('bulk-import-data');
        const el2 = document.getElementById('bulk-import-ext');
        const rawJson = (el1?.value || '').trim();
        const rawExt = (el2?.value || '').trim();
        const raw = rawJson || rawExt;
        if (!raw) { toast('Paste test case data first', 'warning'); return; }
        
        // Input size validation (prevent DoS)
        const MAX_IMPORT_SIZE = 1024 * 1024; // 1MB
        if (raw.length > MAX_IMPORT_SIZE) {
            toast('Import data too large (max 1MB)', 'error');
            return;
        }
        
        let cases;
        try { cases = JSON.parse(raw); } catch (e) { toast('Invalid JSON: ' + e.message, 'error'); return; }
        if (!Array.isArray(cases)) cases = [cases];
        
        // Limit number of test cases
        const MAX_TEST_CASES = 100;
        if (cases.length > MAX_TEST_CASES) {
            toast(`Too many test cases (max ${MAX_TEST_CASES}). Only first ${MAX_TEST_CASES} will be imported.`, 'warning');
            cases = cases.slice(0, MAX_TEST_CASES);
        }

        function matchSelector(desc, selectors) {
            const entries = Object.entries(selectors);
            const lower = desc.toLowerCase();
            for (const [key, value] of entries) {
                const keyNorm = key.toLowerCase().replace(/[_-]/g, ' ');
                const words = lower.split(/\s+/).filter(w => w.length > 3);
                if (words.some(w => keyNorm.includes(w) || keyNorm.includes(w + 's') || keyNorm.includes(w.slice(0, -1))) ||
                    words.some(w => key.includes(w))) return value;
            }
            return '';
        }

        let imported = 0;
        for (const tc of cases) {
            try {
                let steps = tc.steps || [];
                const selectors = tc.selectors || {};

                if (steps.length > 0 && typeof steps[0] === 'string') {
                    steps = steps.map((s, i) => {
                        const desc = s.replace(/^\d+\.\s*/, '').trim();
                        const lower = desc.toLowerCase();
                        let action = 'verify';
                        let target = '';
                        let expected = tc.expected_result || '';

                        // Handle compound steps: "Click X and verify Y"
                        const andVerify = lower.includes(' and verify');
                        const mainDesc = andVerify ? desc.substring(0, desc.toLowerCase().indexOf(' and verify')).trim() : desc;
                        const verifyPart = andVerify ? desc.substring(desc.toLowerCase().indexOf(' and verify') + 5).trim() : '';
                        if (verifyPart && !expected) expected = verifyPart.charAt(0).toUpperCase() + verifyPart.slice(1);

                        const mainLower = mainDesc.toLowerCase();

                        if (mainLower.startsWith('navigate') || mainLower.startsWith('go to')) {
                            action = 'navigate';
                            target = '';
                        } else if (mainLower.startsWith('click') || mainLower.includes('click on') || mainLower.includes('click the')) {
                            action = 'click';
                            target = matchSelector(mainDesc, selectors) || matchSelector(desc, selectors);
                        } else if (mainLower.startsWith('enter') || mainLower.startsWith('type') || mainLower.startsWith('fill') || mainLower.includes('enter a') || mainLower.includes('enter the')) {
                            action = 'fill';
                            target = matchSelector(mainDesc, selectors) || matchSelector(desc, selectors);
                        } else if (mainLower.startsWith('scroll') || mainLower.includes('scroll to')) {
                            action = 'scroll';
                            target = 'down 500';
                        } else if (mainLower.startsWith('hover') || mainLower.includes('hover over')) {
                            action = 'hover';
                            target = matchSelector(mainDesc, selectors) || matchSelector(desc, selectors);
                        } else if (mainLower.startsWith('select') || mainLower.includes('choose')) {
                            action = 'click';
                            target = matchSelector(mainDesc, selectors) || matchSelector(desc, selectors);
                        } else {
                            action = 'verify';
                            target = matchSelector(desc, selectors) || `text=${desc.split('.').pop().trim()}`;
                        }

                        if (action === 'navigate' && !target) target = '';

                        return { action, target, description: desc, expected: expected || desc, verify: verifyPart || '', seq: i + 1 };
                    });
                }
                const name = tc.name || tc.title || tc.feature || tc.test_case_id || `Imported ${imported + 1}`;
                const category = tc.category || tc.feature || 'general';
                await Api.createTestCase(this.projectId, { name, category, steps });
                imported++;
            } catch (e) { console.warn('Import skip:', e); }
        }
        closeModal();
        toast(`Imported ${imported} test case(s)`, imported > 0 ? 'success' : 'warning');
        const tcRes = await Api.getTestCases(this.projectId);
        this.testCases = tcRes.data || [];
        this._populateTcSelect();
        this._renderTestCases();
    },

    _aiDiscovering: false,
    _discoveryStreamId: null,
    _discoveryRetryCount: 0,
    _discoveryRetryTimer: null,
    _lastDiscoveryCreated: 0,

    _reconnectDiscovery() {
        const stored = localStorage.getItem('ai_discovery');
        if (!stored) return;
        try {
            const { projectId, streamId, ts } = JSON.parse(stored);
            // Only reconnect if this discovery was started recently (within 30 minutes)
            // to avoid reconnecting to stale/crashed streams
            if (Date.now() - (ts || 0) > 30 * 60 * 1000) {
                localStorage.removeItem('ai_discovery');
                this._resetDiscoveryUI();
                return;
            }
            if (projectId !== this.projectId) {
                localStorage.removeItem('ai_discovery');
                return;
            }
            this._aiDiscovering = true;
            this._discoveryStreamId = streamId;
            this._discoveryRetryCount = 0;
            const btn = document.getElementById('ai-discovery-btn');
            const bar = document.getElementById('ai-discovery-progress');
            const status = document.getElementById('ai-discovery-status');
            if (btn) btn.disabled = true;
            if (bar) bar.classList.add('active');
            if (status) { status.textContent = 'Reconnecting...'; status.classList.add('active'); }
            this._attachDiscoveryStream(streamId, status);
            // Safety: if reconnect doesn't resolve within 3 minutes, force-reset
            this._discoveryReconnectTimer = setTimeout(() => {
                if (this._aiDiscovering) {
                    console.warn('[AI Discovery] Reconnect timeout — forcing reset');
                    localStorage.removeItem('ai_discovery');
                    this._resetDiscoveryUI();
                }
            }, 3 * 60 * 1000);
        } catch (err) {
            localStorage.removeItem('ai_discovery');
            this._resetDiscoveryUI();
        }
    },

    _attachDiscoveryStream(streamId, statusEl) {
        const src = new EventSource(Api.withKey(`/api/run/stream/${streamId}`));
        let alive = true;

        src.addEventListener('progress', (ev) => {
            try {
                const data = JSON.parse(ev.data);
                this._lastDiscoveryCreated = typeof data.count === 'number' ? data.count : this._lastDiscoveryCreated;
                if (statusEl) {
                    statusEl.textContent = data.message || '';
                    // Live update: show generated test case count if provided
                    if (typeof data.count === 'number' && statusEl) {
                        statusEl.textContent = (data.message || '') + ` (${data.count} cases)`;
                    }
                }
            } catch {}
        });
        src.addEventListener('complete', (ev) => {
            try {
                const data = JSON.parse(ev.data || '{}');
                this._lastDiscoveryCreated = typeof data.created === 'number' ? data.created : this._lastDiscoveryCreated;
            } catch {}
            alive = false;
            clearTimeout(this._discoveryRetryTimer);
            src.close();
            localStorage.removeItem('ai_discovery');
            this._discoveryStreamId = null;
            this._discoveryRetryCount = 0;
            this._resetDiscoveryUI();
            const created = this._lastDiscoveryCreated || 0;
            const msg = created > 0 ? `AI Discovery completed — ${created} cases created` : 'AI Discovery completed';
            this._lastDiscoveryCreated = 0;
            toast(msg, 'success');
            Api.getTestCases(this.projectId).then(({ data }) => {
                this.testCases = data || [];
                this._populateTcSelect();
                this._renderTestCases();
            });
        });
        src.addEventListener('error', (ev) => {
            try {
                const data = JSON.parse(ev.data);
                alive = false;
                clearTimeout(this._discoveryRetryTimer);
                src.close();
                localStorage.removeItem('ai_discovery');
                this._discoveryStreamId = null;
                this._discoveryRetryCount = 0;
                this._resetDiscoveryUI();
                toast('AI Discovery failed: ' + (data.message || 'Server error'), 'error');
            } catch {}
        });
        src.onerror = () => {
            if (!alive) return;
            alive = false;
            // Transient connection error — retry with backoff instead of killing discovery.
            // This is the key fix: a blip on refresh/reconnect should not abandon the run.
            this._discoveryRetryCount = (this._discoveryRetryCount || 0) + 1;
            if (this._discoveryRetryCount <= 5) {
                const delay = Math.min(1000 * this._discoveryRetryCount, 5000);
                if (statusEl) statusEl.textContent = `Reconnecting (${this._discoveryRetryCount}/5)...`;
                this._discoveryRetryTimer = setTimeout(() => {
                    if (this._discoveryStreamId === streamId && this._aiDiscovering) {
                        src.close();
                        this._attachDiscoveryStream(streamId, statusEl);
                    }
                }, delay);
            } else {
                clearTimeout(this._discoveryRetryTimer);
                src.close();
                localStorage.removeItem('ai_discovery');
                this._discoveryStreamId = null;
                this._discoveryRetryCount = 0;
                this._resetDiscoveryUI();
                toast('AI Discovery connection lost — please restart', 'error');
            }
        };
    },

    _resetDiscoveryUI() {
        clearTimeout(this._discoveryRetryTimer);
        clearTimeout(this._discoveryReconnectTimer);
        this._aiDiscovering = false;
        this._discoveryStreamId = null;
        this._discoveryRetryCount = 0;
        this._lastDiscoveryCreated = 0;
        const btn = document.getElementById('ai-discovery-btn');
        const bar = document.getElementById('ai-discovery-progress');
        const status = document.getElementById('ai-discovery-status');
        if (btn) btn.disabled = false;
        if (bar) bar.classList.remove('active');
        if (status) { status.textContent = ''; status.classList.remove('active'); }
    },

    async generateAITests() {
        if (!this.projectId) return;
        // If stuck in discovering state (e.g. stale reconnect), force-reset so user can retry
        if (this._aiDiscovering) {
            console.warn('[AI Discovery] Stuck in progress — force resetting');
            localStorage.removeItem('ai_discovery');
            this._resetDiscoveryUI();
            toast('Previous discovery was stuck — reset. Click AI Discovery again.', 'warning');
            return;
        }
        // If a discovery is already persisted (e.g. page refreshed mid-run), reconnect instead
        const existing = localStorage.getItem('ai_discovery');
        if (existing) {
            try {
                const { projectId, streamId } = JSON.parse(existing);
                if (projectId === this.projectId) {
                    this._aiDiscovering = true;
                    this._discoveryStreamId = streamId;
                    const btn = document.getElementById('ai-discovery-btn');
                    const bar = document.getElementById('ai-discovery-progress');
                    const status = document.getElementById('ai-discovery-status');
                    if (btn) btn.disabled = true;
                    if (bar) bar.classList.add('active');
                    if (status) { status.textContent = 'Resuming...'; status.classList.add('active'); }
                    this._attachDiscoveryStream(streamId, status);
                    return;
                }
            } catch {}
        }
        this._aiDiscovering = true;
        this._discoveryRetryCount = 0;
        const btn = document.getElementById('ai-discovery-btn');
        const bar = document.getElementById('ai-discovery-progress');
        const status = document.getElementById('ai-discovery-status');
        if (btn) btn.disabled = true;
        if (bar) bar.classList.add('active');
        if (status) { status.textContent = 'Starting...'; status.classList.add('active'); }
        try {
            const d = await Api.generateAITests(this.projectId);
            const streamId = d.data.streamId;
            localStorage.setItem('ai_discovery', JSON.stringify({ projectId: this.projectId, streamId, ts: Date.now() }));
            this._discoveryStreamId = streamId;
            this._attachDiscoveryStream(streamId, status);
        } catch (e) {
            this._resetDiscoveryUI();
            toast('AI Discovery failed: ' + e.message, 'error');
        }
    },

    _sectionOptionsHtml(selected) {
        return SECTION_OPTIONS.map(s => `<option value="${esc(s)}" ${s === selected ? 'selected' : ''}>${esc(s)}</option>`).join('');
    },

    addManual() {
        openModal('Add Test Case', `
            <div class="form-group"><label class="form-label">Name</label><input class="form-input" id="tc-name" placeholder="TC-07: Wishlist" autofocus></div>
            <div class="form-group"><label class="form-label">Section</label><select class="form-input" id="tc-section">${this._sectionOptionsHtml('General')}</select></div>
            <div class="form-group"><label class="form-label">Category</label><input class="form-input" id="tc-cat" placeholder="positive / negative / accessibility / security"></div>
            <div class="form-group"><label class="form-label">Steps (JSON)</label><textarea class="form-input form-textarea" id="tc-steps" rows="8" placeholder='[{"seq":1,"action":"navigate","target":"https://example.com","description":"Go to homepage"}]'></textarea></div>
        `, `<button class="btn btn-primary" onclick="Workspace._saveNewTc()">Save</button><button class="btn btn-ghost" onclick="closeModal()">Cancel</button>`);
    },

    async _saveNewTc() {
        const name = document.getElementById('tc-name').value.trim();
        const cat = document.getElementById('tc-cat').value.trim() || 'general';
        const section = document.getElementById('tc-section').value || _inferSection(name);
        const raw = document.getElementById('tc-steps').value.trim();
        if (!name) { toast('Name required', 'warning'); return; }
        let steps = []; if (raw) { try { steps = JSON.parse(raw); } catch { toast('Invalid JSON', 'error'); return; } }
        try { await Api.createTestCase(this.projectId, { name, category: cat, section, steps }); closeModal(); toast('Test case created', 'success'); const tcRes = await Api.getTestCases(this.projectId); this.testCases = tcRes.data || []; this._populateTcSelect(); this._renderTestCases(); } catch (e) { toast(e.message, 'error'); }
    },

    async editTestCase(id) {
        try {
            const { data: tc } = await Api.getTestCase(id);
            const currentSection = tc.section || _inferSection(tc.name);
            openModal('Edit Test Case', `
                <div class="form-group"><label class="form-label">Name</label><input class="form-input" id="edit-tc-name" value="${esc(tc.name)}"></div>
                <div class="form-group"><label class="form-label">Section</label><select class="form-input" id="edit-tc-section">${this._sectionOptionsHtml(currentSection)}</select></div>
                <div class="form-group"><label class="form-label">Category</label><input class="form-input" id="edit-tc-cat" value="${esc(tc.category || '')}"></div>
                <div class="form-group"><label class="form-label">Steps (JSON)</label><textarea class="form-input form-textarea" id="edit-tc-steps" rows="12">${esc(JSON.stringify(tc.steps || [], null, 2))}</textarea></div>
            `, `<button class="btn btn-primary" onclick="Workspace._saveEditTc('${id}')">Save</button><button class="btn btn-danger-outline" onclick="Workspace.deleteTestCase('${id}')">Delete</button><button class="btn btn-ghost" onclick="closeModal()">Cancel</button>`);
        } catch (e) { toast(e.message, 'error'); }
    },

    async _saveEditTc(id) {
        const name = document.getElementById('edit-tc-name').value.trim();
        const cat = document.getElementById('edit-tc-cat').value.trim();
        const section = document.getElementById('edit-tc-section').value;
        const raw = document.getElementById('edit-tc-steps').value.trim();
        if (!name) { toast('Name required', 'warning'); return; }
        let steps = []; if (raw) { try { steps = JSON.parse(raw); } catch { toast('Invalid JSON', 'error'); return; } }
        try { await Api.updateTestCase(id, { name, category: cat, section, steps }); closeModal(); toast('Updated', 'success'); const tcRes = await Api.getTestCases(this.projectId); this.testCases = tcRes.data || []; this._populateTcSelect(); this._renderTestCases(); } catch (e) { toast(e.message, 'error'); }
    },

    async deleteTestCase(id) {
        if (!confirm('Delete this test case?')) return;
        console.log("DEBUG: Attempting to delete:", id);
        try {
            const response = await Api.deleteTestCase(id);
            console.log("DEBUG: API Response:", response);
            if (!response.success) {
                throw new Error(response.error || 'Failed to delete');
            }

            toast('Deleted', 'success');
            if (response.data && typeof response.data.removed_count === 'number') {
                this.testCases = this.testCases.filter(tc => tc._id !== id && tc.id !== id);
                this._populateTcSelect();
                this._renderTestCases();
                closeModal();
                return;
            }

            // Fallback: fetch fresh list from server
            const tcRes = await Api.getTestCases(this.projectId);
            console.log("DEBUG: Refreshed TC List:", tcRes.data);
            this.testCases = tcRes.data || [];
            this._populateTcSelect();
            this._renderTestCases();
            closeModal();
        } catch (e) {
            console.error("DEBUG: Deletion error:", e);
            toast(e.message, 'error');
        }
    },

    /** Reconnect to existing run from GlobalRuns panel */
    _reconnectToRun(runId) {
        Api.getRunStatus(runId).then(res => {
            const run = res.data;
            if (!run || run.status !== 'running') return;
            this.activeRunId = runId; this._totalSteps = run.totalSteps || 0; this._completedSteps = run.currentStep || 0;
            const panel = document.getElementById('ws-progress');
            panel.style.display = 'block';
            document.getElementById('ws-progress-label').textContent = `Running: ${run.testCaseName || 'Test'}`;
            document.getElementById('ws-progress-close').style.display = 'none';
            document.getElementById('ws-progress-cancel').disabled = false;
            const pct = this._totalSteps > 0 ? Math.min(100, Math.round((this._completedSteps / this._totalSteps) * 100)) : 0;
            document.getElementById('ws-progress-bar-fill').style.width = `${pct}%`;
            this._timerStart = new Date(run.startedAt).getTime();
            clearInterval(this._timer);
            this._timer = setInterval(() => { document.getElementById('ws-progress-timer').textContent = `${Math.floor((Date.now() - this._timerStart) / 1000)}s`; }, 1000);
            const stepsList = document.getElementById('ws-progress-steps'); stepsList.innerHTML = '';
            if (run.progress) run.progress.forEach(p => this._addProgressStep(p));
            this._connectSSE(runId);
            sessionStorage.setItem('activeRun', JSON.stringify({ runId, name: run.testCaseName, totalSteps: this._totalSteps, projectId: this.projectId, startedAt: this._timerStart }));
        }).catch(() => {});
    },
};

// ─────────────────────────────────────────────
// RESULTS — global run history
// ─────────────────────────────────────────────
const Results = {
    _raw: [],
    _filters: { projectId: '', range: 'all', status: 'all', sort: 'date_desc' },

    async load() {
        const container = document.getElementById('results-content');
        container.innerHTML = '<div class="empty-state-sm">Loading results...</div>';
        try {
            const [resRes, projRes] = await Promise.all([Api.getTestResults(), Api.getProjects()]);
            this._raw = resRes.data || [];
            this._projectMap = {};
            (projRes.data || []).forEach(p => { this._projectMap[p.id || p._id] = p.name; });
            this._raw.forEach(r => {
                if (!r.projectName && r.projectId && this._projectMap[r.projectId]) {
                    r.projectName = this._projectMap[r.projectId];
                }
            });
            if (!this._raw.length) { container.innerHTML = '<div class="empty-state-sm">No test runs yet.</div>'; return; }
            this._restoreFilters();
            this._render();
        } catch (e) { container.innerHTML = `<div class="empty-state-sm" style="color:var(--danger)">Failed: ${e.message}</div>`; }
    },

    _restoreFilters() {
        try {
            const saved = JSON.parse(sessionStorage.getItem('resultsFilters') || '{}');
            this._filters = { projectId: '', range: 'all', status: 'all', sort: 'date_desc', ...saved };
        } catch {}
    },

    _saveFilters() {
        try { sessionStorage.setItem('resultsFilters', JSON.stringify(this._filters)); } catch {}
    },

    _projectOptions() {
        const seen = new Map();
        this._raw.forEach(r => {
            if (r.projectId && r.projectName && !seen.has(r.projectId)) seen.set(r.projectId, r.projectName);
        });
        return Array.from(seen.entries()).sort((a, b) => a[1].localeCompare(b[1]));
    },

    _passesFilters(r) {
        const f = this._filters;
        if (f.projectId && r.projectId !== f.projectId) return false;
        if (f.status !== 'all' && r.status !== f.status) return false;
        if (f.range !== 'all') {
            const key = _dateKey(r.created || r.createdAt);
            if (!key) return false;
            const now = new Date();
            const todayKey = now.toISOString().substring(0, 10);
            const yesterdayDate = new Date(now.getTime() - 86400000);
            const yesterdayKey = yesterdayDate.toISOString().substring(0, 10);
            if (f.range === 'today' && key !== todayKey) return false;
            if (f.range === 'yesterday' && key !== yesterdayKey) return false;
            if (f.range === '7d' || f.range === '30d') {
                const maxDays = f.range === '7d' ? 6 : 29;
                const rDate = new Date(key + 'T12:00:00Z');
                const todayDate = new Date(todayKey + 'T12:00:00Z');
                const diffDays = Math.floor((todayDate.getTime() - rDate.getTime()) / 86400000);
                if (diffDays < 0 || diffDays > maxDays) return false;
            }
        }
        return true;
    },

    setFilter(key, value) {
        this._filters[key] = value;
        this._saveFilters();
        this._render();
    },

    clearFilters() {
        this._filters = { projectId: '', range: 'all', status: 'all', sort: 'date_desc' };
        this._saveFilters();
        this._render();
    },

    _renderBar(filteredCount) {
        const f = this._filters;
        const projOpts = this._projectOptions();
        const projSelect = `<select class="results-filter-select" onchange="Results.setFilter('projectId', this.value)">
            <option value="">All projects</option>
            ${projOpts.map(([id, name]) => `<option value="${esc(id)}" ${f.projectId === id ? 'selected' : ''}>${esc(name)}</option>`).join('')}
        </select>`;
        const rangeSelect = `<select class="results-filter-select" onchange="Results.setFilter('range', this.value)">
            ${[['all','All time'],['today','Today'],['yesterday','Yesterday'],['7d','Last 7 days'],['30d','Last 30 days']]
                .map(([v,l]) => `<option value="${v}" ${f.range === v ? 'selected' : ''}>${l}</option>`).join('')}
        </select>`;
        const statusSelect = `<select class="results-filter-select" onchange="Results.setFilter('status', this.value)">
            ${[['all','All statuses'],['pass','Pass'],['fail','Fail'],['blocked','Blocked']]
                .map(([v,l]) => `<option value="${v}" ${f.status === v ? 'selected' : ''}>${l}</option>`).join('')}
        </select>`;
        const sortSelect = `<select class="results-filter-select" onchange="Results.setFilter('sort', this.value)">
            ${[['date_desc','Newest first'],['date_asc','Oldest first'],['project','By project']]
                .map(([v,l]) => `<option value="${v}" ${f.sort === v ? 'selected' : ''}>${l}</option>`).join('')}
        </select>`;
        const hasActive = f.projectId || f.range !== 'all' || f.status !== 'all' || f.sort !== 'date_desc';
        const clearBtn = hasActive ? `<button class="results-filter-clear" onclick="Results.clearFilters()">Clear</button>` : '';
        return `<div class="results-filter-bar">
            <span class="results-filter-label">Project</span>${projSelect}
            <span class="results-filter-label">Date</span>${rangeSelect}
            <span class="results-filter-label">Status</span>${statusSelect}
            <span class="results-filter-label">Sort</span>${sortSelect}
            ${clearBtn}
            <span class="results-filter-count">${filteredCount} of ${this._raw.length}</span>
        </div>`;
    },

    _render() {
        const container = document.getElementById('results-content');
        const filtered = this._raw.filter(r => this._passesFilters(r));
        const bar = this._renderBar(filtered.length);

        if (!filtered.length) {
            container.innerHTML = bar + '<div class="empty-state-sm">No results match the current filters.</div>';
            return;
        }

        let body = '';
        if (this._filters.sort === 'project') {
            // Group by project, within each project sort by date desc
            const groups = {};
            filtered.forEach(r => {
                const k = r.projectName || 'Unassigned';
                (groups[k] = groups[k] || []).push(r);
            });
            const projectKeys = Object.keys(groups).sort((a, b) => a.localeCompare(b));
            for (const projName of projectKeys) {
                const items = groups[projName].sort((a, b) => (b.created || '').localeCompare(a.created || ''));
                body += `<div class="date-group">
                    <div class="date-group-header">
                        <span class="date-group-label">${esc(projName)}</span>
                        <span class="date-group-count">${items.length} run${items.length !== 1 ? 's' : ''}</span>
                    </div>
                    <div class="date-group-rows">${items.map(r => this._cardHtml(r, /*showDate*/true)).join('')}</div>
                </div>`;
            }
        } else {
            // Group by calendar day
            const groups = {};
            filtered.forEach(r => {
                const key = _dateKey(r.created || r.createdAt);
                (groups[key] = groups[key] || []).push(r);
            });
            const cmp = this._filters.sort === 'date_asc'
                ? (a, b) => a[0].localeCompare(b[0])
                : (a, b) => b[0].localeCompare(a[0]);
            for (const [dateKey, dayResults] of Object.entries(groups).sort(cmp)) {
                body += `<div class="date-group">
                    <div class="date-group-header">
                        <span class="date-group-label">${_dateHeader(dateKey)}</span>
                        <span class="date-group-count">${dayResults.length} run${dayResults.length !== 1 ? 's' : ''}</span>
                    </div>
                    <div class="date-group-rows">${dayResults.map(r => this._cardHtml(r, false)).join('')}</div>
                </div>`;
            }
        }

        container.innerHTML = bar + body;
    },

    _cardHtml(r, showDate) {
        const status = r.status || (r.failed > 0 ? 'fail' : r.passed > 0 ? 'pass' : 'blocked');
        const cls = status;
        const viewId = r.id || r.filename;
        const dur = r.duration ? `${(r.duration / 1000).toFixed(0)}s` : '';
        const runner = r.runner === 'graph' ? 'Graph' : r.runner === 'claude-browser' ? 'Standard' : r.runner === 'ai' ? 'AI' : r.runner || '';
        const time = showDate ? _fmtDateTime(r.created || r.createdAt) : _fmtTime(r.created || r.createdAt);
        let stepsHtml = '';
        if (r.passed) stepsHtml += `<span class="sc-pass">${r.passed}✓</span>`;
        if (r.adapted) stepsHtml += `<span class="sc-adapted">${r.adapted}~</span>`;
        if (r.failed) stepsHtml += `<span class="sc-fail">${r.failed}✗</span>`;
        if (r.blocked) stepsHtml += `<span class="sc-blocked">${r.blocked}⏸</span>`;
        const meta = [stepsHtml, dur, runner].filter(Boolean).join('<span class="sep">·</span>');
        const delBtn = r.id ? `<button class="result-card-delete" title="Delete result" onclick="event.stopPropagation();Results._delete('${r.id}',this)">✕</button>` : '';
        return `<div class="result-card" onclick="Results._view('${esc(viewId || '')}')">
            <span class="result-badge ${cls}" style="min-width:52px;text-align:center">${status.toUpperCase()}</span>
            <div class="result-card-info">
                <span class="result-card-name">${esc(r.title || r.testCaseName || '—')}</span>
                <span class="result-card-meta">${meta}</span>
            </div>
            <span class="result-card-time">${time}</span>
            ${delBtn}
        </div>`;
    },

    async _view(id) { App.navigate('result', id); },

    async _delete(id, btn) {
        if (!confirm('Delete this test result permanently? Pass rate will be recalculated.')) return;
        if (btn) { btn.disabled = true; btn.textContent = '…'; }
        try {
            await Api.deleteResult(id);
            toast('Result deleted', 'info');
            // Drop from cache and re-render with current filters — preserves user's filter state
            this._raw = this._raw.filter(r => r.id !== id);
            this._render();
            if (typeof Dashboard !== 'undefined' && Dashboard.load) Dashboard.load();
        } catch (e) {
            if (btn) { btn.disabled = false; btn.textContent = '✕'; }
            toast('Failed to delete: ' + e.message, 'error');
        }
    },
};

// ─────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────
const Config = {
    _ollamaConnected: false,

    async load() {
        const container = document.getElementById('config-content');
        container.innerHTML = '<div class="empty-state-sm">Loading config...</div>';
        try {
            const { data } = await Api.getConfig();
            const baseUrl = data.ollama_base_url || 'http://localhost:11434';
            const provider = data.ai_provider || 'ollama';
            const currentModel = data.ollama_model || 'qwen2.5-coder:3b';
            const cloudUrl = data.cloud_base_url || '';
            const cloudKeySet = !!data.cloud_api_key_set;
            const cloudModel = data.cloud_model || '';

            // Fetch ollama status + models in parallel
            let ollamaStatus = false, models = [];
            try {
                const [statusRes, modelsRes] = await Promise.all([
                    Api.afetch('/api/ollama-status'),
                    Api.afetch('/api/ollama-models'),
                ]);
                ollamaStatus = statusRes.data?.connected || false;
                models = modelsRes.data?.models || [];
                this._ollamaConnected = ollamaStatus;
            } catch {}

            const statusDot = ollamaStatus
                ? '<span class="cfg-status-dot cfg-status-ok"></span><span class="cfg-status-text cfg-status-ok">Connected</span>'
                : '<span class="cfg-status-dot cfg-status-err"></span><span class="cfg-status-text cfg-status-err">Disconnected</span>';

            const modelOptions = models.length > 0
                ? models.map(m => `<option value="${esc(m)}" ${m === currentModel ? 'selected' : ''}>${esc(m)}</option>`).join('')
                : `<option value="${esc(currentModel)}" selected>${esc(currentModel)}</option>`;

            container.innerHTML = `
            <div class="cfg-grid">
                <!-- AI Provider Card -->
                <div class="cfg-card">
                    <div class="cfg-card-header">
                        <span class="cfg-card-icon">🤖</span>
                        <span class="cfg-card-title">AI Provider</span>
                    </div>
                    <div class="cfg-card-body">
                        <div class="form-group">
                            <label class="form-label">Select Provider</label>
                            <select class="form-input" id="cfg-provider" onchange="Config._onProviderChange()">
                                <option value="ollama" ${provider === 'ollama' ? 'selected' : ''}>Local AI (Ollama)</option>
                                <option value="cloud" ${provider === 'cloud' ? 'selected' : ''}>Cloud API</option>
                            </select>
                        </div>
                    </div>
                </div>

                <!-- Ollama Config Card -->
                <div class="cfg-card" id="cfg-ollama-card">
                    <div class="cfg-card-header">
                        <span class="cfg-card-icon">⚡</span>
                        <span class="cfg-card-title">Local AI (Ollama)</span>
                        <div class="cfg-card-status">${statusDot}</div>
                    </div>
                    <div class="cfg-card-body">
                        <div class="form-group">
                            <label class="form-label">Base URL</label>
                            <input class="form-input" id="cfg-url" value="${esc(baseUrl)}" placeholder="http://localhost:11434">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Model</label>
                            <select class="form-input" id="cfg-model">${modelOptions}</select>
                        </div>
                        <div class="cfg-hint">
                            <strong>Quick Setup:</strong><br>
                            Install: <code>curl -fsSL https://ollama.ai/install.sh | sh</code><br>
                            Pull model: <code>ollama pull qwen2.5-coder:3b</code>
                        </div>
                    </div>
                </div>

                <!-- Cloud API Config Card -->
                <div class="cfg-card" id="cfg-cloud-card" style="display:none">
                    <div class="cfg-card-header">
                        <span class="cfg-card-icon">☁️</span>
                        <span class="cfg-card-title">Cloud API</span>
                        <div class="cfg-card-status" id="cfg-cloud-status"></div>
                    </div>
                    <div class="cfg-card-body">
                        <div class="form-group">
                            <label class="form-label">API Base URL</label>
                            <input class="form-input" id="cfg-cloud-url" type="password" value="${esc(cloudUrl)}" placeholder="https://api.example.com/v1" autocomplete="off" spellcheck="false" oncopy="return false" oncut="return false" oncontextmenu="return false" ondrag="return false" ondragstart="return false" oninput="Config._debounceCloudTest()" style="-webkit-user-select:none;user-select:none">
                        </div>
                        <div class="form-group">
                            <label class="form-label">API Key ${cloudKeySet ? '<span class="cfg-status-badge ok">saved</span>' : ''}</label>
                            <input class="form-input" id="cfg-cloud-key" type="password" value="" placeholder="${cloudKeySet ? '•••••••• (saved — leave blank to keep)' : 'nvapi-...'}" autocomplete="new-password" oninput="Config._debounceCloudTest()">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Model</label>
                            <div style="display:flex;gap:8px;align-items:center">
                                <select class="form-input" id="cfg-cloud-model" style="flex:1">
                                    <option value="${esc(cloudModel)}">${cloudModel ? esc(cloudModel) : '-- enter URL & key first --'}</option>
                                </select>
                                <button class="btn btn-sm btn-ghost" onclick="Config.fetchCloudModels()" id="cfg-cloud-fetch-btn">↻ Fetch</button>
                            </div>
                        </div>
                        <div class="cfg-hint">
                            Supports any OpenAI-compatible API.<br>
                            Enter URL + Key, then click <strong>Fetch</strong> to load available models.
                        </div>
                    </div>
                </div>

                <!-- System Status Card -->
                <div class="cfg-card">
                    <div class="cfg-card-header">
                        <span class="cfg-card-icon">📊</span>
                        <span class="cfg-card-title">System Status</span>
                    </div>
                    <div class="cfg-card-body">
                        <div class="cfg-status-grid">
                            <div class="cfg-status-item">
                                <span class="cfg-status-label">Ollama Server</span>
                                <span class="cfg-status-badge ${ollamaStatus ? 'ok' : 'err'}">${ollamaStatus ? 'Online' : 'Offline'}</span>
                            </div>
                            <div class="cfg-status-item">
                                <span class="cfg-status-label">Available Models</span>
                                <span class="cfg-status-badge info">${models.length}</span>
                            </div>
                            <div class="cfg-status-item">
                                <span class="cfg-status-label">Current Model</span>
                                <span class="cfg-status-badge info">${esc(currentModel)}</span>
                            </div>
                            <div class="cfg-status-item">
                                <span class="cfg-status-label">Base URL</span>
                                <span class="cfg-status-badge info">${esc(baseUrl)}</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Access Key Card -->
                <div class="cfg-card">
                    <div class="cfg-card-header">
                        <span class="cfg-card-icon">🔑</span>
                        <span class="cfg-card-title">Access Key</span>
                        <div class="cfg-card-status" id="cfg-access-status">${Api.getKey() ? '<span class="cfg-status-dot cfg-status-ok"></span><span class="cfg-status-text cfg-status-ok">Set</span>' : '<span class="cfg-status-dot cfg-status-err"></span><span class="cfg-status-text cfg-status-err">Not set</span>'}</div>
                    </div>
                    <div class="cfg-card-body">
                        <div class="form-group">
                            <label class="form-label">X-API-Key (browser only)</label>
                            <div style="display:flex;gap:8px;align-items:center">
                                <input class="form-input" id="cfg-access-key" type="password" style="flex:1" placeholder="Paste server API key" autocomplete="new-password">
                                <button class="btn btn-sm" onclick="Config.saveAccessKey()">Save</button>
                                <button class="btn btn-sm btn-ghost" onclick="Config.clearAccessKey()">Clear</button>
                            </div>
                        </div>
                        <div class="cfg-hint">
                            Required when the server has <code>API_KEY</code> set (e.g. deployed). Stored in this browser only — never sent anywhere except your server.
                        </div>
                    </div>
                </div>
            </div>`;

            this._onProviderChange();
        } catch (e) { container.innerHTML = `<div class="empty-state-sm" style="color:var(--danger)">Failed: ${e.message}</div>`; }
    },

    _onProviderChange() {
        const provider = document.getElementById('cfg-provider')?.value || 'ollama';
        const ollamaCard = document.getElementById('cfg-ollama-card');
        const cloudCard = document.getElementById('cfg-cloud-card');
        if (ollamaCard) ollamaCard.style.display = provider === 'ollama' ? '' : 'none';
        if (cloudCard) cloudCard.style.display = provider === 'cloud' ? '' : 'none';
        // Auto-fetch cloud models if URL & key are filled
        if (provider === 'cloud') {
            const url = document.getElementById('cfg-cloud-url')?.value || '';
            const key = document.getElementById('cfg-cloud-key')?.value || '';
            if (url && key && key.length > 5) {
                this.fetchCloudModels();
            }
        }
    },

    _cloudTestTimer: null,
    _debounceCloudTest() {
        clearTimeout(this._cloudTestTimer);
        this._cloudTestTimer = setTimeout(() => this._testCloudConnection(), 800);
    },

    async _testCloudConnection() {
        const statusEl = document.getElementById('cfg-cloud-status');
        const url = document.getElementById('cfg-cloud-url')?.value || '';
        const key = document.getElementById('cfg-cloud-key')?.value || '';
        if (!url || !key || key.length < 5) {
            if (statusEl) statusEl.innerHTML = '';
            return;
        }
        if (statusEl) statusEl.innerHTML = '<span class="cfg-status-dot" style="background:#FDCB6E"></span><span class="cfg-status-text" style="color:#FDCB6E">Testing...</span>';
        try {
            const json = await Api.afetch(Api.withKey(`/api/cloud-test?base_url=${encodeURIComponent(url)}&api_key=${encodeURIComponent(key)}`));
            if (json.data?.connected) {
                if (statusEl) statusEl.innerHTML = '<span class="cfg-status-dot cfg-status-ok"></span><span class="cfg-status-text cfg-status-ok">Connected</span>';
                this.fetchCloudModels();
            } else {
                if (statusEl) statusEl.innerHTML = '<span class="cfg-status-dot cfg-status-err"></span><span class="cfg-status-text cfg-status-err">Failed: ' + esc(json.data?.error || 'Unknown') + '</span>';
            }
        } catch {
            if (statusEl) statusEl.innerHTML = '<span class="cfg-status-dot cfg-status-err"></span><span class="cfg-status-text cfg-status-err">Connection error</span>';
        }
    },

    async fetchCloudModels() {
        const url = document.getElementById('cfg-cloud-url')?.value || '';
        const key = document.getElementById('cfg-cloud-key')?.value || '';
        const select = document.getElementById('cfg-cloud-model');
        const btn = document.getElementById('cfg-cloud-fetch-btn');
        const statusEl = document.getElementById('cfg-cloud-status');
        if (!url || !key) { toast('Enter URL and API key first', 'warning'); return; }
        if (btn) btn.disabled = true;
        if (statusEl) statusEl.innerHTML = '<span class="cfg-status-dot" style="background:#FDCB6E"></span><span class="cfg-status-text" style="color:#FDCB6E">Fetching models...</span>';
        try {
            const json = await Api.afetch(Api.withKey(`/api/cloud-models?base_url=${encodeURIComponent(url)}&api_key=${encodeURIComponent(key)}`));
            if (json.success && json.data?.models?.length > 0) {
                const models = json.data.models;
                const currentVal = select?.value || '';
                if (select) {
                    select.innerHTML = models.map(m =>
                        `<option value="${esc(m)}" ${m === currentVal ? 'selected' : ''}>${esc(m)}</option>`
                    ).join('');
                }
                if (statusEl) statusEl.innerHTML = '<span class="cfg-status-dot cfg-status-ok"></span><span class="cfg-status-text cfg-status-ok">Connected — ' + models.length + ' models</span>';
                toast(`Loaded ${models.length} models`, 'success');
            } else {
                if (statusEl) statusEl.innerHTML = '<span class="cfg-status-dot cfg-status-err"></span><span class="cfg-status-text cfg-status-err">' + esc(json.error || 'No models found') + '</span>';
                toast(json.error || 'Failed to fetch models', 'error');
            }
        } catch (e) {
            if (statusEl) statusEl.innerHTML = '<span class="cfg-status-dot cfg-status-err"></span><span class="cfg-status-text cfg-status-err">Request failed</span>';
            toast('Failed to fetch models: ' + e.message, 'error');
        }
        if (btn) btn.disabled = false;
    },

    saveAccessKey() {
        const v = document.getElementById('cfg-access-key')?.value.trim() || '';
        if (!v) { toast('Enter a key first', 'warning'); return; }
        Api.setKey(v);
        document.getElementById('cfg-access-key').value = '';
        const st = document.getElementById('cfg-access-status');
        if (st) st.innerHTML = '<span class="cfg-status-dot cfg-status-ok"></span><span class="cfg-status-text cfg-status-ok">Set</span>';
        toast('Access key saved in this browser', 'success');
    },

    clearAccessKey() {
        Api.setKey('');
        const inp = document.getElementById('cfg-access-key');
        if (inp) inp.value = '';
        const st = document.getElementById('cfg-access-status');
        if (st) st.innerHTML = '<span class="cfg-status-dot cfg-status-err"></span><span class="cfg-status-text cfg-status-err">Not set</span>';
        toast('Access key cleared', 'success');
    },

    async save() {
        const provider = document.getElementById('cfg-provider')?.value || 'ollama';
        const url = document.getElementById('cfg-url')?.value || '';
        const model = document.getElementById('cfg-model')?.value || '';
        const cloudUrl = document.getElementById('cfg-cloud-url')?.value || '';
        const cloudKey = document.getElementById('cfg-cloud-key')?.value || '';
        const cloudModel = document.getElementById('cfg-cloud-model')?.value || '';
        try {
            const payload = { ai_provider: provider, ollama_base_url: url, ollama_model: model };
            if (provider === 'cloud') {
                payload.cloud_base_url = cloudUrl;
                // Send key ONLY if user typed a new one — blank keeps the saved key.
                if (cloudKey.trim()) payload.cloud_api_key = cloudKey.trim();
                payload.cloud_model = cloudModel;
            }
            await Api.saveConfig(payload);
            toast('Config saved', 'success');
        } catch (e) { toast(e.message, 'error'); }
    },
};

// ─────────────────────────────────────────────
// RESULT DETAIL — full page view (shareable URL)
// ─────────────────────────────────────────────
const ResultDetail = {
    async load(resultId, projectId) {
        const container = document.getElementById('result-detail-content');
        container.innerHTML = '<div class="empty-state-sm">Loading result...</div>';
        document.getElementById('topbar-title').textContent = 'Test Result';

        // Set back button
        const backBtn = document.getElementById('result-back-btn');
        if (projectId) {
            backBtn.onclick = () => App.navigate('workspace', projectId);
        } else {
            backBtn.onclick = () => App.navigate('results');
        }

        try {
            const { data } = await Api.getTestResult(resultId);
            this.render(data);
        } catch (e) {
            container.innerHTML = `<div class="empty-state-sm" style="color:var(--danger)">Failed to load: ${e.message}</div>`;
        }
    },

    render(data) {
        const container = document.getElementById('result-detail-content');
        const result = data.result || data;
        const steps = result.steps || [];
        const hasProcessLog = !!(result.processLog || '').trim();

        // Header summary
        const status = result.status || 'blocked';
        const dur = result.duration ? `${(result.duration / 1000).toFixed(1)}s` : '—';
        const runner = result.runner === 'graph' ? 'Graph' : result.runner === 'claude-browser' ? 'Standard' : result.runner || '—';
        const tokens = result.totalTokens
            ? (result.inputTokens && result.outputTokens
                ? `${result.totalTokens.toLocaleString()} (${result.inputTokens.toLocaleString()} in / ${result.outputTokens.toLocaleString()} out)`
                : result.totalTokens.toLocaleString())
            : '—';
        const date = result.createdAt ? new Date(result.createdAt).toLocaleString() : result.executedAt ? new Date(result.executedAt).toLocaleString() : '—';

        const tcId = (result.testCaseId || '').toString();
        const projId = (result.projectId || '').toString();
        const resultId = (result._id || '').toString();
        const rerunMode = result.runner === 'graph' ? 'graph' : 'standard';

        let html = `<div class="result-detail-header">
            <div class="result-detail-title">
                <span class="result-badge ${status}" style="font-size:12px;padding:4px 12px">${status.toUpperCase()}</span>
                <h2 style="color:#fff;font-size:18px;font-weight:700;margin-left:12px">${esc(result.testCaseName || 'Test Run')}</h2>
                ${tcId && projId ? `<button class="btn btn-sm btn-primary" style="margin-left:16px" onclick="ResultDetail.rerun('${tcId}','${projId}','${rerunMode}',this)">▶ Re-run</button>` : ''}
                ${resultId && result.logFile ? `<button class="btn btn-sm btn-ghost" style="margin-left:8px" onclick="window.open('/api/run/log/${resultId}','_blank')" title="Opens the full server-side run log in a new tab">📄 View Run Log</button>` : ''}
                ${resultId ? `<button class="btn btn-sm btn-danger-outline" style="margin-left:8px" onclick="ResultDetail.delete('${resultId}','${projId}',this)">🗑 Delete</button>` : ''}
            </div>
            <div class="result-detail-meta">
                <span>Duration: <strong>${dur}</strong></span>
                <span>Runner: <strong>${runner}</strong></span>
                <span>Tokens: <strong>${tokens}</strong></span>
                <span>Date: <strong>${date}</strong></span>
            </div>
        </div>`;

        // Tabs
        const tabClick = `this.parentElement.querySelectorAll('.result-tab').forEach(t=>t.classList.remove('active'));this.classList.add('active');this.parentElement.parentElement.querySelectorAll('.result-tab-content').forEach(c=>c.style.display='none');`;
        html += `<div class="result-tabs">
            <button class="result-tab active" onclick="${tabClick}document.getElementById('rtab-steps').style.display='block'">Steps (${steps.length})</button>
            <button class="result-tab" onclick="${tabClick}document.getElementById('rtab-report').style.display='block'">Report</button>
            ${hasProcessLog ? `<button class="result-tab" onclick="${tabClick}document.getElementById('rtab-log').style.display='block'">AI Log</button>` : ''}
        </div>`;

        // Steps
        let stepsHtml = '<div class="result-steps-detail">';
        steps.forEach(s => {
            const cls = s.status === 'pass' ? 'pass' : s.status === 'adapted' ? 'adapted' : s.status === 'fail' ? 'fail' : 'blocked';
            const icon = s.status === 'pass' ? '✅' : s.status === 'adapted' ? '🔄' : s.status === 'fail' ? '❌' : '⏸️';
            const stepDur = s.durationMs > 0 ? `<span class="result-step-duration">${s.durationMs >= 1000 ? (s.durationMs / 1000).toFixed(1) + 's' : s.durationMs + 'ms'}</span>` : '';
            stepsHtml += `<div class="result-step-row ${cls}"><span class="result-step-seq">${s.seq}.</span><span class="result-step-badge ${cls}">${icon} ${(s.status || 'blocked').toUpperCase()}</span><span class="result-step-note">${esc(s.note || '')}</span>${stepDur}`;
            if (s.screenshot) stepsHtml += `<div class="result-step-screenshot"><a href="${s.screenshot}" target="_blank"><img src="${s.screenshot}" alt="Step ${s.seq}"></a></div>`;
            stepsHtml += '</div>';
        });
        stepsHtml += '</div>';
        html += `<div id="rtab-steps" class="result-tab-content" style="display:block">${stepsHtml}</div>`;

        const md = data.rawMarkdown || result.rawMarkdown || data.content || 'No report.';
        html += `<div id="rtab-report" class="result-tab-content" style="display:none"><div class="result-md">${renderMarkdown(md)}</div></div>`;
        if (hasProcessLog) html += `<div id="rtab-log" class="result-tab-content" style="display:none"><pre class="process-log-viewer">${esc(result.processLog)}</pre></div>`;

        container.innerHTML = html;
    },

    async rerun(testCaseId, projectId, mode, btn) {
        if (btn) { btn.disabled = true; btn.textContent = 'Starting…'; }
        try {
            const res = await Api.runTest(testCaseId, mode);
            const { runId, testCaseName, totalSteps } = res.data;
            sessionStorage.setItem('activeRun', JSON.stringify({ runId, name: testCaseName, totalSteps: totalSteps || 0, projectId, startedAt: Date.now() }));
            App.navigate('workspace', projectId);
        } catch (e) {
            if (btn) { btn.disabled = false; btn.textContent = '▶ Re-run'; }
            toast('Failed to start re-run: ' + e.message, 'error');
        }
    },

    async delete(resultId, projectId, btn) {
        if (!confirm('Delete this test result permanently? Pass rate will be recalculated.')) return;
        if (btn) { btn.disabled = true; btn.textContent = 'Deleting…'; }
        try {
            await Api.deleteResult(resultId);
            toast('Result deleted', 'info');
            if (projectId) App.navigate('workspace', projectId);
            else App.navigate('results');
        } catch (e) {
            if (btn) { btn.disabled = false; btn.textContent = '🗑 Delete'; }
            toast('Failed to delete: ' + e.message, 'error');
        }
    },
};

// ─────────────────────────────────────────────
// GLOBAL RUNS
// ─────────────────────────────────────────────
const GlobalRuns = {
    _interval: null, _open: false, _lastCount: 0,
    _lastRunIds: new Set(),         // runIds seen on previous poll
    _lastRunSnapshot: new Map(),    // runId -> last-seen run info (for failure notification)
    startPolling() {
        this._poll();
        this._interval = setInterval(() => this._poll(), 5000);
        // Request browser notification permission once on first user interaction
        document.addEventListener('click', this._requestNotificationPermission, { once: true });
    },
    _requestNotificationPermission() {
        try { if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission(); } catch {}
    },
    async _poll() {
        try {
            const { data } = await Api.getActiveRuns();
            const indicator = document.getElementById('global-runs-indicator');
            const countEl = document.getElementById('global-runs-count');
            const sidebarEl = document.getElementById('sidebar-active-runs');

            // Snapshot the active set so we can compare on the next tick
            const currentIds = new Set(data.map(r => r.runId));
            // Update snapshots for active runs
            data.forEach(r => this._lastRunSnapshot.set(r.runId, r));

            // Disappeared = present last poll, gone now = just finished
            const disappeared = [...this._lastRunIds].filter(id => !currentIds.has(id));
            for (const id of disappeared) {
                this._handleRunFinished(id);
            }
            this._lastRunIds = currentIds;

            if (data.length < this._lastCount) {
                this._notifyRunsFinished();
            }
            this._lastCount = data.length;

            if (data.length > 0) {
                indicator.style.display = 'flex';
                countEl.textContent = `${data.length} run${data.length > 1 ? 's' : ''} active`;
                if (this._open) this._renderPanel(data);
                // Sidebar footer
                if (sidebarEl) sidebarEl.innerHTML = data.map(r => {
                    const pct = r.totalSteps > 0 ? Math.round((r.currentStep / r.totalSteps) * 100) : 0;
                    return `<div style="padding:6px 4px;font-size:11px;color:var(--text-dim);cursor:pointer" onclick="App.navigate('workspace','${r.projectId}')"><div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.testCaseName || 'Test')}</div><div style="display:flex;height:3px;border-radius:2px;overflow:hidden;background:var(--border);margin-top:4px"><div style="width:${pct}%;background:var(--primary-light)"></div></div></div>`;
                }).join('');
            } else {
                indicator.style.display = 'none';
                if (this._open) this._close();
                if (sidebarEl) sidebarEl.innerHTML = '';
            }
        } catch {}
    },

    // A specific run finished — fetch its outcome and surface a notification
    // (popup + toast + browser push) if it failed.
    async _handleRunFinished(runId) {
        try {
            const { data: run } = await Api.getRunStatus(runId);
            const snap = this._lastRunSnapshot.get(runId);
            const testName = (run && run.testCaseName) || (snap && snap.testCaseName) || 'Test';
            // Status surface — runs in run-manager set 'completed' for natural finish;
            // result.status carries pass/fail/blocked. For failed runs, also 'rate_limited' / 'error'.
            const finalStatus = (run && (run.result?.status || run.status)) || 'unknown';
            this._lastRunSnapshot.delete(runId);
            if (['fail', 'blocked', 'error', 'cancelled'].includes(finalStatus)) {
                const label = finalStatus === 'fail' ? 'FAILED' : finalStatus.toUpperCase();
                const summary = run?.result?.summary || run?.summary || '';
                const resultId = run?.resultId || run?.result?.resultId || null;
                const tcId = run?.testCaseId || (snap && snap.testCaseId) || null;
                const projId = run?.projectId || (snap && snap.projectId) || null;
                FailAlert.show({ label, testName, summary, resultId, tcId, projId });
                toast(`${label}: ${testName}`, 'error');
                this._pushBrowserNotification(`${label}: ${testName}`, summary || 'Open the dashboard for details');
            } else if (finalStatus === 'pass') {
                toast(`PASSED: ${testName}`, 'success');
                this._pushBrowserNotification(`PASSED: ${testName}`, 'The test completed successfully');
            }
        } catch {}
    },

    _pushBrowserNotification(title, body) {
        try {
            if (!('Notification' in window)) return;
            if (Notification.permission !== 'granted') return;
            if (document.visibilityState === 'visible') return; // already looking at the app
            const n = new Notification(title, { body, tag: 'ai-qa-fail', icon: '/ui/favicon.ico' });
            setTimeout(() => { try { n.close(); } catch {} }, 8000);
        } catch {}
    },

    // When a run finishes, refresh whatever page the user is currently looking at
    // so they see new results without manually reloading.
    _notifyRunsFinished() {
        const activePage = document.querySelector('.page-section:not([style*="display:none"]):not([style*="display: none"])');
        const pageId = activePage?.id || '';
        try {
            if (pageId === 'page-dashboard' && typeof Dashboard !== 'undefined') {
                Dashboard.load();
            } else if (pageId === 'page-results' && typeof Results !== 'undefined') {
                Results.load();
            } else if (pageId === 'page-workspace' && typeof Workspace !== 'undefined' && Workspace.projectId) {
                Workspace._refreshResults();
                Workspace._loadAnalytics && Workspace._loadAnalytics();
            }
        } catch {}
    },
    toggle() {
        if (this._open) { this._close(); return; }
        this._open = true;
        document.getElementById('global-runs-panel').style.display = 'block';
        this._poll();
        setTimeout(() => document.addEventListener('click', this._outsideClick), 10);
    },
    _outsideClick(e) {
        if (!document.getElementById('global-runs-panel').contains(e.target) && !document.getElementById('global-runs-indicator').contains(e.target)) GlobalRuns._close();
    },
    _close() { this._open = false; document.getElementById('global-runs-panel').style.display = 'none'; document.removeEventListener('click', this._outsideClick); },
    _renderPanel(runs) {
        document.getElementById('global-runs-panel').innerHTML = runs.map(r => {
            const pct = r.totalSteps > 0 ? Math.round((r.currentStep / r.totalSteps) * 100) : 0;
            const elapsed = Math.floor((Date.now() - new Date(r.startedAt).getTime()) / 1000);
            return `<div class="global-run-item" onclick="GlobalRuns._goToRun('${r.runId}','${r.projectId}')"><div class="global-run-info"><span class="global-run-name">${esc(r.testCaseName || 'Test')}</span><span class="global-run-meta">step ${r.currentStep}/${r.totalSteps} · ${elapsed}s</span></div><div class="global-run-progress"><div class="global-run-progress-fill" style="width:${pct}%"></div></div><button class="global-run-cancel" onclick="event.stopPropagation();GlobalRuns._cancel('${r.runId}')">✕</button></div>`;
        }).join('');
    },
    async _cancel(runId) { try { await Api.cancelRun(runId); } catch {} this._poll(); },
    _goToRun(runId, projectId) {
        this._close();
        if (projectId && projectId !== 'adhoc') {
            App.navigate('workspace', projectId);
            setTimeout(() => Workspace._reconnectToRun(runId), 500);
        }
    },
};

// ─────────────────────────────────────────────
// QUEUE STATUS — Regression queue pause/resume tracker
// ─────────────────────────────────────────────
const QueueStatus = {
    _queueId: null,
    _projectId: null,
    _sse: null,
    _state: null,
    _countdownTimer: null,
    // Live terminal for the currently-running queue test
    _runSse: null,
    _runId: null,
    _runTestName: '',
    _termCollapsed: false,

    start(queueId, projectId) {
        this._queueId = queueId;
        this._projectId = projectId;
        sessionStorage.setItem('activeQueue', JSON.stringify({ queueId, projectId }));
        this._openStream();
    },

    _openStream() {
        if (this._sse) try { this._sse.close(); } catch {}
        this._sse = new EventSource(Api.withKey(`/api/queue/stream/${this._queueId}`));
        this._sse.onmessage = (ev) => {
            try { this._onEvent(JSON.parse(ev.data)); } catch {}
        };
        this._sse.onerror = () => {};
    },

    _onEvent(ev) {
        if (ev.type === 'snapshot' || ev.type === 'queue_started') {
            this._state = { ...ev };
            // Reconnect-time: if a run was already active when we loaded the
            // page, snap the terminal pane to it.
            if (ev.currentRunId) this._attachRunTerminal(ev.currentRunId, ev.currentTestCase || '');
        } else if (ev.type === 'queue_test_started') {
            // New per-test event — tells us the runId of the test that just started
            this._attachRunTerminal(ev.runId, ev.testCaseName || '');
        } else if (ev.type === 'queue_progress') {
            this._state = { ...(this._state || {}), ...ev, status: 'running' };
        } else if (ev.type === 'queue_paused') {
            this._state = { ...(this._state || {}), ...ev, status: 'paused' };
            toast(`Queue paused — token limit hit. Resumes at ${new Date(ev.resetAt).toLocaleTimeString()}`, 'warning');
        } else if (ev.type === 'queue_resumed') {
            this._state = { ...(this._state || {}), status: 'running', resetAt: null };
            toast('Queue resumed', 'info');
        } else if (ev.type === 'queue_completed') {
            this._state = { ...(this._state || {}), ...ev, status: 'completed' };
            const passed = (ev.completed || []).filter(c => c.status === 'pass').length;
            toast(`Regression queue done: ${passed}/${(ev.completed || []).length} passed`, 'info');
            this._cleanupAfter(8000);
        } else if (ev.type === 'queue_cancelled') {
            this._state = { ...(this._state || {}), status: 'cancelled' };
            this._cleanupAfter(4000);
        } else if (ev.type === 'queue_failed') {
            this._state = { ...(this._state || {}), ...ev, status: 'failed' };
            toast('Queue failed — rate limit kept recurring', 'error');
            this._cleanupAfter(8000);
        }
        this._render();
    },

    _render() {
        const slot = document.getElementById('queue-status');
        if (!slot) return;
        const s = this._state;
        if (!s) { slot.innerHTML = ''; return; }

        const done = (s.completed && Array.isArray(s.completed)) ? s.completed.length : (s.completed || 0);
        const total = s.total || 0;
        const cur = s.currentTestCase || s.nextTestCase || '';
        let body = '';

        if (s.status === 'paused') {
            body = `
                <div class="queue-block queue-paused">
                    <div class="queue-head">⏸ Queue paused</div>
                    <div class="queue-sub">Token limit hit · ${done}/${total} done</div>
                    <div class="queue-countdown" id="queue-countdown" data-reset="${s.resetAt || 0}">resumes…</div>
                    <button class="queue-cancel-btn" onclick="QueueStatus.cancel()">Cancel queue</button>
                </div>`;
            this._startCountdown();
        } else if (s.status === 'running') {
            const pct = total > 0 ? Math.round((done / total) * 100) : 0;
            body = `
                <div class="queue-block queue-running">
                    <div class="queue-head">▶ Regression queue</div>
                    <div class="queue-sub">${done}/${total} done${cur ? ` · ${esc(cur)}` : ''}</div>
                    <div class="queue-bar"><div class="queue-bar-fill" style="width:${pct}%"></div></div>
                    <button class="queue-cancel-btn" onclick="QueueStatus.cancel()">Cancel queue</button>
                </div>`;
            this._stopCountdown();
        } else if (s.status === 'completed' || s.status === 'cancelled' || s.status === 'failed') {
            const label = s.status === 'completed' ? '✓ Queue complete' : s.status === 'failed' ? '✕ Queue failed' : '⏹ Queue cancelled';
            body = `<div class="queue-block queue-done"><div class="queue-head">${label}</div><div class="queue-sub">${done}/${total} processed</div></div>`;
            this._stopCountdown();
        }
        slot.innerHTML = body;
    },

    _startCountdown() {
        this._stopCountdown();
        const tick = () => {
            const el = document.getElementById('queue-countdown');
            if (!el) return;
            const resetAt = parseInt(el.dataset.reset || '0', 10);
            if (!resetAt) { el.textContent = 'resumes shortly…'; return; }
            const remaining = resetAt - Date.now();
            if (remaining <= 0) { el.textContent = 'resuming…'; return; }
            const h = Math.floor(remaining / 3600000);
            const m = Math.floor((remaining % 3600000) / 60000);
            const timeStr = new Date(resetAt).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
            el.textContent = `resumes in ${h}h ${m}m (${timeStr})`;
        };
        tick();
        this._countdownTimer = setInterval(tick, 30000);
    },

    _stopCountdown() {
        if (this._countdownTimer) { clearInterval(this._countdownTimer); this._countdownTimer = null; }
    },

    async cancel() {
        if (!this._queueId) return;
        if (!confirm('Cancel the regression queue?')) return;
        try { await Api.cancelQueue(this._queueId); } catch {}
    },

    _cleanupAfter(ms) {
        setTimeout(() => {
            if (this._sse) { try { this._sse.close(); } catch {} this._sse = null; }
            this._detachRunTerminal();
            this._stopCountdown();
            sessionStorage.removeItem('activeQueue');
            this._queueId = null;
            this._state = null;
            this._render();
        }, ms);
    },

    // ── Live Claude terminal pane for the currently-running queue test ──
    _attachRunTerminal(runId, testName) {
        if (!runId || runId === this._runId) return; // already attached to this run
        this._detachRunTerminal();                   // close prior run's stream
        this._runId = runId;
        this._runTestName = testName || '';
        this._showRunTerminal();
        const src = new EventSource(Api.withKey(`/api/run/stream/${runId}`));
        this._runSse = src;
        src.addEventListener('log', (e) => {
            try { const ev = JSON.parse(e.data); if (ev.text) this._appendQueueTerm(ev.text); } catch {}
        });
        src.addEventListener('complete', (e) => {
            try {
                const ev = JSON.parse(e.data);
                this._appendQueueTerm(`\n$ ── Test completed (${ev.status || ''}) ──`);
                if (['fail', 'blocked', 'error'].includes(ev.status)) {
                    FailAlert.show({ label: (ev.status || 'FAILED').toUpperCase(), testName: this._runTestName, summary: ev.summary || '', resultId: ev.resultId || null, tcId: null, projId: this._projectId });
                }
            } catch {}
        });
        src.addEventListener('error', (e) => {
            try {
                const ev = typeof e.data === 'string' ? { message: e.data } : JSON.parse(e.data);
                this._appendQueueTerm(`\n$ ── Test error (${ev.message || ev.status || 'error'}) ──`);
                FailAlert.show({ label: 'ERROR', testName: this._runTestName, summary: ev.message || '', resultId: null, tcId: null, projId: this._projectId });
            } catch {}
        });
        src.onerror = () => {};
    },
    _detachRunTerminal() {
        if (this._runSse) { try { this._runSse.close(); } catch {} this._runSse = null; }
        this._runId = null;
        const panel = document.getElementById('queue-terminal-panel');
        if (panel) panel.style.display = 'none';
    },
    _showRunTerminal() {
        const panel = document.getElementById('queue-terminal-panel');
        if (!panel) return;
        const collapsedAttr = this._termCollapsed ? 'collapsed' : '';
        panel.className = collapsedAttr;
        panel.style.display = 'block';
        panel.innerHTML = `
            <div class="qterm-head" onclick="QueueStatus._toggleTerm(event)">
                <div class="qterm-head-left">
                    <span class="qterm-dot"></span>
                    <span class="qterm-name">${esc(this._runTestName || 'Test')}</span>
                    <span class="qterm-meta">live Ollama output</span>
                </div>
                <div class="qterm-head-right">
                    <button class="qterm-toggle" onclick="event.stopPropagation();QueueStatus._toggleTerm()">${this._termCollapsed ? 'expand' : 'collapse'}</button>
                    <button class="qterm-close" onclick="event.stopPropagation();QueueStatus._detachRunTerminal()">✕</button>
                </div>
            </div>
            <div class="qterm-body" id="qterm-body"></div>`;
    },
    _appendQueueTerm(text) {
        // First log of a new test — refresh the header (test name may have updated)
        const body = document.getElementById('qterm-body');
        if (!body) { this._showRunTerminal(); return this._appendQueueTerm(text); }
        let cls = '';
        if (text.startsWith('$')) cls = 'term-cmd';
        else if (/\*\*PASS\*\*/i.test(text)) cls = 'term-pass';
        else if (/\*\*ADAPTED\*\*/i.test(text)) cls = 'term-adapted';
        else if (/\*\*FAIL\*\*/i.test(text)) cls = 'term-fail';
        if (cls) { const s = document.createElement('span'); s.className = cls; s.textContent = text + '\n'; body.appendChild(s); }
        else { body.appendChild(document.createTextNode(text + '\n')); }
        // Cap buffer at ~800 lines to avoid runaway DOM growth
        while (body.childNodes.length > 800) body.removeChild(body.firstChild);
        body.scrollTop = body.scrollHeight;
    },
    _toggleTerm() {
        this._termCollapsed = !this._termCollapsed;
        const panel = document.getElementById('queue-terminal-panel');
        if (panel) panel.classList.toggle('collapsed', this._termCollapsed);
        const btn = panel?.querySelector('.qterm-toggle');
        if (btn) btn.textContent = this._termCollapsed ? 'expand' : 'collapse';
    },

    reconnect() {
        const saved = sessionStorage.getItem('activeQueue');
        if (!saved) return;
        try {
            const { queueId, projectId } = JSON.parse(saved);
            if (!queueId) return;
            Api.getQueue(queueId).then(({ data }) => {
                if (!data || data.status === 'completed' || data.status === 'cancelled' || data.status === 'failed') {
                    sessionStorage.removeItem('activeQueue');
                    return;
                }
                this._queueId = queueId;
                this._projectId = projectId;
                this._state = data;
                this._openStream();
                this._render();
            }).catch(() => sessionStorage.removeItem('activeQueue'));
        } catch { sessionStorage.removeItem('activeQueue'); }
    },
};

// ─────────────────────────────────────────────
// THEME — Dark / Light switcher
// ─────────────────────────────────────────────
const Theme = {
    init() {
        const saved = localStorage.getItem('theme') || 'dark';
        this.set(saved, true);
    },
    set(theme, init = false) {
        if (theme === 'light') {
            document.body.classList.add('light');
        } else {
            document.body.classList.remove('light');
        }
        localStorage.setItem('theme', theme);
        // Update switcher buttons
        document.querySelectorAll('.theme-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.theme === theme);
        });
    },
};

// ─────────────────────────────────────────────
// MODAL + TOAST + UTILS
// ─────────────────────────────────────────────
function openModal(title, body, footer) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body-content').innerHTML = body;
    document.getElementById('modal-footer-actions').innerHTML = footer || '';
    document.getElementById('modal').style.display = 'flex';
    setTimeout(() => { const inp = document.querySelector('#modal-body-content input, #modal-body-content textarea'); if (inp) inp.focus(); }, 50);
}
function closeModal() { document.getElementById('modal').style.display = 'none'; document.getElementById('modal-body-content').innerHTML = ''; }

function toast(msg, type = 'info') {
    const container = document.querySelector('.toast-container');
    const el = document.createElement('div'); el.className = `toast toast-${type}`;
    el.textContent = msg; container.appendChild(el);
    setTimeout(() => el.classList.add('visible'), 10);
    setTimeout(() => { el.classList.remove('visible'); setTimeout(() => el.remove(), 300); }, 3500);
}

// Prominent failure popup — shown top-center for ANY test that ends in
// fail/blocked/error/cancelled. Stacks if multiple alerts fire in quick
// succession (bulk regression run). Auto-dismisses after 30s (paused on hover).
const FailAlert = {
    _maxStack: 5,
    _audio: null,
    _initAudio() {
        if (this._audio !== null) return this._audio;
        // Tiny built-in beep — uses WebAudio so we don't ship a sound file.
        try {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!Ctx) return (this._audio = false);
            this._audio = new Ctx();
        } catch { this._audio = false; }
        return this._audio;
    },
    _beep() {
        const ctx = this._initAudio();
        if (!ctx) return;
        try {
            if (ctx.state === 'suspended') ctx.resume();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain); gain.connect(ctx.destination);
            osc.type = 'sine'; osc.frequency.value = 660;
            gain.gain.setValueAtTime(0.0001, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.32);
            osc.start(); osc.stop(ctx.currentTime + 0.34);
        } catch {}
    },
    show({ label, testName, summary, resultId, tcId, projId }) {
        const stack = document.getElementById('fail-alert-stack');
        if (!stack) return;
        // Cap stack — drop the oldest if we'd exceed
        while (stack.children.length >= this._maxStack) stack.firstChild.remove();
        const id = 'fa-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
        const viewBtn = resultId
            ? `<a class="btn btn-sm btn-primary" href="#result/${resultId}" onclick="FailAlert._dismiss('${id}')">View result</a>`
            : '';
        const rerunBtn = (tcId && projId)
            ? `<button class="btn btn-sm btn-ghost" onclick="FailAlert._rerun('${id}','${tcId}','${projId}')">▶ Re-run</button>`
            : '';
        const el = document.createElement('div');
        el.className = 'fail-alert'; el.id = id;
        el.innerHTML = `
            <div class="fail-alert-head">
                <span class="fail-alert-icon">❌</span>
                <span class="fail-alert-label">${esc(label || 'FAILED')}</span>
                <button class="fail-alert-dismiss" onclick="FailAlert._dismiss('${id}')" title="Dismiss">✕</button>
            </div>
            <div class="fail-alert-body">
                <div class="fail-alert-name">${esc(testName || 'Test')}</div>
                ${summary ? `<div class="fail-alert-summary">${esc(summary)}</div>` : ''}
            </div>
            <div class="fail-alert-actions">
                ${viewBtn}
                ${rerunBtn}
                <button class="btn btn-sm btn-ghost" onclick="FailAlert._dismiss('${id}')">Dismiss</button>
            </div>
            <div class="fail-alert-progress"></div>`;
        stack.appendChild(el);
        // Trigger entry animation
        requestAnimationFrame(() => el.classList.add('visible'));
        // Auto-dismiss after the CSS countdown finishes (~30s + 200ms buffer)
        const timer = setTimeout(() => this._dismiss(id), 30200);
        // Cancel timer if dismissed early
        el.dataset.timer = String(timer);
        this._beep();
    },
    _dismiss(id) {
        const el = document.getElementById(id);
        if (!el) return;
        if (el.dataset.timer) clearTimeout(parseInt(el.dataset.timer, 10));
        el.classList.remove('visible');
        setTimeout(() => el.remove(), 260);
    },
    _rerun(id, tcId, projId) {
        this._dismiss(id);
        try {
            App.navigate('workspace', projId);
            setTimeout(async () => {
                try {
                    const res = await Api.runTest(tcId, 'graph');
                    const { runId, testCaseName, totalSteps } = res.data;
                    Workspace._startProgress(runId, testCaseName || 'Re-run', totalSteps || 0);
                } catch (e) { toast(e.message, 'error'); }
            }, 300);
        } catch (e) { toast(e.message, 'error'); }
    },
};

function esc(str) { return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
function escAttr(str) { return String(str ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }

function renderMarkdown(md) {
    if (typeof Markdown !== 'undefined') return Markdown.render(md);
    // Safe fallback: escape HTML first, then apply simple markdown
    const safe = String(md || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    return safe
        .replace(/^#####\s(.+)$/gm, '<h5>$1</h5>')
        .replace(/^####\s(.+)$/gm, '<h4>$1</h4>')
        .replace(/^###\s(.+)$/gm, '<h3>$1</h3>')
        .replace(/^##\s(.+)$/gm, '<h2>$1</h2>')
        .replace(/^#\s(.+)$/gm, '<h1>$1</h1>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>');
}
