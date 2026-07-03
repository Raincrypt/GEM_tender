/* ============================================================
   GEM Tender — Activity Timeline Component v1.0
   Renders a beautiful vertical timeline of audit events.
   ============================================================ */

const GemTimeline = (() => {

    const EVENT_CONFIG = {
        'TENDER_CREATED':     { icon: 'file-plus',     color: '#3b82f6', label: 'Tender Created' },
        'TENDER_PUBLISHED':   { icon: 'globe',         color: '#10b981', label: 'Published' },
        'TENDER_UPDATED':     { icon: 'edit',          color: '#f59e0b', label: 'Updated' },
        'BID_SUBMITTED':      { icon: 'send',          color: '#8b5cf6', label: 'Bid Submitted' },
        'BID_REJECTED':       { icon: 'x-circle',      color: '#ef4444', label: 'Bid Rejected' },
        'EVALUATION_STARTED': { icon: 'play',          color: '#06b6d4', label: 'Evaluation Started' },
        'EVALUATION_DONE':    { icon: 'check-circle',  color: '#10b981', label: 'Evaluation Complete' },
        'AWARDED':            { icon: 'trophy',        color: '#fbbf24', label: 'Awarded' },
        'FRAUD_ALERT':        { icon: 'alert-triangle', color: '#ef4444', label: 'Fraud Alert' },
        'LOGIN':              { icon: 'log-in',        color: '#64748b', label: 'Login' },
        'LOGOUT':             { icon: 'log-out',       color: '#64748b', label: 'Logout' },
        'STATUS_CHANGE':      { icon: 'refresh-cw',    color: '#a78bfa', label: 'Status Change' },
        'DOCUMENT_UPLOADED':  { icon: 'upload',        color: '#60a5fa', label: 'Document Uploaded' },
        'VENDOR_CREATED':     { icon: 'user-plus',     color: '#10b981', label: 'Vendor Registered' },
        'SETTING_CHANGED':    { icon: 'settings',      color: '#f59e0b', label: 'Setting Changed' },
    };

    const DEFAULT_CONFIG = { icon: 'activity', color: '#94a3b8', label: 'Activity' };

    function injectStyles() {
        if (document.getElementById('gem-timeline-styles')) return;
        const style = document.createElement('style');
        style.id = 'gem-timeline-styles';
        style.textContent = `
            .gem-timeline {
                position: relative;
                padding: 0;
                list-style: none;
                max-height: 600px;
                overflow-y: auto;
            }
            .gem-timeline::before {
                content: '';
                position: absolute;
                left: 20px;
                top: 0;
                bottom: 0;
                width: 2px;
                background: linear-gradient(to bottom, rgba(99,102,241,0.5), rgba(99,102,241,0.05));
            }
            .timeline-item {
                position: relative;
                padding: 0 0 24px 52px;
                animation: timelineFadeIn 0.4s ease forwards;
                opacity: 0;
            }
            .timeline-item:last-child { padding-bottom: 0; }
            @keyframes timelineFadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }
            .timeline-dot {
                position: absolute;
                left: 11px;
                top: 2px;
                width: 20px;
                height: 20px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 1;
                box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.8), 0 0 10px rgba(0,0,0,0.3);
            }
            .timeline-dot i, .timeline-dot svg {
                width: 10px;
                height: 10px;
                color: white;
            }
            .timeline-card {
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 8px;
                padding: 12px 14px;
                transition: all 0.2s ease;
            }
            .timeline-card:hover {
                background: rgba(255,255,255,0.06);
                border-color: rgba(255,255,255,0.12);
                transform: translateX(3px);
            }
            .timeline-label {
                font-size: 0.82rem;
                font-weight: 600;
                margin-bottom: 3px;
            }
            .timeline-detail {
                font-size: 0.75rem;
                color: #94a3b8;
                line-height: 1.4;
            }
            .timeline-time {
                font-size: 0.65rem;
                color: #64748b;
                margin-top: 4px;
                display: flex;
                align-items: center;
                gap: 4px;
            }
            .timeline-user-badge {
                font-size: 0.6rem;
                padding: 1px 6px;
                border-radius: 4px;
                background: rgba(99, 102, 241, 0.12);
                color: #a5b4fc;
                font-weight: 500;
            }
            .timeline-empty {
                text-align: center;
                color: #64748b;
                padding: 40px 20px;
                font-size: 0.85rem;
            }
            .timeline-filter-bar {
                display: flex;
                gap: 6px;
                margin-bottom: 12px;
                flex-wrap: wrap;
            }
            .timeline-filter-btn {
                font-size: 0.7rem;
                padding: 3px 10px;
                border-radius: 12px;
                border: 1px solid rgba(255,255,255,0.1);
                background: transparent;
                color: var(--text-muted, #94a3b8);
                cursor: pointer;
                transition: all 0.2s ease;
            }
            .timeline-filter-btn:hover, .timeline-filter-btn.active {
                background: rgba(99, 102, 241, 0.15);
                border-color: #6366f1;
                color: #a5b4fc;
            }

            /* Light mode */
            [data-theme="light"] .timeline-card {
                background: rgba(0,0,0,0.02);
                border-color: rgba(0,0,0,0.08);
            }
            [data-theme="light"] .timeline-card:hover {
                background: rgba(0,0,0,0.04);
            }
            [data-theme="light"] .timeline-dot {
                box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.9), 0 0 10px rgba(0,0,0,0.1);
            }
            [data-theme="light"] .gem-timeline::before {
                background: linear-gradient(to bottom, rgba(99,102,241,0.3), rgba(99,102,241,0.02));
            }
        `;
        document.head.appendChild(style);
    }

    /**
     * Render a timeline into a container.
     * @param {string} containerSelector - CSS selector for the container element
     * @param {Object[]} events - Array of audit log entries: { action, entity_type, entity_id, details, user, timestamp }
     * @param {Object} [opts] - Options: { filterTypes: ['TENDER_CREATED', ...], limit: 50 }
     */
    function render(containerSelector, events, opts = {}) {
        injectStyles();

        const container = document.querySelector(containerSelector);
        if (!container) return;

        let items = [...events].sort((a, b) => new Date(b.timestamp || b.created_at) - new Date(a.timestamp || a.created_at));

        const limit = opts.limit || 50;
        items = items.slice(0, limit);

        if (items.length === 0) {
            container.innerHTML = '<div class="timeline-empty"><i data-lucide="inbox" style="width:28px;height:28px;margin-bottom:8px;display:inline-block;"></i><br>No activity yet</div>';
            if (window.lucide) lucide.createIcons();
            return;
        }

        // Build filter bar
        const actionTypes = [...new Set(items.map(e => e.action || 'UNKNOWN'))];
        let currentFilter = null;

        const filterBar = document.createElement('div');
        filterBar.className = 'timeline-filter-bar';
        filterBar.innerHTML = `<button class="timeline-filter-btn active" data-filter="all">All</button>` +
            actionTypes.map(type => {
                const cfg = EVENT_CONFIG[type] || DEFAULT_CONFIG;
                return `<button class="timeline-filter-btn" data-filter="${type}">${cfg.label || type}</button>`;
            }).join('');

        const timeline = document.createElement('div');
        timeline.className = 'gem-timeline';

        container.innerHTML = '';
        container.appendChild(filterBar);
        container.appendChild(timeline);

        function renderItems(filter) {
            const filtered = filter && filter !== 'all'
                ? items.filter(e => e.action === filter)
                : items;

            timeline.innerHTML = filtered.map((event, i) => {
                const cfg = EVENT_CONFIG[event.action] || DEFAULT_CONFIG;
                const time = new Date(event.timestamp || event.created_at);
                const timeStr = time.toLocaleDateString() + ' ' + time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                const relTime = getRelativeTime(time);
                const detail = event.details || event.entity_type || '';
                const user = event.user || event.username || '';

                return `
                    <div class="timeline-item" style="animation-delay: ${i * 0.05}s">
                        <div class="timeline-dot" style="background: ${cfg.color}">
                            <i data-lucide="${cfg.icon}"></i>
                        </div>
                        <div class="timeline-card">
                            <div class="timeline-label" style="color: ${cfg.color}">${cfg.label || event.action}</div>
                            ${detail ? `<div class="timeline-detail">${detail}</div>` : ''}
                            <div class="timeline-time">
                                <i data-lucide="clock" style="width:10px;height:10px;"></i> ${relTime}
                                ${user ? `<span class="timeline-user-badge">${user}</span>` : ''}
                                <span style="margin-left:auto;">${timeStr}</span>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');

            if (window.lucide) lucide.createIcons();
        }

        // Filter click handlers
        filterBar.querySelectorAll('.timeline-filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                filterBar.querySelectorAll('.timeline-filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentFilter = btn.dataset.filter;
                renderItems(currentFilter);
            });
        });

        renderItems(null);
    }

    /**
     * Render a horizontal lifecycle stepper for a tender.
     * @param {string} containerSelector - CSS selector
     * @param {string} currentStage - e.g. 'Published', 'Under Evaluation', 'Awarded'
     */
    function renderLifecycleStepper(containerSelector, currentStage) {
        injectStyles();

        const container = document.querySelector(containerSelector);
        if (!container) return;

        const stages = ['Draft', 'Published', 'Under Evaluation', 'Awarded', 'Closed'];
        const currentIndex = stages.findIndex(s => s.toLowerCase() === (currentStage || '').toLowerCase());

        if (!document.getElementById('gem-stepper-styles')) {
            const style = document.createElement('style');
            style.id = 'gem-stepper-styles';
            style.textContent = `
                .lifecycle-stepper {
                    display: flex;
                    align-items: center;
                    gap: 0;
                    padding: 16px 0;
                    overflow-x: auto;
                }
                .step {
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    flex: 1;
                    position: relative;
                    min-width: 80px;
                }
                .step-circle {
                    width: 32px;
                    height: 32px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 0.7rem;
                    font-weight: bold;
                    z-index: 1;
                    transition: all 0.3s ease;
                }
                .step.completed .step-circle {
                    background: #10b981;
                    color: white;
                    box-shadow: 0 0 12px rgba(16,185,129,0.4);
                }
                .step.active .step-circle {
                    background: #6366f1;
                    color: white;
                    box-shadow: 0 0 16px rgba(99,102,241,0.5);
                    animation: stepPulse 2s infinite;
                }
                .step.pending .step-circle {
                    background: rgba(255,255,255,0.05);
                    color: #64748b;
                    border: 2px solid rgba(255,255,255,0.1);
                }
                @keyframes stepPulse {
                    0%, 100% { box-shadow: 0 0 16px rgba(99,102,241,0.5); }
                    50% { box-shadow: 0 0 24px rgba(99,102,241,0.8); }
                }
                .step-label {
                    font-size: 0.7rem;
                    margin-top: 6px;
                    color: #94a3b8;
                    text-align: center;
                    white-space: nowrap;
                }
                .step.active .step-label { color: #a5b4fc; font-weight: 600; }
                .step.completed .step-label { color: #6ee7b7; }
                .step-connector {
                    flex: 1;
                    height: 2px;
                    background: rgba(255,255,255,0.08);
                    position: relative;
                    min-width: 20px;
                    align-self: flex-start;
                    margin-top: 15px;
                }
                .step-connector.done {
                    background: linear-gradient(to right, #10b981, #10b981);
                }
                .step-connector.in-progress {
                    background: linear-gradient(to right, #10b981, #6366f1);
                }
            `;
            document.head.appendChild(style);
        }

        let html = '<div class="lifecycle-stepper">';
        stages.forEach((stage, i) => {
            const cls = i < currentIndex ? 'completed' : i === currentIndex ? 'active' : 'pending';
            const icon = i < currentIndex ? '✓' : (i + 1);
            html += `<div class="step ${cls}"><div class="step-circle">${icon}</div><div class="step-label">${stage}</div></div>`;

            if (i < stages.length - 1) {
                const connCls = i < currentIndex ? 'done' : i === currentIndex ? 'in-progress' : '';
                html += `<div class="step-connector ${connCls}"></div>`;
            }
        });
        html += '</div>';
        container.innerHTML = html;
    }

    // ── Helpers ─────────────────────────────────────────────────
    function getRelativeTime(date) {
        const now = new Date();
        const diff = now - date;
        const seconds = Math.floor(diff / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);

        if (seconds < 60) return 'Just now';
        if (minutes < 60) return `${minutes}m ago`;
        if (hours < 24) return `${hours}h ago`;
        if (days < 7) return `${days}d ago`;
        return date.toLocaleDateString();
    }

    return { render, renderLifecycleStepper, EVENT_CONFIG };
})();
