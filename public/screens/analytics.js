// Analytics module logic for public/screens/analytics.html.
// Loaded after api.js — relies on the global `api`, `apiJson`, and CashPilot
// helpers it defines. All figures are computed from real /invoices and
// /dashboard data; nothing here is hardcoded.

CashPilot.initPage();

const CATEGORY_COLORS = ['#22C55E', '#A3E635', '#FBBF24', '#FB923C', '#EF4444', '#9CA3AF', '#3B82F6', '#8B5CF6'];
const STATUS_COLORS = { paid: '#22C55E', pending: '#3B82F6', due_soon: '#F59E0B', overdue: '#EF4444' };

let allInvoices = [];
let dashboardData = null;
let currentRange = { key: '30', from: null, to: null };
let charts = { trend: null, category: null, bar: null, status: null };

// ==========================================
// STATUS (mirrors public/screens/invoices.html's computeStatus for
// consistent Paid/Overdue/Due Soon/Pending semantics across the app)
// ==========================================
function computeStatus(invoice) {
    if (invoice.is_paid) {
        return { key: "paid", label: "Paid" };
    }
    const due = CashPilot.parseBackendDate(invoice.due_date);
    if (due) {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const diffDays = Math.ceil((due - today) / (1000 * 60 * 60 * 24));
        if (diffDays < 0) return { key: "overdue", label: "Overdue" };
        if (diffDays <= 3) return { key: "due_soon", label: "Due Soon" };
    }
    return { key: "pending", label: "Pending" };
}

// ==========================================
// DATE RANGE
// ==========================================
function computeRangeDates(key) {
    if (key === 'custom') {
        return { from: currentRange.from, to: currentRange.to };
    }
    const days = Number(key);
    // Symmetric around today: presets must catch both invoices due soon
    // (future due dates — the common case for unpaid bills) and invoices
    // due/overdue in the recent past, not just a backward-only window.
    const from = new Date();
    from.setDate(from.getDate() - days);
    from.setHours(0, 0, 0, 0);
    const to = new Date();
    to.setDate(to.getDate() + days);
    to.setHours(23, 59, 59, 999);
    return { from, to };
}

function setActiveRangeButton(key) {
    document.querySelectorAll('.range-btn').forEach((btn) => {
        const active = btn.dataset.range === key;
        btn.classList.toggle('bg-white', active);
        btn.classList.toggle('shadow-sm', active);
        btn.classList.toggle('font-bold', active);
        btn.classList.toggle('text-on-surface', active);
        btn.classList.toggle('text-on-surface-variant', !active);
    });
}

function formatRangeSubtitle(from, to) {
    const opts = { month: 'short', day: 'numeric', year: 'numeric' };
    return `${from.toLocaleDateString(undefined, opts)} – ${to.toLocaleDateString(undefined, opts)}`;
}

document.getElementById('rangeButtons').addEventListener('click', (e) => {
    const btn = e.target.closest('.range-btn');
    if (!btn) return;
    const key = btn.dataset.range;

    if (key === 'custom') {
        document.getElementById('customRangeInputs').classList.remove('hidden');
        document.getElementById('customRangeInputs').classList.add('flex');
        setActiveRangeButton('custom');
        return;
    }

    document.getElementById('customRangeInputs').classList.add('hidden');
    document.getElementById('customRangeInputs').classList.remove('flex');
    currentRange.key = key;
    setActiveRangeButton(key);
    renderAll();
});

document.getElementById('applyCustomRange').addEventListener('click', () => {
    const fromVal = document.getElementById('customFrom').value;
    const toVal = document.getElementById('customTo').value;
    if (!fromVal || !toVal) {
        CashPilot.toast('Pick both a start and end date.', 'error');
        return;
    }
    const from = new Date(fromVal);
    const to = new Date(toVal);
    to.setHours(23, 59, 59, 999);
    if (from > to) {
        CashPilot.toast('Start date must be before end date.', 'error');
        return;
    }
    currentRange.key = 'custom';
    currentRange.from = from;
    currentRange.to = to;
    renderAll();
});

