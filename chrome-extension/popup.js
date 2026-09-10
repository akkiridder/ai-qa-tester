const $ = (sel) => document.querySelector(sel);
const serverUrl = () => $('#server-url').value.replace(/\/+$/, '');

let currentSteps = [];
let projects = [];

document.addEventListener('DOMContentLoaded', async () => {
    const stored = await chrome.storage.local.get(['serverUrl']);
    if (stored.serverUrl) $('#server-url').value = stored.serverUrl;

    chrome.runtime.sendMessage({ type: 'GET_STATE' }, (state) => {
        if (state && state.active) {
            showRecordingUI(state.steps.length);
        } else if (state && state.steps && state.steps.length > 0) {
            currentSteps = state.steps;
            showReviewUI();
        }
    });

    loadProjects();

    $('#btn-start').addEventListener('click', startRecording);
    $('#btn-stop').addEventListener('click', stopRecording);
    $('#btn-save').addEventListener('click', saveToProject);
    $('#btn-export').addEventListener('click', exportMarkdown);
    $('#btn-dedup').addEventListener('click', removeDuplicates);
    $('#btn-new-project').addEventListener('click', () => $('#new-project-modal').style.display = 'flex');
    $('#btn-np-cancel').addEventListener('click', () => $('#new-project-modal').style.display = 'none');
    $('#btn-np-save').addEventListener('click', createProject);

    $('#server-url').addEventListener('change', () => {
        chrome.storage.local.set({ serverUrl: $('#server-url').value });
    });
});

async function startRecording() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return toast('No active tab', true);

    chrome.runtime.sendMessage({
        type: 'START_RECORDING',
        tabId: tab.id,
        url: tab.url,
    }, () => {
        showRecordingUI(1);
        chrome.alarms?.create('keepalive', { periodInMinutes: 0.4 });
        pollStepCount();
    });
}

function showRecordingUI(count) {
    $('#btn-start').style.display = 'none';
    $('#btn-stop').style.display = 'block';
    $('#step-counter').style.display = 'block';
    $('#step-count').textContent = count || 0;
    $('#review-section').style.display = 'none';
    $('#status-badge').className = 'badge badge-recording';
    $('#status-badge').textContent = 'Recording';
}

let pollTimer = null;
function pollStepCount() {
    clearInterval(pollTimer);
    pollTimer = setInterval(() => {
        chrome.runtime.sendMessage({ type: 'GET_STATE' }, (state) => {
            if (!state || !state.active) {
                clearInterval(pollTimer);
                return;
            }
            $('#step-count').textContent = state.steps.length;
        });
    }, 1000);
}

function stopRecording() {
    clearInterval(pollTimer);
    chrome.alarms?.clear('keepalive');
    chrome.runtime.sendMessage({ type: 'STOP_RECORDING' }, (resp) => {
        if (resp && resp.steps) {
            currentSteps = resp.steps;
            showReviewUI();
        }
    });
}

function showReviewUI() {
    $('#btn-start').style.display = 'block';
    $('#btn-stop').style.display = 'none';
    $('#step-counter').style.display = 'none';
    $('#review-section').style.display = 'block';
    $('#status-badge').className = 'badge badge-done';
    $('#status-badge').textContent = `${currentSteps.length} Steps`;
    renderSteps();
}

function renderSteps() {
    const list = $('#steps-list');
    list.innerHTML = '';
    currentSteps.forEach((step, i) => {
        const item = document.createElement('div');
        item.className = 'step-item';
        item.innerHTML = `
            <span class="step-seq">${step.seq}</span>
            <span class="step-action ${step.action}">${step.action}</span>
            <span class="step-desc" title="${esc(step.description)}">${esc(step.description)}</span>
            <span class="step-delete" data-idx="${i}" title="Remove step">&times;</span>
        `;
        list.appendChild(item);
    });
    list.querySelectorAll('.step-delete').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const idx = parseInt(e.target.dataset.idx);
            currentSteps.splice(idx, 1);
            currentSteps.forEach((s, i) => s.seq = i + 1);
            chrome.runtime.sendMessage({ type: 'UPDATE_STEPS', steps: currentSteps });
            renderSteps();
        });
    });
}

