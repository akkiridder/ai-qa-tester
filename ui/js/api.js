const API_BASE = '/api';

const Api = {
    // Access key for X-API-Key header auth (stored in browser only, never in repo).
    getKey() { try { return localStorage.getItem('aiqa_api_key') || ''; } catch { return ''; } },
    setKey(k) { try { k ? localStorage.setItem('aiqa_api_key', k) : localStorage.removeItem('aiqa_api_key'); } catch {} },
    headers(extra = {}) {
        const h = { 'Content-Type': 'application/json', ...(extra || {}) };
        const k = this.getKey();
        if (k) h['X-API-Key'] = k;
        return h;
    },
    // Query-param variant for EventSource URLs (browsers can't set headers on SSE).
    withKey(url) {
        const k = this.getKey();
        if (!k) return url;
        return url + (url.includes('?') ? '&' : '?') + 'access_key=' + encodeURIComponent(k);
    },
    // Raw fetch with auth headers (for non-/api-wrapper GETs).
    async afetch(url, options = {}) {
        const { headers, ...rest } = options;
        const response = await fetch(url, { ...rest, headers: this.headers(headers) });
        return response.json();
    },
    async request(endpoint, options = {}) {
        try {
            const { headers, ...rest } = options;
            const response = await fetch(`${API_BASE}/${endpoint}`, {
                ...rest,
                headers: this.headers(headers),
            });
            const data = await response.json();
            if (!data.success) {
                if (response.status === 401) {
                    toast('Unauthorized — set your Access Key in Settings', 'error');
                    App.navigate('settings');
                }
                throw new Error(data.error || 'API request failed');
            }
            return data;
        } catch (error) {
            console.error(`API Error [${endpoint}]:`, error);
            throw error;
        }
    },

    // Dashboard
    async getDashboard() {
        return this.request('dashboard');
    },

    // Test Plans
    async getTestPlans() {
        return this.request('test-plans');
    },

    async getTestPlan(filename) {
        return this.request(`test-plans/${encodeURIComponent(filename)}`);
    },

    async saveTestPlan(filename, content) {
        return this.request('test-plans', {
            method: 'POST',
            body: JSON.stringify({ filename, content }),
        });
    },

    async deleteTestPlan(filename) {
        return this.request(`test-plans/${encodeURIComponent(filename)}`, {
            method: 'DELETE',
        });
    },

    // Test Results
    async getTestResults() {
        return this.request('results');
    },

    async getTestResult(id) {
        return this.request(`results/${encodeURIComponent(id)}`);
    },

    async deleteResult(resultId) {
        return this.request(`results/${encodeURIComponent(resultId)}`, {
            method: 'DELETE',
        });
    },

    // Projects
    async getProjects() {
        return this.request('projects');
    },
    async createProject(data) {
        return this.request('projects', { method: 'POST', body: JSON.stringify(data) });
    },
    async getProject(id) {
        return this.request(`projects/${id}`);
    },
    async updateProject(id, data) {
        return this.request(`projects/${id}`, { method: 'PUT', body: JSON.stringify(data) });
    },
    async deleteProject(id) {
        return this.request(`projects/${id}`, { method: 'DELETE' });
    },
    async getProjectDashboard(id) {
        return this.request(`projects/${id}/dashboard`);
    },

    // Test Cases (TinyDB)
    async getTestCases(projectId) {
        return this.request(`projects/${projectId}/test-cases`);
    },
    async createTestCase(projectId, data) {
        return this.request(`projects/${projectId}/test-cases`, { method: 'POST', body: JSON.stringify(data) });
    },
    async getTestCase(id) {
        return this.request(`test-cases/${id}`);
    },
    async updateTestCase(id, data) {
        return this.request(`test-cases/${id}`, { method: 'PUT', body: JSON.stringify(data) });
    },
    async deleteTestCase(id) {
        return this.request(`test-cases/${id}`, { method: 'DELETE' });
    },
    async reorderTestCases(projectId, orderedIds) {
        return this.request(`projects/${projectId}/test-cases/reorder`, { method: 'PUT', body: JSON.stringify({ orderedIds }) });
    },
    async exportTestCase(id) {
        return this.request(`test-cases/${id}/export`);
    },

    // Project Results (TinyDB)
    async getProjectResults(projectId) {
        return this.request(`projects/${projectId}/results`);
    },
    async saveProjectResult(projectId, data) {
        return this.request(`projects/${projectId}/results`, { method: 'POST', body: JSON.stringify(data) });
    },

    async runTest(testCaseId, mode = 'standard', device = 'desktop') {
        return this.request(`run/${testCaseId}`, {
            method: 'POST',
            body: JSON.stringify({ mode, device })
        });
    },

    async runProject(projectId, mode = 'standard', device = 'desktop') {
        return this.request(`run/project/${projectId}`, { 
            method: 'POST',
            body: JSON.stringify({ mode, device })
        });
    },

    async runSelected(projectId, testCaseIds, mode = 'standard', device = 'desktop') {
        return this.request('run/selected', {
            method: 'POST',
            body: JSON.stringify({ projectId, testCaseIds, mode, device })
        });
    },

    async getQueue(queueId) {
        return this.request(`queue/${queueId}`);
    },

    async getActiveQueues() {
        return this.request('queue/active');
    },

    async cancelQueue(queueId) {
        return this.request(`queue/${queueId}/cancel`, { method: 'POST' });
    },

    async runPlan(planFile, url, projectId, mode = 'standard', device = 'desktop') {
        return this.request('run/plan', {
            method: 'POST',
            body: JSON.stringify({ filename: planFile, url, projectId, mode, device }),
        });
    },

    async getRunStatus(runId) {
        return this.request(`run/status/${runId}`);
    },

    async getActiveRuns() {
        return this.request('run/active');
    },

    async cancelRun(runId) {
        return this.request(`run/cancel/${runId}`, { method: 'POST' });
    },

    // Analytics
    async getProjectAnalytics(projectId) {
        return this.request(`projects/${projectId}/analytics`);
    },

    // AI Generation
    async generateAITests(projectId) {
        return this.request(`generate-tests/${projectId}`, { method: 'POST' });
    },

    // Config
    async getConfig() {
        return this.request('config');
    },

    async saveConfig(data) {
        return this.request('config', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },
};