// ==========================================
// LOAD
// ==========================================
async function loadAll(manual) {
    try {
        const [dashRes, invRes] = await Promise.all([api('/dashboard'), api('/invoices')]);

        if (!dashRes.ok || !invRes.ok) throw new Error('Could not load analytics data');

        dashboardData = await dashRes.json();
        allInvoices = await invRes.json();

        document.getElementById('analyticsErrorBanner').classList.add('hidden');

        setText('sidebarBalance', CashPilot.formatCurrency(dashboardData.current_balance));
        setText('sidebarRunway', `${Math.ceil(dashboardData.cash_runway)} days runway`);

        renderAll();

        if (manual) CashPilot.toast('Analytics refreshed.', 'success');

    } catch (err) {
        document.getElementById('analyticsErrorText').textContent = err.message || 'Something went wrong loading analytics.';
        document.getElementById('analyticsErrorBanner').classList.remove('hidden');
        CashPilot.toast('Could not load analytics data.', 'error');
    }
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

// ==========================================
// DATES FOR TIME-SERIES USE ONLY
// KPI cards, Invoice Status, Vendor Analytics, Expense Categories, and
// Invoice Analytics always read the complete authenticated dataset
// (`allInvoices`) below in renderAll() — the selected range never touches
// them, and an unparseable/missing due_date can never make an invoice
// disappear from any of those. Only the two time-series charts (Cash Flow
// Trend, Income vs Expenses) are range-filtered, and for those, due_date is
// preferred but invoice_date is used whenever due_date can't be parsed.
// ==========================================
function getEffectiveDate(inv) {
    return CashPilot.parseBackendDate(inv.due_date) || CashPilot.parseBackendDate(inv.invoice_date) || null;
}

function getTimeSeriesInvoices() {
    const { from, to } = computeRangeDates(currentRange.key);
    if (!from || !to) return allInvoices;

    return allInvoices.filter((inv) => {
        const effectiveDate = getEffectiveDate(inv);
        // No due_date AND no invoice_date at all — there's genuinely no time
        // axis to place this on, so it can't appear in a time-series chart.
        // (It still appears in every complete-dataset widget above.)
        if (!effectiveDate) return false;
        return effectiveDate >= from && effectiveDate <= to;
    });
}

// ==========================================
// ORCHESTRATOR
// ==========================================
function renderAll() {
    const { from, to } = computeRangeDates(currentRange.key);
    if (from && to) setText('rangeSubtitle', formatRangeSubtitle(from, to));

    const timeSeriesInvoices = getTimeSeriesInvoices();

    // Complete dataset — unaffected by the selected date range.
    renderKPIs(allInvoices);
    renderExpenseCategories(allInvoices);
    renderInvoiceStatus(allInvoices);
    renderVendorTable(allInvoices);
    renderInvoiceAnalytics(allInvoices);

    // Time-series only — these are the sole consumers of the date range.
    renderCashFlowTrend(timeSeriesInvoices, from, to);
    renderIncomeExpensesBar(timeSeriesInvoices, from, to);
}

// ==========================================
// KPI CARDS
// ==========================================
function renderKPIs(invoices) {
    const income = invoices.filter((i) => i.transaction_type === 'receivable').reduce((s, i) => s + i.amount, 0);
    const expenses = invoices.filter((i) => i.transaction_type === 'payable').reduce((s, i) => s + i.amount, 0);
    const net = income - expenses;
    const outstanding = invoices.filter((i) => !i.is_paid);
    const paid = invoices.filter((i) => i.is_paid);

    setText('kpiIncome', CashPilot.formatCurrency(income));
    setText('kpiIncomeSub', `${invoices.filter((i) => i.transaction_type === 'receivable').length} receivable invoice(s)`);

    setText('kpiExpenses', CashPilot.formatCurrency(expenses));
    setText('kpiExpensesSub', `${invoices.filter((i) => i.transaction_type === 'payable').length} payable invoice(s)`);

    setText('kpiNet', (net >= 0 ? '+' : '') + CashPilot.formatCurrency(net));
    const netEl = document.getElementById('kpiNet');
    netEl.className = `text-headline-md font-headline-md ${net >= 0 ? 'text-emerald-600' : 'text-error'}`;
    const netIcon = document.getElementById('kpiNetIcon');
    netIcon.textContent = net >= 0 ? 'trending_up' : 'trending_down';
    netIcon.className = `material-symbols-outlined text-[20px] ${net >= 0 ? 'text-emerald-600' : 'text-error'}`;
    setText('kpiNetSub', net >= 0 ? 'Income exceeds expenses' : 'Expenses exceed income');

    setText('kpiOutstanding', String(outstanding.length));
    setText('kpiOutstandingSub', CashPilot.formatCurrency(outstanding.reduce((s, i) => s + i.amount, 0)) + ' total');

    setText('kpiPaid', String(paid.length));
    setText('kpiPaidSub', CashPilot.formatCurrency(paid.reduce((s, i) => s + i.amount, 0)) + ' total');
}

// ==========================================
// ADAPTIVE BUCKETING (shared by trend line + bar chart)
// ==========================================
function buildBuckets(invoices, from, to) {

    if (!from || !to) return { labels: [], income: [], expenses: [], net: [] };

    const spanDays = Math.max(1, Math.round((to - from) / (1000 * 60 * 60 * 24)));
    let granularity = 'day';
    if (spanDays > 120) granularity = 'month';
    else if (spanDays > 14) granularity = 'week';

    const buckets = [];
    const cursor = new Date(from);
    cursor.setHours(0, 0, 0, 0);

    while (cursor <= to) {
        const start = new Date(cursor);
        let end;
        let label;

        if (granularity === 'day') {
            end = new Date(start); end.setHours(23, 59, 59, 999);
            label = start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
            cursor.setDate(cursor.getDate() + 1);
        } else if (granularity === 'week') {
            end = new Date(start); end.setDate(end.getDate() + 6); end.setHours(23, 59, 59, 999);
            label = start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
            cursor.setDate(cursor.getDate() + 7);
        } else {
            end = new Date(start.getFullYear(), start.getMonth() + 1, 0, 23, 59, 59, 999);
            label = start.toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
            cursor.setMonth(cursor.getMonth() + 1);
            cursor.setDate(1);
        }

        buckets.push({ start, end, label, income: 0, expenses: 0 });
    }

    invoices.forEach((inv) => {
        const effectiveDate = getEffectiveDate(inv);
        if (!effectiveDate) return;
        const bucket = buckets.find((b) => effectiveDate >= b.start && effectiveDate <= b.end);
        if (!bucket) return;
        if (inv.transaction_type === 'receivable') bucket.income += inv.amount;
        else bucket.expenses += inv.amount;
    });

    return {
        labels: buckets.map((b) => b.label),
        income: buckets.map((b) => b.income),
        expenses: buckets.map((b) => b.expenses),
        net: buckets.map((b) => b.income - b.expenses),
    };
}

// ==========================================
// CASH FLOW TREND (line)
// ==========================================
function renderCashFlowTrend(invoices, from, to) {
    const ctx = document.getElementById('chartCashFlowTrend');
    const emptyState = document.getElementById('trendEmptyState');
    const data = buildBuckets(invoices, from, to);
    const hasData = data.net.some((v) => v !== 0);

    if (charts.trend) { charts.trend.destroy(); charts.trend = null; }

    if (!invoices.length || !hasData) {
        emptyState.innerHTML = CashPilot.emptyState({
            icon: 'show_chart',
            title: 'No cash flow data yet',
            description: 'Add invoices with due dates to see your cash flow trend.',
            actionLabel: 'Add Invoice',
            actionHref: '/screens/invoices.html',
        });
        emptyState.classList.remove('hidden');
        return;
    }
    emptyState.classList.add('hidden');

    charts.trend = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.labels,
            datasets: [{
                label: 'Net Cash Flow',
                data: data.net,
                borderColor: '#4648D4',
                backgroundColor: 'rgba(70,72,212,0.1)',
                fill: true,
                tension: 0.35,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
        },
    });
}

