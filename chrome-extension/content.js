let isRecording = false;
let overlay = null;
let lastStep = null;
let inputTimers = new Map();
let scrollTimer = null;
let scrollStartY = 0;
let scrollRecorded = false;
let mutationObserver = null;

function describeElement(el) {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    if (el.placeholder) return el.placeholder;
    if ((el.tagName === 'BUTTON' || el.tagName === 'A') && el.textContent.trim().length < 60) {
        return el.textContent.trim();
    }
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
        const id = el.id;
        if (id) {
            const label = document.querySelector(`label[for="${id}"]`);
            if (label) return label.textContent.trim();
        }
        const parentLabel = el.closest('label');
        if (parentLabel) return parentLabel.textContent.replace(el.value || '', '').trim();
        if (el.name) return el.name;
    }
    if (el.title) return el.title;
    if (el.id) return `#${el.id}`;
    if (el.textContent.trim().length < 40 && el.textContent.trim().length > 0) {
        return el.textContent.trim();
    }
    return `${el.tagName.toLowerCase()}${el.className ? '.' + el.className.split(' ')[0] : ''}`;
}

function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return false;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    return true;
}

function getSelector(el) {
    if (el.id) return `#${el.id}`;
    if (el.name) return `[name="${el.name}"]`;
    if (el.getAttribute('data-testid')) return `[data-testid="${el.getAttribute('data-testid')}"]`;
    const path = [];
    let current = el;
    while (current && current !== document.body) {
        let selector = current.tagName.toLowerCase();
        if (current.id) { path.unshift(`#${current.id}`); break; }
        if (current.className && typeof current.className === 'string') {
            const cls = current.className.trim().split(/\s+/).filter(c =>
                !c.startsWith('hover') && !c.startsWith('active') && !c.startsWith('focus')
            )[0];
            if (cls) selector += `.${cls}`;
        }
        const parent = current.parentElement;
        if (parent) {
            const siblings = Array.from(parent.children).filter(c => c.tagName === current.tagName);
            if (siblings.length > 1) {
                const idx = siblings.indexOf(current) + 1;
                selector += `:nth-of-type(${idx})`;
            }
        }
        path.unshift(selector);
        current = current.parentElement;
    }
    return path.join(' > ');
}

function flashElement(el) {
    const orig = el.style.outline;
    el.style.outline = '3px solid #ef4444';
    setTimeout(() => { el.style.outline = orig; }, 500);
}

function showRecordingIndicator() {
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.id = 'ai-qa-recording-indicator';
    overlay.innerHTML = '⏺ Recording';
    overlay.style.cssText = 'position:fixed;top:8px;right:8px;z-index:999999;background:#ef4444;color:#fff;padding:6px 14px;border-radius:20px;font:600 13px/1 system-ui;box-shadow:0 2px 8px rgba(0,0,0,.3);pointer-events:none;transition:opacity 0.3s;';
    document.body.appendChild(overlay);
    let visible = true;
    overlay._pulseTimer = setInterval(() => {
        visible = !visible;
        if (overlay) overlay.style.opacity = visible ? '1' : '0.5';
    }, 1000);
}

function hideRecordingIndicator() {
    if (overlay) {
        clearInterval(overlay._pulseTimer);
        overlay.remove();
        overlay = null;
    }
}

function isDuplicate(step) {
    if (!lastStep) return false;
    if (step.action === lastStep.action && step.target === lastStep.target) {
        if (Date.now() - (lastStep._time || 0) < 1000) return true;
    }
    return false;
}

function recordStep(step) {
    if (isDuplicate(step)) return;
    step._time = Date.now();
    lastStep = step;
    try {
        chrome.runtime.sendMessage({ type: 'ADD_STEP', step }, () => {
            if (chrome.runtime.lastError) {}
        });
    } catch {}
}

function handleClick(e) {
    if (!isRecording) return;
    const el = e.target;
    if (el.id === 'ai-qa-recording-indicator') return;
    if (!isVisible(el)) return;
    if (el.tagName === 'INPUT' && ['text','email','password','search','tel','url','number'].includes(el.type)) return;
    if (el.tagName === 'TEXTAREA') return;

    const dropdownItem = el.closest('[role="option"], [role="menuitem"], [role="listbox"] li, [data-value], .dropdown-item, .select-option, .option, li[data-option-index]');
    if (dropdownItem) {
        flashElement(dropdownItem);
        const optionText = dropdownItem.textContent.trim().substring(0, 80);
        const dropdownParent = dropdownItem.closest('[role="listbox"], [role="menu"], .dropdown-menu, .select-dropdown, ul.options, [class*="dropdown"], [class*="select"]');
        let dropdownName = '';
        if (dropdownParent) {
            const trigger = dropdownParent.previousElementSibling || dropdownParent.parentElement?.querySelector('[role="combobox"], [class*="trigger"], [class*="selected"], button');
            if (trigger) dropdownName = ` from "${describeElement(trigger)}"`;
        }
        recordStep({ action: 'select', target: getSelector(dropdownItem), description: `${optionText}${dropdownName}`, value: optionText });
        return;
    }

    flashElement(el);
    const desc = describeElement(el);
    recordStep({ action: 'click', target: getSelector(el), description: desc });
}

