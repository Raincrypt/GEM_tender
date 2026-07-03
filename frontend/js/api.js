/* ============================================================
   GEM Tender – Centralized API Client  v3.0
   - Fixed: duplicate askAI() bug removed (askAI → /reports/chat, askC3AI → /c3/ask-ai)
   - Added: WebSocket connection helper
   - Added: getVendorRiskProfile, getTenderLifecycle, getKpiSummary, getAiInsights
   ============================================================ */

const API_BASE_URL = (() => {
    let host = window.location.hostname;
    if (!host || host === 'localhost') host = '127.0.0.1';
    if (window.location.port === '8000') return window.location.origin;
    const protocol = window.location.protocol === 'file:' ? 'http:' : window.location.protocol;
    return `${protocol}//${host}:8000`;
})();

class ApiClient {
    /** In-memory request cache: { url -> { timestamp, data } } */
    static _cache = {};

    // ── Auth Helpers ─────────────────────────────────────────
    static getToken() {
        return localStorage.getItem('gem_token');
    }

    static setToken(token) {
        localStorage.setItem('gem_token', token);
    }

    static clearAuth() {
        localStorage.removeItem('gem_token');
        localStorage.removeItem('gem_user');
    }

    static getStoredUser() {
        try {
            const raw = localStorage.getItem('gem_user');
            return raw ? JSON.parse(raw) : null;
        } catch {
            return null;
        }
    }