// ==========================================
// EXPENSE CATEGORIES (doughnut)
// ==========================================
function renderExpenseCategories(invoices) {
    const ctx = document.getElementById('chartExpenseCategories');
    const emptyState = document.getElementById('categoryEmptyState');
    const legend = document.getElementById('categoryLegend');

    const categories = {};
    invoices.filter((i) => i.transaction_type === 'payable').forEach((i) => {
        categories[i.category || 'Uncategorized'] = (categories[i.category || 'Uncategorized'] || 0) + i.amount;
    });

    const entries = Object.entries(categories).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);

    if (charts.category) { charts.category.destroy(); charts.category = null; }

    if (!entries.length) {
        emptyState.innerHTML = CashPilot.emptyState({
            icon: 'donut_small',
            title: 'No expenses yet',
            description: 'Add payable invoices to see spend by category.',
            actionLabel: 'Add Invoice',
            actionHref: '/screens/invoices.html',
        });
        emptyState.classList.remove('hidden');
        legend.innerHTML = '';
        return;
    }
    emptyState.classList.add('hidden');

    charts.category = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: entries.map(([k]) => k),
            datasets: [{ data: entries.map(([, v]) => v), backgroundColor: CATEGORY_COLORS, borderWidth: 3, borderColor: '#fff' }],
        },
        options: { responsive: true, maintainAspectRatio: false, cutout: '70%', plugins: { legend: { display: false } } },
    });

    legend.innerHTML = entries.map(([label, value], i) => `
        <div class="flex items-center justify-between gap-2 min-w-0">
            <span class="flex items-center gap-1.5 text-on-surface-variant min-w-0 flex-1">
                <span class="w-2 h-2 rounded-full flex-shrink-0" style="background:${CATEGORY_COLORS[i % CATEGORY_COLORS.length]}"></span>
                <span class="truncate" title="${CashPilot.escapeHtml(label)}">${CashPilot.escapeHtml(label)}</span>
            </span>
            <span class="font-mono-data font-semibold flex-shrink-0">${CashPilot.formatCurrency(value)}</span>
        </div>
    `).join('');
}