function handleInput(e) {
    if (!isRecording) return;
    const el = e.target;
    if (!el.tagName || (el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA')) return;
    if (el.type === 'checkbox' || el.type === 'radio') return;
    const key = getSelector(el);
    if (inputTimers.has(key)) clearTimeout(inputTimers.get(key));
    inputTimers.set(key, setTimeout(() => {
        inputTimers.delete(key);
        flashElement(el);
        const desc = describeElement(el);
        recordStep({ action: 'type', target: key, description: desc, value: el.value });
    }, 600));
}

function flushInputTimers() {
    for (const [key, timer] of inputTimers) {
        clearTimeout(timer);
        try {
            const el = document.querySelector(key);
            if (el && el.value) {
                const desc = describeElement(el);
                recordStep({ action: 'type', target: key, description: desc, value: el.value });
            }
        } catch {}
    }
    inputTimers.clear();
}

function handleChange(e) {
    if (!isRecording) return;
    const el = e.target;
    if (el.tagName === 'SELECT') {
        flashElement(el);
        const desc = describeElement(el);
        const selectedText = el.options[el.selectedIndex]?.text || el.value;
        recordStep({ action: 'select', target: getSelector(el), description: `${selectedText} from ${desc}`, value: selectedText });
    }
    if (el.type === 'checkbox' || el.type === 'radio') {
        flashElement(el);
        const desc = describeElement(el);
        recordStep({ action: el.checked ? 'check' : 'uncheck', target: getSelector(el), description: desc });
    }
}

function handleSubmit(e) {
    if (!isRecording) return;
    flushInputTimers();
    const form = e.target;
    const desc = form.id || form.action || 'form';
    recordStep({ action: 'submit', target: getSelector(form), description: desc });
}

function handleScroll() {
    if (!isRecording) return;
    if (!scrollRecorded) { scrollStartY = window.scrollY; scrollRecorded = true; }
    if (scrollTimer) clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => {
        const scrollEndY = window.scrollY;
        const delta = scrollEndY - scrollStartY;
        if (Math.abs(delta) < 80) { scrollRecorded = false; return; }
        const direction = delta > 0 ? 'down' : 'up';
        const amount = Math.abs(Math.round(delta));
        let visibleSection = '';
        const headings = document.querySelectorAll('h1, h2, h3, [class*="title"], [class*="heading"]');
        for (const h of headings) {
            const rect = h.getBoundingClientRect();
            if (rect.top >= 0 && rect.top < window.innerHeight / 2 && h.textContent.trim()) {
                visibleSection = ` to "${h.textContent.trim().substring(0, 50)}"`;
                break;
            }
        }
        recordStep({ action: 'scroll', target: 'window', description: `Scroll ${direction} ${amount}px${visibleSection}`, value: `${direction} ${amount}` });
        scrollRecorded = false;
    }, 500);
}

function handleBeforeUnload() {
    if (!isRecording) return;
    flushInputTimers();
    if (scrollTimer) {
        clearTimeout(scrollTimer);
        const scrollEndY = window.scrollY;
        const delta = scrollEndY - scrollStartY;
        if (Math.abs(delta) >= 80) {
            const direction = delta > 0 ? 'down' : 'up';
            const amount = Math.abs(Math.round(delta));
            recordStep({ action: 'scroll', target: 'window', description: `Scroll ${direction} ${amount}px`, value: `${direction} ${amount}` });
        }
        scrollTimer = null;
        scrollRecorded = false;
    }
}

function setupMutationObserver() {
    if (mutationObserver) return;
    mutationObserver = new MutationObserver((mutations) => {
        if (!isRecording) return;
    });
    mutationObserver.observe(document.body, { childList: true, subtree: true });
}

function startListening() {
    isRecording = true;
    lastStep = null;
    showRecordingIndicator();
    document.addEventListener('click', handleClick, true);
    document.addEventListener('input', handleInput, true);
    document.addEventListener('change', handleChange, true);
    document.addEventListener('submit', handleSubmit, true);
    window.addEventListener('scroll', handleScroll, { passive: true });
    window.addEventListener('beforeunload', handleBeforeUnload);
    setupMutationObserver();
}

function stopListening() {
    isRecording = false;
    lastStep = null;
    hideRecordingIndicator();
    document.removeEventListener('click', handleClick, true);
    document.removeEventListener('input', handleInput, true);
    document.removeEventListener('change', handleChange, true);
    document.removeEventListener('submit', handleSubmit, true);
    window.removeEventListener('scroll', handleScroll);
    window.removeEventListener('beforeunload', handleBeforeUnload);
    inputTimers.forEach(t => clearTimeout(t));
    inputTimers.clear();
    if (scrollTimer) { clearTimeout(scrollTimer); scrollTimer = null; }
    if (mutationObserver) { mutationObserver.disconnect(); mutationObserver = null; }
}

chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'RECORDING_STARTED') startListening();
    if (msg.type === 'RECORDING_STOPPED') stopListening();
});

chrome.runtime.sendMessage({ type: 'GET_STATE' }, (state) => {
    if (chrome.runtime.lastError) return;
    if (state && state.active) startListening();
});
