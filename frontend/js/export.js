/* ============================================================
   GEM Tender — Universal Export Utility v1.0
   Provides CSV, Excel (TSV), and PDF export for any data table.
   Include this script on pages that need export buttons.
   ============================================================ */

const GemExport = (() => {

    /**
     * Export an array of objects as a CSV file download.
     * @param {Object[]} data - Array of row objects
     * @param {string} filename - Name for the downloaded file (without extension)
     * @param {string[]} [columns] - Optional ordered column keys. If omitted, uses Object.keys of first row.
     * @param {Object} [headerMap] - Optional { key: 'Display Header' } mapping
     */
    function toCSV(data, filename = 'export', columns, headerMap) {
        if (!data || data.length === 0) {
            showToast?.('No data to export', 'warning');
            return;
        }

        const cols = columns || Object.keys(data[0]);
        const headers = cols.map(c => headerMap?.[c] || formatHeader(c));

        const escape = (val) => {
            if (val === null || val === undefined) return '';
            const str = String(val);
            if (str.includes(',') || str.includes('"') || str.includes('\n')) {
                return '"' + str.replace(/"/g, '""') + '"';
            }
            return str;
        };

        const rows = [
            headers.map(escape).join(','),
            ...data.map(row => cols.map(c => escape(row[c])).join(','))
        ];

        downloadFile(rows.join('\r\n'), `${filename}.csv`, 'text/csv;charset=utf-8;');
    }

    /**
     * Export an HTML table element as CSV.
     * @param {string} tableSelector - CSS selector for the table
     * @param {string} filename - Download filename
     */
    function tableToCSV(tableSelector, filename = 'table_export') {
        const table = document.querySelector(tableSelector);
        if (!table) {
            showToast?.('Table not found', 'error');
            return;
        }

        const rows = [];
        table.querySelectorAll('tr').forEach(tr => {
            const cells = [];
            tr.querySelectorAll('th, td').forEach(td => {
                let val = td.innerText.trim();
                if (val.includes(',') || val.includes('"') || val.includes('\n')) {
                    val = '"' + val.replace(/"/g, '""') + '"';
                }
                cells.push(val);
            });
            rows.push(cells.join(','));
        });

        downloadFile(rows.join('\r\n'), `${filename}.csv`, 'text/csv;charset=utf-8;');
    }

    /**
     * Export data as a styled PDF using browser print.
     * Creates a hidden iframe with a print-friendly table and triggers print.
     * @param {Object[]} data - Array of row objects
     * @param {string} title - Document title
     * @param {string[]} [columns] - Ordered column keys
     * @param {Object} [headerMap] - { key: 'Header' } mapping
     */
    function toPDF(data, title = 'Report', columns, headerMap) {
        if (!data || data.length === 0) {
            showToast?.('No data to export', 'warning');
            return;
        }

        const cols = columns || Object.keys(data[0]);
        const headers = cols.map(c => headerMap?.[c] || formatHeader(c));

        const headerRow = headers.map(h => `<th>${h}</th>`).join('');
        const bodyRows = data.map(row =>
            '<tr>' + cols.map(c => `<td>${row[c] ?? ''}</td>`).join('') + '</tr>'
        ).join('');

        const html = `
<!DOCTYPE html>
<html>
<head>
<title>${title}</title>
<style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Segoe UI', system-ui, sans-serif; padding: 30px; color: #1e293b; }
    h1 { font-size: 1.4rem; margin-bottom: 4px; color: #0f172a; }
    .meta { font-size: 0.75rem; color: #64748b; margin-bottom: 16px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
    th { background: #1e293b; color: white; padding: 8px 10px; text-align: left; font-weight: 600; }
    td { padding: 7px 10px; border-bottom: 1px solid #e2e8f0; }
    tr:nth-child(even) td { background: #f8fafc; }
    .footer { margin-top: 20px; font-size: 0.65rem; color: #94a3b8; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 10px; }
    @media print { body { padding: 10px; } }
</style>
</head>
<body>
    <h1>${title}</h1>
    <div class="meta">Generated on ${new Date().toLocaleString()} • GEM Tender Evaluation System</div>
    <table>
        <thead><tr>${headerRow}</tr></thead>
        <tbody>${bodyRows}</tbody>
    </table>
    <div class="footer">Confidential — GEM Procurement Intelligence • ${data.length} records</div>
</body>
</html>`;

        const iframe = document.createElement('iframe');
        iframe.style.position = 'fixed';
        iframe.style.top = '-10000px';
        iframe.style.left = '-10000px';
        iframe.style.width = '1px';
        iframe.style.height = '1px';
        document.body.appendChild(iframe);

        iframe.contentDocument.open();
        iframe.contentDocument.write(html);
        iframe.contentDocument.close();

        iframe.onload = () => {
            setTimeout(() => {
                iframe.contentWindow.print();
                setTimeout(() => iframe.remove(), 2000);
            }, 250);
        };

        // Fallback: trigger load
        setTimeout(() => {
            try { iframe.contentWindow.print(); } catch(e) {}
            setTimeout(() => iframe.remove(), 2000);
        }, 1000);
    }

    /**
     * Export an HTML table as a styled PDF via print.
     * @param {string} tableSelector - CSS selector for the table
     * @param {string} title - Document title
     */
    function tableToPDF(tableSelector, title = 'Report') {
        const table = document.querySelector(tableSelector);
        if (!table) {
            showToast?.('Table not found', 'error');
            return;
        }

        // Extract data from the table
        const rows = [];
        const headerCells = [];
        table.querySelectorAll('thead th').forEach(th => headerCells.push(th.innerText.trim()));

        table.querySelectorAll('tbody tr').forEach(tr => {
            const row = {};
            tr.querySelectorAll('td').forEach((td, i) => {
                row[headerCells[i] || `col_${i}`] = td.innerText.trim();
            });
            rows.push(row);
        });

        if (rows.length === 0) {
            showToast?.('No data to export', 'warning');
            return;
        }

        toPDF(rows, title, headerCells.length > 0 ? headerCells : undefined);
    }

    // ── Helpers ────────────────────────────────────────────────

    function downloadFile(content, filename, mimeType) {
        const blob = new Blob(['\ufeff' + content], { type: mimeType });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        link.style.display = 'none';
        document.body.appendChild(link);
        link.click();
        setTimeout(() => {
            URL.revokeObjectURL(link.href);
            link.remove();
        }, 500);

        showToast?.(`Exported: ${filename}`, 'success');
    }

    function formatHeader(key) {
        return key
            .replace(/_/g, ' ')
            .replace(/([a-z])([A-Z])/g, '$1 $2')
            .replace(/\b\w/g, c => c.toUpperCase());
    }

    /**
     * Inject export buttons into a container.
     * @param {string} containerSelector - Where to inject buttons
     * @param {Function} getDataFn - Function that returns { data, columns?, headerMap?, filename?, title? }
     */
    function injectButtons(containerSelector, getDataFn) {
        const container = document.querySelector(containerSelector);
        if (!container) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'export-btn-group';
        wrapper.innerHTML = `
            <button class="btn btn-sm export-csv-btn" title="Export CSV">
                <i data-lucide="file-spreadsheet" style="width:14px;height:14px;"></i> CSV
            </button>
            <button class="btn btn-sm export-pdf-btn" title="Export PDF">
                <i data-lucide="file-text" style="width:14px;height:14px;"></i> PDF
            </button>
        `;

        wrapper.querySelector('.export-csv-btn').addEventListener('click', () => {
            const { data, columns, headerMap, filename } = getDataFn();
            toCSV(data, filename || 'export', columns, headerMap);
        });

        wrapper.querySelector('.export-pdf-btn').addEventListener('click', () => {
            const { data, columns, headerMap, filename, title } = getDataFn();
            toPDF(data, title || 'Report', columns, headerMap);
        });

        container.appendChild(wrapper);
        if (window.lucide) lucide.createIcons();
    }

    // Inject global styles for export buttons
    function injectStyles() {
        if (document.getElementById('gem-export-styles')) return;
        const style = document.createElement('style');
        style.id = 'gem-export-styles';
        style.textContent = `
            .export-btn-group {
                display: inline-flex;
                gap: 6px;
                align-items: center;
            }
            .export-csv-btn, .export-pdf-btn {
                display: inline-flex;
                align-items: center;
                gap: 4px;
                font-size: 0.75rem;
                padding: 5px 10px;
                border-radius: 6px;
                border: 1px solid rgba(255,255,255,0.1);
                background: rgba(255,255,255,0.04);
                color: var(--text, #e2e8f0);
                cursor: pointer;
                transition: all 0.2s ease;
                white-space: nowrap;
            }
            .export-csv-btn:hover {
                background: rgba(16, 185, 129, 0.15);
                border-color: #10b981;
                color: #10b981;
            }
            .export-pdf-btn:hover {
                background: rgba(239, 68, 68, 0.15);
                border-color: #ef4444;
                color: #ef4444;
            }
        `;
        document.head.appendChild(style);
    }

    // Auto-inject styles
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', injectStyles);
    } else {
        injectStyles();
    }

    return { toCSV, toPDF, tableToCSV, tableToPDF, injectButtons };
})();
