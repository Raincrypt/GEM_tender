/* ============================================================
   GEM Tender — Shared Sidebar & Notifications Component v2.0
   Include this script to auto-inject sidebar, hamburger menu,
   theme toggle, active-link highlighting, and real-time notifications.
   ============================================================ */

const GemSidebar = (() => {
    const NAV_ITEMS = [
        { href: 'dashboard.html', icon: 'layout-dashboard', label: 'Dashboard' },
        { href: 'tenders.html', icon: 'file-text', label: 'Tenders' },
        { href: 'vendors.html', icon: 'users', label: 'Vendors' },
        { href: 'autopilot.html', icon: 'play-circle', label: 'Procurement Autopilot', style: 'color: #10b981; font-weight: 600;' },
        { href: 'predictive_analysis.html', icon: 'trending-up', label: 'AI Price Forecast', style: 'color: #a78bfa;', id: 'nav-predictive' },
        { href: 'oracle_nexus.html', icon: 'eye', label: 'Oracle Nexus', style: 'color: #06b6d4;', id: 'nav-oracle' },
        { href: 'evaluation.html', icon: 'check-square', label: 'Evaluation', id: 'nav-evaluation', adminOnly: true },
        { href: 'cartel.html', icon: 'network', label: 'Cartel Intel', style: 'color: var(--danger);', id: 'nav-cartel', adminOnly: true },
        { href: 'plagiarism_report.html', icon: 'file-search', label: 'Plagiarism Intel', style: 'color: #fbbf24;', id: 'nav-plagiarism', adminOnly: true },
        { href: 'pqc_comparison.html', icon: 'shield', label: 'PQC Forensics', style: 'color: #ec4899;', id: 'nav-pqc', adminOnly: true },
        { href: 'tender_rules_understanding.html', icon: 'book-open', label: 'Rules Understanding', style: 'color: #f472b6;', id: 'nav-tender-rules', adminOnly: true },
        { href: 'deep_forensics.html', icon: 'shield-alert', label: 'Deep Forensics', style: 'color: #a78bfa;', id: 'nav-forensics', adminOnly: true },
        { href: 'bid_analysis.html', icon: 'bar-chart-2', label: 'Bid Analysis', style: 'color: #60a5fa;', id: 'nav-analysis', adminOnly: true },
        { href: 'dynamic_rule_analyzer.html', icon: 'sliders', label: 'Dynamic Rule Analyzer', style: 'color: #f472b6;', id: 'nav-rule-analyzer', adminOnly: true },
        { href: 'advanced_analytics.html', icon: 'atom', label: 'Advanced Analytics', style: 'color: #8b5cf6; font-weight: 600;' },
        { href: 'executive_command_center.html', icon: 'crown', label: 'Executive Intel', style: 'color: #fbbf24; font-weight: 600;' },
        { href: 'document_intelligence.html', icon: 'file-search', label: 'Doc Intelligence', style: 'color: #60a5fa; font-weight: 600;' },
        { href: 'ai_copilot.html', icon: 'bot', label: 'AI Copilot', style: 'color: #06b6d4;' },
        { href: 'ai_intelligence.html', icon: 'brain-circuit', label: 'AI Command Center', style: 'color: #a78bfa; font-weight: 600;', id: 'nav-ai-intelligence' },
        { href: 'settings_paths.html', icon: 'settings', label: 'System Settings', style: 'color: #f59e0b; font-weight: 600;' },
    ];

    function getCurrentPage() {
        const path = window.location.pathname;
        const file = path.substring(path.lastIndexOf('/') + 1) || 'index.html';
        return file;
    }

    function buildSidebarHTML() {
        const currentPage = getCurrentPage();
        const user = (() => { try { return JSON.parse(localStorage.getItem('gem_user')); } catch { return null; } })();
        const isPrivileged = user && (user.role === 'Admin' || user.role === 'Evaluator');

        let navHtml = NAV_ITEMS.map(item => {
            const isActive = currentPage === item.href ? ' active' : '';
            const hide = item.adminOnly && !isPrivileged ? ' style="display:none;"' : '';
            const linkStyle = item.style ? ` style="${item.style}"` : '';
            const idAttr = item.id ? ` id="${item.id}"` : '';
            return `<li class="nav-item"${idAttr}${hide}>
                <a href="${item.href}" class="nav-link${isActive}"${linkStyle}>
                    <i data-lucide="${item.icon}"></i> ${item.label}
                </a>
            </li>`;
        }).join('\n');

        return `
        <aside class="sidebar" id="gem-sidebar">
            <div class="sidebar-brand">
                <i data-lucide="shield-check"></i>
                GEM Tender
            </div>
            <ul class="nav-menu">
                ${navHtml}
            </ul>
        </aside>
        <div class="sidebar-overlay" id="sidebar-overlay" onclick="GemSidebar.closeMobile()"></div>
        <button class="sidebar-toggle" id="sidebar-toggle" onclick="GemSidebar.toggleMobile()">
            <i data-lucide="menu"></i>
        </button>`;
    }

    function inject() {
        const layout = document.querySelector('.app-layout');
        if (!layout) return;

        const existingSidebar = layout.querySelector('.sidebar');
        if (existingSidebar) return;

        layout.insertAdjacentHTML('afterbegin', buildSidebarHTML());
        if (window.lucide) lucide.createIcons();
    }

    function toggleMobile() {
        const sidebar = document.getElementById('gem-sidebar');
        if (sidebar) sidebar.classList.toggle('open');
    }

    function closeMobile() {
        const sidebar = document.getElementById('gem-sidebar');
        if (sidebar) sidebar.classList.remove('open');
    }

    return { inject, toggleMobile, closeMobile, NAV_ITEMS };
})();