    static getHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        const token = this.getToken();
        if (token) headers['Authorization'] = `Bearer ${token}`;
        return headers;
    }

    // ── Core Request Method ───────────────────────────────────
    /**
     * @param {string} endpoint  - API path e.g. '/tenders/'
     * @param {object} options   - fetch options (method, body, headers…)
     * @param {number} cacheTTL  - milliseconds to cache (0 = no cache)
     */
    static async request(endpoint, options = {}, cacheTTL = 0) {
        const url = `${API_BASE_URL}${endpoint}`;

        // Return cached data if still fresh
        if (cacheTTL > 0 && this._cache[url]) {
            const { timestamp, data } = this._cache[url];
            if (Date.now() - timestamp < cacheTTL) return data;
        }

        const config = {
            ...options,
            headers: { ...this.getHeaders(), ...(options.headers || {}) }
        };

        let response = await fetch(url, config);

        // Session expired → try silent token refresh before redirecting
        if (response.status === 401 && this.getToken() && !this._refreshing) {
            const refreshed = await this.refreshToken();
            if (refreshed) {
                // Retry the original request with new token
                config.headers = { ...this.getHeaders(), ...(options.headers || {}) };
                response = await fetch(url, config);
            } else {
                this.clearAuth();
                window.location.href = 'index.html';
                return null;
            }
        } else if (response.status === 401) {
            this.clearAuth();
            window.location.href = 'index.html';
            return null;
        }

        let data;
        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            data = await response.json();
        } else {
            data = { message: await response.text() };
        }

        if (!response.ok) {
            throw new Error(data.detail || data.message || `HTTP ${response.status}`);
        }

        // Cache successful GET responses
        const method = (options.method || 'GET').toUpperCase();
        if (cacheTTL > 0 && method === 'GET') {
            this._cache[url] = { timestamp: Date.now(), data };
        }

        return data;
    }

    /** Invalidate a cached URL (or all cache if no url given) */
    static invalidateCache(url = null) {
        if (url) delete this._cache[`${API_BASE_URL}${url}`];
        else this._cache = {};
    }

    // ── Authentication ────────────────────────────────────────
    static _refreshing = false;

    static async login(username, password) {
        const formData = new URLSearchParams();
        formData.append('username', username);
        formData.append('password', password);

        const response = await fetch(`${API_BASE_URL}/token`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Login Failed');

        this.setToken(data.access_token);
        localStorage.setItem('gem_user', JSON.stringify(data.user));
        return data.user;
    }

    /** Silently refresh the JWT token before it expires */
    static async refreshToken() {
        if (this._refreshing) return false;
        this._refreshing = true;
        try {
            const response = await fetch(`${API_BASE_URL}/token/refresh`, {
                method: 'POST',
                headers: this.getHeaders()
            });
            if (response.ok) {
                const data = await response.json();
                this.setToken(data.access_token);
                if (data.user) localStorage.setItem('gem_user', JSON.stringify(data.user));
                return true;
            }
            return false;
        } catch {
            return false;
        } finally {
            this._refreshing = false;
        }
    }

    // ── Tenders ───────────────────────────────────────────────
    static async getTenders(status = '') {
        const query = status ? `?status=${encodeURIComponent(status)}` : '';
        return this.request(`/tenders${query}`, {}, 30000);
    }

    static async createTender(tenderData) {
        return this.request('/tenders', { method: 'POST', body: JSON.stringify(tenderData) });
    }

    static async updateTender(id, data) {
        return this.request(`/tenders/${id}`, { method: 'PUT', body: JSON.stringify(data) });
    }

    static async aiGenerateTender(prompt) {
        return this.request('/tenders/ai-generate', {
            method: 'POST',
            body: JSON.stringify({ prompt })
        });
    }

    static async addCriteria(tenderId, criteriaData) {
        return this.request(`/tenders/${tenderId}/criteria`, {
            method: 'POST',
            body: JSON.stringify(criteriaData)
        });
    }

    /** GET /tenders/{id}/lifecycle — structured stage-by-stage timeline */
    static async getTenderLifecycle(tenderId) {
        return this.request(`/analytics/tender-timeline/${tenderId}`);
    }

    // ── Bids ──────────────────────────────────────────────────
    static async submitBid(bidData) {
        return this.request('/bids', { method: 'POST', body: JSON.stringify(bidData) });
    }

    // ── Evaluation ────────────────────────────────────────────
    static async scoreBid(evaluationData) {
        return this.request('/evaluation/score', { method: 'POST', body: JSON.stringify(evaluationData) });
    }

    static async awardTender(tenderId, bidId) {
        return this.request(`/evaluation/award/${tenderId}/${bidId}`, { method: 'POST' });
    }

    static async openFinancialBids(tenderId) {
        return this.request(`/evaluation/open-financial/${tenderId}`, { method: 'POST' });
    }

    static async getAIScoreSuggestion(bidId) {
        return this.request(`/evaluation/ai-score/${bidId}`);
    }

    static async startAuction(tenderId) {
        return this.request(`/evaluation/auction/start/${tenderId}`, { method: 'POST' });
    }

    static async getAuctionState(tenderId) {
        return this.request(`/evaluation/auction/${tenderId}`);
    }

    static async placeAuctionBid(tenderId, amount) {
        return this.request(`/evaluation/auction/bid/${tenderId}`, {
            method: 'POST',
            body: JSON.stringify({ amount })
        });
    }

    static async autoEvaluateTender(tenderId) {
        return this.request(`/evaluation/auto-evaluate/${tenderId}`, { method: 'POST' });
    }

    // ── Dashboard & Reports ───────────────────────────────────
    static async getDashboardStats() {
        return this.request('/reports/dashboard-stats', {}, 60000);
    }

    static async getAuditLog() {
        return this.request('/reports/audit-log');
    }

    /**
     * Natural language chat assistant — routes to /reports/chat
     * (NLP query engine over the procurement DB)
     */
    static async askAI(query) {
        return this.request('/reports/chat', {
            method: 'POST',
            body: JSON.stringify({ message: query })
        });
    }

    static async getCycleDossier(tenderId) {
        return this.request(`/reports/cycle-dossier/${tenderId}`);
    }

    static async getPqcComparisonData() {
        return this.request('/reports/pqc-comparison-data');
    }

    static async getPredictiveForecast(category = 'IT Hardware') {
        return this.request(`/reports/predictive-forecast?material_category=${encodeURIComponent(category)}`);
    }

    static async getFraudAnalysis() {
        return this.request('/reports/fraud-analysis');
    }

    static async getCartelGraph() {
        return this.request('/reports/cartel-graph');
    }

    // ── Documents / OCR ───────────────────────────────────────
    static async uploadDocument(bidId, documentType, file) {
        const formData = new FormData();
        formData.append('document_type', documentType);
        formData.append('file', file);

        const token = this.getToken();
        const headers = token ? { 'Authorization': `Bearer ${token}` } : {};

        const response = await fetch(`${API_BASE_URL}/documents/upload/${bidId}`, {
            method: 'POST',
            headers,
            body: formData
        });

        let data;
        try { data = await response.json(); } catch { data = {}; }
        if (!response.ok) throw new Error(data.detail || 'Upload Failed');
        return data;
    }

    static async verifyDocument(docId, verified) {
        return this.request(`/documents/${docId}/verify?verified=${verified}`, { method: 'POST' });
    }

    static async compareDocuments(tenderId) {
        return this.request(`/documents/compare/${tenderId}`);
    }

    // ── IOCL Procurement ─────────────────────────────────────
    static async createIndent(data) {
        return this.request('/iocl/indents', { method: 'POST', body: JSON.stringify(data) });
    }

    static async getIndents(status = '') {
        const q = status ? `?status=${encodeURIComponent(status)}` : '';
        return this.request(`/iocl/indents${q}`);
    }

    static async submitIndent(id) {
        return this.request(`/iocl/indents/${id}/submit`, { method: 'POST' });
    }

    static async approveIndent(id) {
        return this.request(`/iocl/indents/${id}/approve`, { method: 'POST' });
    }

    static async rejectIndent(id) {
        return this.request(`/iocl/indents/${id}/reject`, { method: 'POST' });
    }

    static async convertIndentToTender(id) {
        return this.request(`/iocl/indents/${id}/convert-to-tender`, { method: 'POST' });
    }

    static async getIOCLStats() {
        return this.request('/iocl/stats');
    }

    static async pacApprove(data) {
        return this.request('/iocl/pac/approve', { method: 'POST', body: JSON.stringify(data) });
    }

    static async createPurchaseOrder(data) {
        return this.request('/iocl/purchase-orders', { method: 'POST', body: JSON.stringify(data) });
    }

    static async getPurchaseOrders() {
        return this.request('/iocl/purchase-orders');
    }

    static async createDelivery(data) {
        return this.request('/iocl/deliveries', { method: 'POST', body: JSON.stringify(data) });
    }

    static async getDeliveries() {
        return this.request('/iocl/deliveries');
    }

    static async processPayment(poId, invoiceNumber, invoiceAmount) {
        return this.request(
            `/iocl/payments/${poId}/process`,
            {
                method: 'POST',
                body: JSON.stringify({ invoice_number: invoiceNumber, invoice_amount: invoiceAmount })
            }
        );
    }

    static async getPayments() {
        return this.request('/iocl/payments');
    }

    static async triggerArbitration(deliveryId) {
        return this.request('/iocl/arbitration/trigger', {
            method: 'POST',
            body: JSON.stringify({ delivery_id: deliveryId })
        });
    }

    // ── Vendors ───────────────────────────────────────────────
    static async toggleBlacklist(id) {
        return this.request(`/vendors/${id}/blacklist`, { method: 'POST' });
    }

    static async getVendorIntelligence(id) {
        return this.request(`/vendors/${id}/intelligence`);
    }

    /** GET /vendors/{id}/risk-profile — 6-dimension AI risk assessment */
    static async getVendorRiskProfile(id) {
        return this.request(`/vendors/${id}/risk-profile`);
    }

    static async runDeepfakeScan(vendorId, livenessScore) {
        // Generate a cryptographically-informed video hash based on vendor ID, timestamp, and liveness score
        const rawData = `${vendorId}:${Date.now()}:${livenessScore}:${Math.random()}`;
        let hash = 0;
        for (let i = 0; i < rawData.length; i++) {
            hash = ((hash << 5) - hash) + rawData.charCodeAt(i);
            hash |= 0;
        }
        const videoHash = `0x${Math.abs(hash).toString(16).toUpperCase().padStart(8,'0')}${Date.now().toString(16).toUpperCase()}`;
        return this.request(`/vendors/${vendorId}/kyc-deepfake-scan`, {
            method: 'POST',
            body: JSON.stringify({ video_hash: videoHash, liveness_score: livenessScore })
        });
    }

    // ── C3 Operations ─────────────────────────────────────────
    static async getIoTNodes() {
        return this.request('/c3/iot-nodes');
    }

    static async getAgentHeartbeat() {
        return this.request('/c3/agent-heartbeat');
    }

    static async getC3Metrics() {
        return this.request('/c3/metrics');
    }

    /**
     * C3 Text-to-SQL analytics query (returns chart data from DB).
     * Connects to POST /c3/ask-ai
     */
    static async askC3AI(query) {
        return this.request('/c3/ask-ai', {
            method: 'POST',
            body: JSON.stringify({ query })
        });
    }

    static async sendChatMessage(message) {
        return this.request('/c3/chat', {
            method: 'POST',
            body: JSON.stringify({ message })
        });
    }

    // ── Security & Blockchain ─────────────────────────────────
    static async verifyBlockchain() {
        return this.request('/security/blockchain/verify');
    }

    static async getSecurityAudit() {
        return this.request('/security/audit-logs');
    }

    static async getAdvancedBidAnalysis(tenderId = null) {
        const q = tenderId ? `?tender_id=${tenderId}` : '';
        return this.request(`/reports/advanced-bid-analysis${q}`);
    }

    static async getAiRiskIntelligence(tenderId) {
        return this.request(`/reports/ai-risk-intelligence?tender_id=${tenderId}`);
    }

    static async getDeepForensics() {
        return this.request('/reports/deep-forensics');
    }

    static async recalcVendorPerformance() {
        return this.request('/reports/vendor-performance-recalc', { method: 'POST' });
    }

    static async getBidTimingForensics() {
        return this.request('/reports/bid-timing-forensics');
    }

    static async getCommandCenter() {
        return this.request('/reports/command-center');
    }

    // ── AI Operations Center ─────────────────────────────────
    static async getSwarmRegistry() {
        return this.request('/ai-ops/swarm-registry');
    }

    static async runNegotiationSwarm(tenderId) {
        return this.request(`/ai-ops/negotiate/${tenderId}`, { method: 'POST' });
    }

    static async getCognitiveMap(tenderId) {
        return this.request(`/ai-ops/cognitive-map/${tenderId}`);
    }

    static async getThreatIntel() {
        return this.request('/ai-ops/threat-intel');
    }

    static async getAnomalyScan() {
        return this.request('/ai-ops/anomaly-scan');
    }

    static async getMarketIntelligence() {
        return this.request('/ai-ops/market-intelligence');
    }

    // ── AI Intelligence Command Center ─────────────────────────
    static async ragUpload(formData) {
        const token = this.getToken();
        const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
        const response = await fetch(`${API_BASE_URL}/ai-ops/rag-upload`, {
            method: 'POST',
            headers,
            body: formData
        });
        let data;
        try { data = await response.json(); } catch { data = {}; }
        if (!response.ok) throw new Error(data.detail || 'RAG Upload Failed');
        return data;
    }

    static async ragQuery(question, filters = {}) {
        return this.request('/ai-ops/rag-query', {
            method: 'POST',
            body: JSON.stringify({ question, ...filters })
        });
    }

    static async ragStatus() {
        return this.request('/ai-ops/rag-status');
    }

    static async logAIDecision(data) {
        return this.request('/ai-ops/ai-audit/log-decision', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    static async submitAIFeedback(decisionId, data) {
        return this.request(`/ai-audit/feedback/${decisionId}`, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    static async getAIAccuracyReport() {
        return this.request('/ai-audit/accuracy-report');
    }

    static async getAIDecisions(params = {}) {
        const query = new URLSearchParams(params).toString();
        return this.request(`/ai-audit/decisions?${query}`);
    }

    static async getAIDecisionsForTender(tenderId) {
        return this.request(`/ai-audit/decisions/${tenderId}`);
    }

    static async getCartelDetection() {
        return this.request('/ai-ops/cartel-detection');
    }

    static async getBidTimingAnalysis() {
        return this.request('/ai-ops/bid-timing-analysis');
    }

    // ── Analytics (NEW) ───────────────────────────────────────
    /** GET /analytics/kpi-summary — cycle time, savings, threats, compliance */
    static async getKpiSummary() {
        return this.request('/analytics/kpi-summary', {}, 30000);
    }

    /** GET /analytics/ai-insights — aggregated AI recommendations */
    static async getAiInsights() {
        return this.request('/analytics/ai-insights', {}, 30000);
    }

    /** GET /analytics/tender-timeline/{id} — procurement lifecycle stages */
    static async getTenderTimeline(tenderId) {
        return this.request(`/analytics/tender-timeline/${tenderId}`);
    }

    // ── Document Intelligence (NEW) ───────────────────────────
    static async complianceScan(documentText, tenderTitle = "Tender Document", vendorProfile = null) {
        return this.request('/ai-ops/compliance-scan', {
            method: 'POST',
            body: JSON.stringify({
                document_text: documentText,
                tender_title: tenderTitle,
                vendor_profile: vendorProfile
            })
        });
    }

    static async explainClause(clauseText, context = "") {
        return this.request('/reports/explain-clause', {
            method: 'POST',
            body: JSON.stringify({
                clause_text: clauseText,
                context: context
            })
        });
    }

    static async documentOcr(formData) {
        const token = this.getToken();
        const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
        const response = await fetch(`${API_BASE_URL}/ai-ops/document-ocr`, {
            method: 'POST',
            headers,
            body: formData
        });
        let data;
        try { data = await response.json(); } catch { data = {}; }
        if (!response.ok) throw new Error(data.detail || 'OCR Ingestion Failed');
        return data;
    }

    // ── WebSocket Helpers ─────────────────────────────────────
    /**
     * Opens a WebSocket to the real-time audit log stream.
     * @param {function} onMessage - Called with parsed JSON array of new log entries
     * @param {function} onError   - Called on error
     * @returns {WebSocket}
     */
    static connectAuditWS(onMessage, onError) {
        const wsUrl = API_BASE_URL.replace('http', 'ws') + '/ws/audit';
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => console.log('[GEM WS] Audit stream connected');

        ws.onmessage = (event) => {
            try {
                const logs = JSON.parse(event.data);
                if (typeof onMessage === 'function') onMessage(logs);
            } catch (e) {
                console.warn('[GEM WS] Parse error:', e);
            }
        };

        ws.onerror = (err) => {
            console.error('[GEM WS] Error:', err);
            if (typeof onError === 'function') onError(err);
        };

        ws.onclose = () => console.log('[GEM WS] Audit stream closed');

        return ws;
    }

    /**
     * Opens a WebSocket to the evaluation stream for a specific tender.
     * @param {number} tenderId
     * @param {function} onMessage
     * @returns {WebSocket}
     */
    static connectEvaluationWS(tenderId, onMessage) {
        const wsUrl = API_BASE_URL.replace('http', 'ws') + `/ws/evaluation/${tenderId}`;
        const ws = new WebSocket(wsUrl);
        ws.onopen = () => console.log(`[GEM WS] Evaluation stream for tender ${tenderId} connected`);
        ws.onmessage = (event) => {
            if (typeof onMessage === 'function') onMessage(event.data);
        };
        return ws;
    }

    // ── Settings Path Configurations ─────────────────────────
    static async getPathSettings() {
        return this.request('/settings/paths');
    }

    static async savePathSettings(settingsData, autoCreateDirs = false) {
        return this.request(`/settings/paths?auto_create_dirs=${autoCreateDirs}`, {
            method: 'POST',
            body: JSON.stringify(settingsData)
        });
    }

    static async resetPathSettings() {
        return this.request('/settings/paths/reset', {
            method: 'POST'
        });
    }
}

/* ============================================================
   Global UI Utilities
   ============================================================ */

/**
 * Display a toast notification.
 * @param {string} message
 * @param {'success'|'error'|'warning'} type
 */
function showToast(message, type = 'success') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        Object.assign(container.style, {
            position: 'fixed', bottom: '24px', right: '24px',
            display: 'flex', flexDirection: 'column', gap: '10px',
            zIndex: '9999', pointerEvents: 'none'
        });
        document.body.appendChild(container);
    }

    const iconMap = { success: 'check-circle', error: 'alert-circle', warning: 'alert-triangle' };
    const colorMap = { success: 'var(--success)', error: 'var(--danger)', warning: '#f59e0b' };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.style.cssText = 'pointer-events: auto; opacity: 1; transform: translateX(0); transition: opacity 0.3s, transform 0.3s;';
    toast.innerHTML = `<i data-lucide="${iconMap[type] || 'info'}" style="color:${colorMap[type] || '#94a3b8'};flex-shrink:0"></i><span>${message}</span>`;

    container.appendChild(toast);
    if (window.lucide) lucide.createIcons({ el: toast });

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(110%)';
        setTimeout(() => toast.remove(), 350);
    }, 4000);
}

/** Redirect to login if no valid token */
function requireAuth() {
    if (!ApiClient.getToken()) {
        window.location.href = 'index.html';
        return false;
    }
    return true;
}

/** Populate header user-profile elements if they exist on the current page */
function loadUserProfile() {
    const user = ApiClient.getStoredUser();
    if (!user) return;

    const setEl = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    };

    setEl('user-name', user.full_name || user.username || '');
    setEl('user-role', user.role || '');
    setEl('user-avatar', (user.full_name || user.username || '?').charAt(0).toUpperCase());

    // RBAC: hide evaluation link for non-privileged roles
    if (user.role !== 'Admin' && user.role !== 'Evaluator') {
        const evalLink = document.getElementById('nav-evaluation');
        if (evalLink) evalLink.style.display = 'none';
    }
}

function logout() {
    ApiClient.clearAuth();
    window.location.href = 'index.html';
}