// ==========================================
// INCOME VS EXPENSES (bar)
// ==========================================
function renderIncomeExpensesBar(invoices, from, to) {
    const ctx = document.getElementById('chartIncomeExpenses');
    const emptyState = document.getElementById('barEmptyState');
    const data = buildBuckets(invoices, from, to);
    const hasData = data.income.some((v) => v > 0) || data.expenses.some((v) => v > 0);

    if (charts.bar) { charts.bar.destroy(); charts.bar = null; }

    if (!invoices.length || !hasData) {
        emptyState.innerHTML = CashPilot.emptyState({
            icon: 'bar_chart',
            title: 'No data in this range',
            description: 'Try a different date range, or add some invoices.',
            actionLabel: 'Add Invoice',
            actionHref: '/screens/invoices.html',
        });
        emptyState.classList.remove('hidden');
        return;
    }
    emptyState.classList.add('hidden');

    charts.bar = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.labels,
            datasets: [
                { label: 'Income', data: data.income, backgroundColor: '#4648D4' },
                { label: 'Expenses', data: data.expenses, backgroundColor: '#EF4444' },
            ],
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
    });
}

// ==========================================
// INVOICE STATUS DISTRIBUTION (doughnut)
// ==========================================
function renderInvoiceStatus(invoices) {
    const ctx = document.getElementById('chartInvoiceStatus');
    const emptyState = document.getElementById('statusEmptyState');
    const legend = document.getElementById('statusLegend');

    const counts = { paid: 0, pending: 0, due_soon: 0, overdue: 0 };
    invoices.forEach((inv) => { counts[computeStatus(inv).key]++; });

    const labels = { paid: 'Paid', pending: 'Pending', due_soon: 'Due Soon', overdue: 'Overdue' };
    const entries = Object.entries(counts).filter(([, v]) => v > 0);

    if (charts.status) { charts.status.destroy(); charts.status = null; }

    if (!invoices.length || !entries.length) {
        emptyState.innerHTML = CashPilot.emptyState({
            icon: 'receipt_long',
            title: 'No invoices yet',
            description: 'Upload or add your first invoice to see status breakdown.',
            actionLabel: 'Add Invoice',
            actionHref: '/screens/invoices.html',
        });
        emptyState.classList.remove('hidden');
        legend.innerHTML = '';
        return;
    }
    emptyState.classList.add('hidden');

    charts.status = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: entries.map(([k]) => labels[k]),
            datasets: [{ data: entries.map(([, v]) => v), backgroundColor: entries.map(([k]) => STATUS_COLORS[k]), borderWidth: 3, borderColor: '#fff' }],
        },
        options: { responsive: true, maintainAspectRatio: false, cutout: '70%', plugins: { legend: { display: false } } },
    });

    legend.innerHTML = entries.map(([key, value]) => `
        <div class="flex items-center justify-between">
            <span class="flex items-center gap-1.5 text-on-surface-variant">
                <span class="w-2 h-2 rounded-full" style="background:${STATUS_COLORS[key]}"></span>
                ${labels[key]}
            </span>
            <span class="font-mono-data font-semibold">${value}</span>
        </div>
    `).join('');
}