/* ============================================================
   Theme Switcher — persists to localStorage
   ============================================================ */
const GemTheme = (() => {
    const STORAGE_KEY = 'gem_theme';

    function init() {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved === 'light') {
            document.documentElement.setAttribute('data-theme', 'light');
        }
    }

    function toggle() {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'light' ? 'dark' : 'light';
        if (next === 'light') {
            document.documentElement.setAttribute('data-theme', 'light');
        } else {
            document.documentElement.removeAttribute('data-theme');
        }
        localStorage.setItem(STORAGE_KEY, next);

        const icon = document.querySelector('.theme-toggle i');
        if (icon && window.lucide) {
            icon.setAttribute('data-lucide', next === 'light' ? 'moon' : 'sun');
            lucide.createIcons();
        }
    }

    init();
    return { toggle, init };
})();

/* ============================================================
   Notifications Center Controller — fetches /notifications
   ============================================================ */
const GemNotifications = (() => {
    let unreadCount = 0;
    let list = [];

    function injectStyles() {
        if (document.getElementById('gem-notifications-styles')) return;
        const css = `
            .notification-bell-btn {
                background: none;
                border: none;
                color: var(--text, #e2e8f0);
                cursor: pointer;
                padding: 8px;
                position: relative;
                border-radius: 6px;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: background 0.2s;
            }
            .notification-bell-btn:hover {
                background: rgba(255,255,255,0.05);
            }
            .notification-badge {
                position: absolute;
                top: 4px;
                right: 4px;
                background: #ef4444;
                color: white;
                font-size: 0.6rem;
                font-weight: bold;
                min-width: 15px;
                height: 15px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 0 3px;
                border: 2px solid var(--card-bg, #1e293b);
                box-shadow: 0 0 5px rgba(239, 68, 68, 0.5);
            }
            .notification-drawer {
                position: fixed;
                top: 0;
                right: -360px;
                width: 360px;
                height: 100vh;
                background: rgba(15, 23, 42, 0.95);
                backdrop-filter: blur(15px);
                border-left: 1px solid rgba(255,255,255,0.1);
                box-shadow: -10px 0 30px rgba(0,0,0,0.5);
                z-index: 2000;
                transition: right 0.3s cubic-bezier(0.16, 1, 0.3, 1);
                display: flex;
                flex-direction: column;
            }
            .notification-drawer.open {
                right: 0;
            }
            .notification-header {
                padding: 20px;
                border-bottom: 1px solid rgba(255,255,255,0.08);
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .notification-body {
                flex: 1;
                overflow-y: auto;
                padding: 15px;
            }
            .notification-item {
                padding: 12px;
                border-radius: 8px;
                background: rgba(255,255,255,0.02);
                border-left: 4px solid #3b82f6;
                margin-bottom: 10px;
                position: relative;
                transition: all 0.2s ease;
            }
            .notification-item:hover {
                background: rgba(255,255,255,0.05);
            }
            .notification-item.unread {
                background: rgba(59, 130, 246, 0.06);
            }
            .notification-item.severity-critical { border-left-color: #ef4444; }
            .notification-item.severity-warning { border-left-color: #f59e0b; }
            .notification-item.severity-info { border-left-color: #3b82f6; }
            .notification-item .title { font-weight: bold; font-size: 0.85rem; margin-bottom: 4px; color: #f8fafc; }
            .notification-item .message { font-size: 0.78rem; color: #94a3b8; line-height: 1.35; }
            .notification-item .time { font-size: 0.65rem; color: #64748b; margin-top: 6px; text-align: right; }
            .notification-item .mark-read-btn {
                position: absolute;
                top: 8px;
                right: 8px;
                font-size: 0.65rem;
                color: #60a5fa;
                cursor: pointer;
                opacity: 0;
                transition: opacity 0.2s ease;
                background: none;
                border: none;
                padding: 2px 5px;
                border-radius: 3px;
            }
            .notification-item:hover .mark-read-btn {
                opacity: 1;
            }
            .notification-item .mark-read-btn:hover {
                background: rgba(59, 130, 246, 0.1);
            }
            .drawer-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100vh;
                background: rgba(0,0,0,0.5);
                z-index: 1999;
                display: none;
            }
            .drawer-overlay.open {
                display: block;
            }
        `;
        const style = document.createElement('style');
        style.id = 'gem-notifications-styles';
        style.innerHTML = css;
        document.head.appendChild(style);
    }

    async function fetchUnreadCount() {
        if (typeof ApiClient === 'undefined') return;
        try {
            const res = await ApiClient.request('/notifications/unread-count');
            if (res) {
                unreadCount = res.count;
                updateBadge();
            }
        } catch (e) {
            console.error("Failed to fetch unread notifications count:", e);
        }
    }

    async function fetchNotifications() {
        if (typeof ApiClient === 'undefined') return;
        try {
            const res = await ApiClient.request('/notifications/');
            if (res) {
                list = res;
                renderList();
            }
        } catch (e) {
            console.error("Failed to fetch notifications:", e);
        }
    }

    function updateBadge() {
        const bellBtn = document.getElementById('notification-bell-btn');
        if (!bellBtn) return;
        
        let badgeEl = document.getElementById('notification-badge');
        if (unreadCount > 0) {
            if (!badgeEl) {
                badgeEl = document.createElement('span');
                badgeEl.id = 'notification-badge';
                badgeEl.className = 'notification-badge';
                bellBtn.appendChild(badgeEl);
            }
            badgeEl.innerText = unreadCount;
        } else if (badgeEl) {
            badgeEl.remove();
        }
    }

    function renderList() {
        const body = document.getElementById('notification-drawer-body');
        if (!body) return;

        if (list.length === 0) {
            body.innerHTML = '<div style="text-align:center; color:#64748b; margin-top:40px; font-size:0.85rem;">No notifications yet</div>';
            return;
        }

        body.innerHTML = list.map(item => {
            const unreadClass = item.is_read ? '' : ' unread';
            const dateStr = new Date(item.created_at).toLocaleString();
            const markBtn = item.is_read ? '' : `<button class="mark-read-btn" onclick="GemNotifications.markAsRead(${item.id}, event)">Mark Read</button>`;
            
            return `
                <div class="notification-item severity-${item.severity}${unreadClass}">
                    ${markBtn}
                    <div class="title">${item.title}</div>
                    <div class="message">${item.message}</div>
                    <div class="time">${dateStr}</div>
                </div>
            `;
        }).join('');
    }

    async function markAsRead(id, event) {
        if (event) event.stopPropagation();
        if (typeof ApiClient === 'undefined') return;
        try {
            await ApiClient.request(`/notifications/read/${id}`, { method: 'POST' });
            unreadCount = Math.max(0, unreadCount - 1);
            updateBadge();
            
            const idx = list.findIndex(x => x.id === id);
            if (idx !== -1) {
                list[idx].is_read = true;
                renderList();
            }
        } catch (e) {
            console.error(e);
        }
    }

    async function markAllAsRead() {
        if (typeof ApiClient === 'undefined') return;
        try {
            await ApiClient.request('/notifications/read-all', { method: 'POST' });
            unreadCount = 0;
            updateBadge();
            list.forEach(x => x.is_read = true);
            renderList();
        } catch (e) {
            console.error(e);
        }
    }

    function toggleDrawer() {
        const drawer = document.getElementById('notification-drawer');
        const overlay = document.getElementById('notification-overlay');
        if (drawer) {
            const isOpen = drawer.classList.contains('open');
            if (isOpen) {
                drawer.classList.remove('open');
                if (overlay) overlay.classList.remove('open');
            } else {
                fetchNotifications();
                drawer.classList.add('open');
                if (overlay) overlay.classList.add('open');
            }
        }
    }

    function init() {
        if (typeof ApiClient === 'undefined') {
            window.addEventListener('load', () => {
                if (typeof ApiClient !== 'undefined') {
                    GemNotifications.init();
                }
            });
            return;
        }

        injectStyles();
        
        // Inject bell button in top header if present
        const topHeader = document.querySelector('.top-header');
        if (topHeader) {
            const userProfile = topHeader.querySelector('.user-profile');
            if (userProfile && !document.getElementById('notification-bell-btn')) {
                const bellHtml = `
                    <button class="notification-bell-btn" id="notification-bell-btn" onclick="GemNotifications.toggleDrawer()" title="Notifications" style="margin-left: 8px;">
                        <i data-lucide="bell" style="width: 20px; height: 20px;"></i>
                    </button>
                `;
                const logoutBtn = userProfile.querySelector('.btn-outline') || userProfile.querySelector('.theme-toggle');
                if (logoutBtn) {
                    logoutBtn.insertAdjacentHTML('beforebegin', bellHtml);
                } else {
                    userProfile.appendChild(bellHtml);
                }
            }
        }

        // Inject drawer and overlay
        if (!document.getElementById('notification-drawer')) {
            const drawerHtml = `
                <div class="drawer-overlay" id="notification-overlay" onclick="GemNotifications.toggleDrawer()"></div>
                <div class="notification-drawer" id="notification-drawer">
                    <div class="notification-header">
                        <h3 style="margin:0; display:flex; align-items:center; gap:8px; color:white;"><i data-lucide="bell"></i> Notifications</h3>
                        <div style="display:flex; gap:10px; align-items:center;">
                            <button class="btn btn-sm" style="font-size:0.75rem; padding: 4px 8px;" onclick="GemNotifications.markAllAsRead()">Mark All Read</button>
                            <button class="btn btn-outline btn-sm" style="padding: 4px;" onclick="GemNotifications.toggleDrawer()"><i data-lucide="x" style="width: 14px; height: 14px;"></i></button>
                        </div>
                    </div>
                    <div class="notification-body" id="notification-drawer-body">
                        Loading...
                    </div>
                </div>
            `;
            document.body.insertAdjacentHTML('beforeend', drawerHtml);
        }

        if (window.lucide) lucide.createIcons();
        fetchUnreadCount();
        setInterval(fetchUnreadCount, 10000);
    }

    return { init, toggleDrawer, markAsRead, markAllAsRead };
})();

// Auto-inject on ready
document.addEventListener('DOMContentLoaded', () => {
    GemSidebar.inject();
    GemNotifications.init();
});
