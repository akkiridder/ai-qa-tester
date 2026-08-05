let recordingState = {
    active: false,
    tabId: null,
    steps: [],
    startUrl: '',
    startTime: null,
};

async function saveState() {
    try {
        await chrome.storage.session.set({ recordingState });
    } catch {
        await chrome.storage.local.set({ recordingState });
    }
}

async function loadState() {
    try {
        const data = await chrome.storage.session.get('recordingState');
        if (data.recordingState) recordingState = data.recordingState;
    } catch {
        const data = await chrome.storage.local.get('recordingState');
        if (data.recordingState) recordingState = data.recordingState;
    }
}

loadState();

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    loadState().then(() => {
        handleMessage(msg, sender, sendResponse);
    });
    return true;
});

function handleMessage(msg, sender, sendResponse) {
    if (msg.type === 'GET_STATE') {
        sendResponse(recordingState);
        return;
    }

    if (msg.type === 'START_RECORDING') {
        recordingState = {
            active: true,
            tabId: msg.tabId,
            steps: [],
            startUrl: msg.url || '',
            startTime: Date.now(),
        };
        recordingState.steps.push({
            seq: 1,
            action: 'navigate',
            target: msg.url || '',
            description: `Navigate to ${msg.url}`,
            value: null,
            verify: 'Page loads successfully',
            timestamp: Date.now(),
        });
        saveState();
        chrome.tabs.sendMessage(msg.tabId, { type: 'RECORDING_STARTED' }).catch(() => {});
        chrome.alarms?.create('keepalive', { periodInMinutes: 0.33 });
        sendResponse({ success: true });
        return;
    }

    if (msg.type === 'STOP_RECORDING') {
        recordingState.active = false;
        saveState();
        chrome.alarms?.clear('keepalive');
        if (recordingState.tabId) {
            chrome.tabs.sendMessage(recordingState.tabId, { type: 'RECORDING_STOPPED' }).catch(() => {});
        }
        sendResponse({ success: true, steps: recordingState.steps });
        return;
    }

    if (msg.type === 'ADD_STEP') {
        if (!recordingState.active) { sendResponse({ success: false }); return; }
        const step = {
            seq: recordingState.steps.length + 1,
            action: msg.step.action,
            target: msg.step.target,
            description: msg.step.description,
            value: msg.step.value || null,
            verify: msg.step.verify || null,
            timestamp: Date.now(),
        };
        recordingState.steps.push(step);
        saveState();
        sendResponse({ success: true, stepCount: recordingState.steps.length });
        return;
    }

    if (msg.type === 'CLEAR_STEPS') {
        recordingState.steps = [];
        recordingState.active = false;
        recordingState.tabId = null;
        saveState();
        chrome.alarms?.clear('keepalive');
        sendResponse({ success: true });
        return;
    }

    if (msg.type === 'UPDATE_STEPS') {
        recordingState.steps = msg.steps;
        saveState();
        sendResponse({ success: true });
        return;
    }
}

chrome.webNavigation?.onCompleted?.addListener(async (details) => {
    await loadState();
    if (!recordingState.active || details.frameId !== 0) return;
    if (details.tabId !== recordingState.tabId) return;

    const notifyTab = () => {
        chrome.tabs.sendMessage(details.tabId, { type: 'RECORDING_STARTED' }).catch(() => {
            setTimeout(() => {
                chrome.tabs.sendMessage(details.tabId, { type: 'RECORDING_STARTED' }).catch(() => {
                    setTimeout(() => {
                        chrome.tabs.sendMessage(details.tabId, { type: 'RECORDING_STARTED' }).catch(() => {});
                    }, 1500);
                });
            }, 800);
        });
    };
    setTimeout(notifyTab, 300);

    const lastStep = recordingState.steps[recordingState.steps.length - 1];
    if (lastStep && lastStep.action === 'navigate' && lastStep.target === details.url) return;
    const isClickNav = lastStep && lastStep.action === 'click' && (Date.now() - (lastStep.timestamp || 0)) < 1500;

    let pathDesc;
    try {
        const url = new URL(details.url);
        pathDesc = url.pathname + (url.search || '');
    } catch {
        pathDesc = details.url;
    }

    recordingState.steps.push({
        seq: recordingState.steps.length + 1,
        action: 'navigate',
        target: details.url,
        description: isClickNav
            ? `Page navigated to ${pathDesc} (after click)`
            : `Page navigated to ${pathDesc}`,
        value: null,
        verify: 'Page loads successfully',
        timestamp: Date.now(),
    });
    saveState();
});

chrome.alarms?.onAlarm?.addListener(async (alarm) => {
    if (alarm.name === 'keepalive') {
        await loadState();
        if (!recordingState.active) {
            chrome.alarms.clear('keepalive');
            return;
        }
        saveState();
    }
});

chrome.tabs.onRemoved?.addListener(async (tabId) => {
    await loadState();
    if (recordingState.active && recordingState.tabId === tabId) {
        recordingState.active = false;
        saveState();
        chrome.alarms?.clear('keepalive');
    }
});