// ==========================================
// VENDOR ANALYTICS
// ==========================================
function renderVendorTable(invoices) {
    const tbody = document.getElementById('vendorTableBody');
    const today = new Date(); today.setHours(0, 0, 0, 0);

    const vendors = {};
    invoices.filter((i) => i.transaction_type === 'payable').forEach((inv) => {
        const key = inv.vendor || 'Unknown Vendor';
        if (!vendors[key]) vendors[key] = { count: 0, total: 0, overdue: 0 };
        vendors[key].count++;
        vendors[key].total += inv.amount;
        const due = CashPilot.parseBackendDate(inv.due_date);
        if (!inv.is_paid && due && due < today) vendors[key].overdue += inv.amount;
    });

    const rows = Object.entries(vendors).sort((a, b) => b[1].total - a[1].total).slice(0, 8);

    if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="4">${CashPilot.emptyState({
            icon: 'storefront',
            title: 'No vendors yet',
            description: 'Add payable invoices to see vendor spend and overdue totals.',
            actionLabel: 'Add Invoice',
            actionHref: '/screens/invoices.html',
        })}</td></tr>`;
        return;
    }

    tbody.innerHTML = rows.map(([vendor, stats]) => `
        <tr class="hover:bg-surface-container-low/50 transition-colors">
            <td class="px-lg py-md">
                <div class="flex items-center gap-sm">
                    <div class="h-8 w-8 rounded-full bg-surface-container flex items-center justify-center font-bold text-primary text-xs">${CashPilot.escapeHtml((vendor || 'V').charAt(0))}</div>
                    <span class="text-body-sm font-semibold text-on-surface">${CashPilot.escapeHtml(vendor)}</span>
                </div>
            </td>
            <td class="px-lg py-md font-mono-data text-body-sm text-right">${stats.count}</td>
            <td class="px-lg py-md font-mono-data text-body-sm font-bold text-right">${CashPilot.formatCurrency(stats.total)}</td>
            <td class="px-lg py-md text-right">
                ${stats.overdue > 0
                    ? `<span class="px-2 py-1 rounded-full bg-error-container text-on-error-container text-[11px] font-bold">${CashPilot.formatCurrency(stats.overdue)}</span>`
                    : `<span class="text-on-surface-variant text-xs">—</span>`}
            </td>
        </tr>
    `).join('');
}

// ==========================================
// INVOICE ANALYTICS (avg value, payment delay)
// ==========================================
function renderInvoiceAnalytics(invoices) {
    const avg = invoices.length ? invoices.reduce((s, i) => s + i.amount, 0) / invoices.length : 0;
    setText('avgInvoiceValue', invoices.length ? CashPilot.formatCurrency(avg) : '--');

    const delays = [];
    invoices.forEach((inv) => {
        if (!inv.is_paid || !inv.paid_at) return;
        const due = CashPilot.parseBackendDate(inv.due_date);
        const paid = CashPilot.parseBackendDate(inv.paid_at);
        if (!due || !paid) return;
        delays.push(Math.round((paid - due) / (1000 * 60 * 60 * 24)));
    });

    if (delays.length) {
        const avgDelay = Math.round(delays.reduce((s, d) => s + d, 0) / delays.length);
        setText('avgPaymentDelay', `${avgDelay >= 0 ? avgDelay : 0} day${Math.abs(avgDelay) === 1 ? '' : 's'}`);
        const delayEl = document.getElementById('avgPaymentDelay');
        delayEl.className = `text-headline-md font-headline-md ${avgDelay > 0 ? 'text-error' : 'text-emerald-600'}`;
        setText('avgPaymentDelaySub', avgDelay > 0 ? 'Paid after the due date, on average' : 'Paid on or before the due date, on average');
    } else {
        setText('avgPaymentDelay', '--');
        document.getElementById('avgPaymentDelay').className = 'text-headline-md font-headline-md text-on-surface';
        setText('avgPaymentDelaySub', 'No paid invoices with due dates yet.');
    }

    const paidCount = invoices.filter((i) => i.is_paid).length;
    const unpaidCount = invoices.length - paidCount;
    setText('paidVsUnpaid', invoices.length ? `${paidCount} paid / ${unpaidCount} unpaid` : '--');
}

// ==========================================
// EXPORT MENU
// ==========================================
document.getElementById('exportMenuBtn').addEventListener('click', (e) => {
    e.stopPropagation();
    document.getElementById('exportMenu').classList.toggle('hidden');
});
document.addEventListener('click', () => document.getElementById('exportMenu').classList.add('hidden'));

function escapeCSVCell(value) {
    const s = String(value ?? '');
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

document.getElementById('exportCsvBtn').addEventListener('click', () => {
    const invoices = allInvoices;
    if (!invoices.length) { CashPilot.toast('No invoices to export yet.', 'error'); return; }

    const headers = ['Vendor', 'Invoice Number', 'Amount', 'Due Date', 'Category', 'Payment Type', 'Status', 'Paid At'];
    const lines = [headers.join(',')];
    invoices.forEach((inv) => {
        lines.push([
            inv.vendor, `INV-${inv.id}`, inv.amount, inv.due_date, inv.category,
            inv.transaction_type, computeStatus(inv).label, inv.paid_at || '',
        ].map(escapeCSVCell).join(','));
    });

    downloadBlob(new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' }), `analytics-${new Date().toISOString().slice(0, 10)}.csv`);
    CashPilot.toast('CSV exported.', 'success');
    document.getElementById('exportMenu').classList.add('hidden');
});

document.getElementById('exportPdfBtn').addEventListener('click', () => {
    const invoices = allInvoices;
    if (!invoices.length) { CashPilot.toast('No invoices to export yet.', 'error'); return; }

    try {
        const { jsPDF } = window.jspdf;
        const doc = new jsPDF();
        let y = 16;

        doc.setFontSize(18);
        doc.text('CashPilot AI — Analytics Report', 14, y);
        y += 8;
        doc.setFontSize(10);
        doc.setTextColor(100);
        doc.text('Summary below covers all invoices on this account.', 14, y);
        y += 10;

        const income = invoices.filter((i) => i.transaction_type === 'receivable').reduce((s, i) => s + i.amount, 0);
        const expenses = invoices.filter((i) => i.transaction_type === 'payable').reduce((s, i) => s + i.amount, 0);

        doc.setTextColor(20);
        doc.setFontSize(12);
        [
            `Total Income: ${CashPilot.formatCurrency(income)}`,
            `Total Expenses: ${CashPilot.formatCurrency(expenses)}`,
            `Net Cash Flow: ${CashPilot.formatCurrency(income - expenses)}`,
            `Outstanding Invoices: ${invoices.filter((i) => !i.is_paid).length}`,
            `Paid Invoices: ${invoices.filter((i) => i.is_paid).length}`,
        ].forEach((line) => { doc.text(line, 14, y); y += 7; });

        y += 4;
        const trendCanvas = document.getElementById('chartCashFlowTrend');
        if (trendCanvas && charts.trend) {
            try {
                const imgData = trendCanvas.toDataURL('image/png', 1.0);
                doc.text(`Cash Flow Trend (${document.getElementById('rangeSubtitle').textContent})`, 14, y);
                y += 4;
                doc.addImage(imgData, 'PNG', 14, y, 180, 70);
                y += 78;
            } catch (_) { /* canvas may be tainted in rare cross-origin cases — skip the chart image */ }
        }

        if (y > 250) { doc.addPage(); y = 16; }

        doc.setFontSize(13);
        doc.text('Top Vendors', 14, y);
        y += 7;
        doc.setFontSize(10);

        const vendors = {};
        invoices.filter((i) => i.transaction_type === 'payable').forEach((inv) => {
            vendors[inv.vendor] = (vendors[inv.vendor] || 0) + inv.amount;
        });
        Object.entries(vendors).sort((a, b) => b[1] - a[1]).slice(0, 10).forEach(([vendor, total]) => {
            if (y > 280) { doc.addPage(); y = 16; }
            doc.text(`${vendor} — ${CashPilot.formatCurrency(total)}`, 14, y);
            y += 6;
        });

        doc.save(`analytics-${new Date().toISOString().slice(0, 10)}.pdf`);
        CashPilot.toast('PDF exported.', 'success');
    } catch (err) {
        console.error(err);
        CashPilot.toast('Could not generate the PDF.', 'error');
    }

    document.getElementById('exportMenu').classList.add('hidden');
});

// ==========================================
// INIT
// ==========================================
setActiveRangeButton('30');
loadAll();
setInterval(() => loadAll(false), 60000);