function esc(str) {
    return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
}

function removeDuplicates() {
    const before = currentSteps.length;
    const deduped = [];
    for (const step of currentSteps) {
        const last = deduped[deduped.length - 1];
        if (last && last.action === step.action && last.target === step.target && last.description === step.description) continue;
        deduped.push(step);
    }
    deduped.forEach((s, i) => s.seq = i + 1);
    currentSteps = deduped;
    chrome.runtime.sendMessage({ type: 'UPDATE_STEPS', steps: currentSteps });
    renderSteps();
    const removed = before - deduped.length;
    if (removed > 0) toast(`Removed ${removed} duplicate steps`);
    else toast('No duplicates found');
}

async function loadProjects() {
    try {
        const resp = await fetch(`${serverUrl()}/api/projects`);
        const data = await resp.json();
        if (data.success && Array.isArray(data.data)) {
            projects = data.data;
            const sel = $('#project-select');
            sel.innerHTML = '<option value="">-- Select Project --</option>';
            projects.forEach(p => {
                sel.innerHTML += `<option value="${p._id || p.id}">${p.name} (${p.url || ''})</option>`;
            });
        }
    } catch {
        $('#project-select').innerHTML = '<option value="">Server not reachable</option>';
    }
}

async function createProject() {
    const name = $('#np-name').value.trim();
    const url = $('#np-url').value.trim();
    if (!name) return toast('Project name is required', true);
    try {
        const resp = await fetch(`${serverUrl()}/api/projects`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, url: url }),
        });
        const data = await resp.json();
        if (data.success && data.data && data.data.id) {
            toast('Project created!');
            $('#new-project-modal').style.display = 'none';
            $('#np-name').value = '';
            $('#np-url').value = '';
            await loadProjects();
            $('#project-select').value = data.data.id;
        } else {
            toast(data.error || 'Failed', true);
        }
    } catch {
        toast('Failed to create project', true);
    }
}

async function saveToProject() {
    const projectId = $('#project-select').value;
    const name = $('#tc-name').value.trim();
    if (!projectId) return toast('Select a project', true);
    if (!name) return toast('Enter a test case name', true);
    if (currentSteps.length === 0) return toast('No steps recorded', true);

    const steps = currentSteps.map(s => ({
        action: s.action.replace(/ ".*"$/, ''),
        target: s.target,
        description: s.description || '',
        value: s.value || '',
        verify: s.verify || ''
    }));

    try {
        const resp = await fetch(`${serverUrl()}/api/projects/${projectId}/test-cases`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, steps }),
        });
        const data = await resp.json();
        if (data.success && data.data && data.data.id) {
            toast('Test case saved!');
            chrome.runtime.sendMessage({ type: 'CLEAR_STEPS' });
            currentSteps = [];
            $('#review-section').style.display = 'none';
            $('#status-badge').className = 'badge badge-idle';
            $('#status-badge').textContent = 'Idle';
            $('#btn-start').style.display = 'block';
            $('#tc-name').value = '';
        } else {
            toast(data.error || 'Failed to save', true);
        }
    } catch {
        toast('Failed to save. Check server URL.', true);
    }
}

function exportMarkdown() {
    if (currentSteps.length === 0) return toast('No steps to export', true);
    const name = $('#tc-name').value.trim() || 'Recorded Test';
    let md = `# ${name}\n\n## STEPS\n`;
    currentSteps.forEach(step => {
        let line = `${step.seq}. ${step.description}`;
        if (step.verify) line += ` → Verify: ${step.verify}`;
        md += line + '\n';
    });
    navigator.clipboard.writeText(md).then(() => toast('Markdown copied!')).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = md;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
        toast('Markdown copied!');
    });
}

function toast(msg, isError = false) {
    const t = $('#toast');
    t.textContent = msg;
    t.className = isError ? 'toast error' : 'toast';
    t.style.display = 'block';
    setTimeout(() => { t.style.display = 'none'; }, 2500);
}
