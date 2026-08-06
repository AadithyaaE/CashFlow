// AI CFO page — orchestrates /cfo/overview, /cfo/ai-recommendations, and
// /cfo/scenario. Every number rendered here comes straight from the backend;
// this file only formats and displays it (and, for the scenario form,
// collects the user's hypothetical input before sending it to the server).

CashPilot.initPage();

let lastOverview = null;
let lastDashboardData = null;
let forecastChartInstance = null;

const PRIORITY_COLOR = {
    Critical: "text-red-600",
    High: "text-orange-600",
    Medium: "text-yellow-600",
    Low: "text-green-600",
};

const PRIORITY_BADGE = {
    Critical: "bg-red-100 text-red-700",
    High: "bg-orange-100 text-orange-700",
    Medium: "bg-yellow-100 text-yellow-700",
    Low: "bg-green-100 text-green-700",
};

const SEVERITY_BADGE = {
    critical: "bg-red-100 text-red-700",
    high: "bg-orange-100 text-orange-700",
    medium: "bg-yellow-100 text-yellow-700",
    low: "bg-green-100 text-green-700",
};

window.addEventListener("load", () => {
    loadSidebar();
    loadOverview();
    loadAiRecommendations();
});

document.getElementById("refreshBtn").addEventListener("click", () => {
    loadOverview();
    loadAiRecommendations();
});

document.getElementById("retryOverviewBtn").addEventListener("click", () => {
    loadOverview();
});

// ---------------------------------------------------------------------------
// Sidebar (reuses the existing /dashboard endpoint, same as other screens)
// ---------------------------------------------------------------------------

async function loadSidebar() {
    try {
        const data = await CashPilot.apiJson("/dashboard");
        lastDashboardData = data;
        setText("sidebarBalance", CashPilot.formatCurrency(data.current_balance));
        setText("sidebarRunway", `${Math.ceil(data.cash_runway)} days runway`);
        renderFinancialOverviewStats();
    } catch (_) {
        // Non-critical widget — the rest of the page still works without it.
    }
}

// Financial Overview stat tiles reuse data already fetched for the sidebar
// (/dashboard) and the main overview (/cfo/overview) — no extra API calls.
function renderFinancialOverviewStats() {
    if (!lastDashboardData || !lastOverview) return;

    const metrics = lastOverview.health_score.metrics;
    const criticalPayables = lastOverview.payment_recommendations.filter((r) => r.priority === "Critical");
    const criticalTotal = criticalPayables.reduce((sum, r) => sum + r.amount, 0);

    setText("overviewCurrentBalance", CashPilot.formatCurrency(lastDashboardData.current_balance));
    setText("overviewRunway", `${metrics.runway_days} days`);
    setText("overviewPayables", CashPilot.formatCurrency(metrics.total_outstanding_payables));
    setText("overviewReceivables", CashPilot.formatCurrency(metrics.total_outstanding_receivables));
    setText(
        "overviewCriticalPayments",
        criticalPayables.length ? `${criticalPayables.length} (${CashPilot.formatCurrency(criticalTotal)})` : "None"
    );
}

// ---------------------------------------------------------------------------
// Overview: Health Score, Forecast, Recommendations, Risks
// ---------------------------------------------------------------------------

async function loadOverview() {
    document.getElementById("overviewError").classList.add("hidden");
    document.getElementById("cfoLoading").classList.remove("hidden");
    document.getElementById("cfoContent").classList.add("hidden");

    try {
        const data = await CashPilot.apiJson("/cfo/overview");
        lastOverview = data;

        renderHealthScore(data.health_score);
        renderForecast(data.forecast);
        renderPaymentRecs(data.payment_recommendations);
        renderReceivableRecs(data.receivable_recommendations);
        renderRisks(data.risks);
        populateScenarioInvoiceOptions();
        renderFinancialOverviewStats();
        populateNegotiationInvoiceOptions();

        document.getElementById("cfoLoading").classList.add("hidden");
        document.getElementById("cfoContent").classList.remove("hidden");
    } catch (err) {
        document.getElementById("cfoLoading").classList.add("hidden");
        document.getElementById("overviewErrorMessage").textContent =
            err.message || "Could not load your AI CFO data.";
        document.getElementById("overviewError").classList.remove("hidden");
    }
}

function renderHealthScore(health) {
    setText("healthScoreValue", String(health.score));
    setText("healthScoreExplanation", health.explanation);

    const bandColor =
        health.rating === "Excellent" ? "text-emerald-600 bg-emerald-50" :
        health.rating === "Good" ? "text-primary bg-primary-fixed/20" :
        health.rating === "Average" ? "text-secondary bg-secondary-container/40" :
        "text-error bg-error-container";

    const labelEl = document.getElementById("healthScoreLabel");
    labelEl.className = `text-xs font-medium px-2 py-0.5 rounded-full mt-1 ${bandColor}`;
    labelEl.textContent = health.rating;

    const ring = document.getElementById("healthGaugeRing");
    const radius = 70;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (Math.max(health.score, 0) / 100) * circumference;
    ring.style.strokeDasharray = `${circumference}`;
    ring.style.strokeDashoffset = `${offset}`;

    const breakdownEl = document.getElementById("healthBreakdown");
    breakdownEl.innerHTML = health.breakdown.map((factor) => `
        <div>
            <div class="flex justify-between text-xs mb-0.5">
                <span class="text-on-surface-variant">${CashPilot.escapeHtml(factor.factor)}</span>
                <span class="font-semibold text-on-surface">${factor.score}/100</span>
            </div>
            <div class="w-full bg-surface-container rounded-full h-1.5 overflow-hidden">
                <div class="h-full bg-primary" style="width:${Math.min(Math.max(factor.score, 0), 100)}%"></div>
            </div>
        </div>
    `).join("");
}

function renderForecast(forecast) {
    const hasActivity = forecast.some((b) => b.incoming > 0 || b.outgoing > 0);
    document.getElementById("forecastEmptyState").classList.toggle("hidden", hasActivity);

    document.getElementById("forecastTableBody").innerHTML = forecast.map((b) => `
        <tr>
            <td class="py-sm pr-md font-semibold text-on-surface">${CashPilot.escapeHtml(b.label)}</td>
            <td class="py-sm pr-md text-right font-mono-data">${CashPilot.formatCurrency(b.opening_balance)}</td>
            <td class="py-sm pr-md text-right font-mono-data text-emerald-600">+${CashPilot.formatCurrency(b.incoming)}</td>
            <td class="py-sm pr-md text-right font-mono-data text-red-600">-${CashPilot.formatCurrency(b.outgoing)}</td>
            <td class="py-sm pr-md text-right font-mono-data font-bold ${b.closing_balance < 0 ? "text-red-600" : "text-on-surface"}">${CashPilot.formatCurrency(b.closing_balance)}</td>
        </tr>
    `).join("");

    const ctx = document.getElementById("forecastChart");
    if (forecastChartInstance) {
        forecastChartInstance.destroy();
        forecastChartInstance = null;
    }

    forecastChartInstance = new Chart(ctx, {
        data: {
            labels: forecast.map((b) => b.label),
            datasets: [
                {
                    type: "bar",
                    label: "Incoming",
                    data: forecast.map((b) => b.incoming),
                    backgroundColor: "#22C55E",
                    borderRadius: 4,
                },
                {
                    type: "bar",
                    label: "Outgoing",
                    data: forecast.map((b) => b.outgoing),
                    backgroundColor: "#EF4444",
                    borderRadius: 4,
                },
                {
                    type: "line",
                    label: "Closing Balance",
                    data: forecast.map((b) => b.closing_balance),
                    borderColor: "#4648D4",
                    backgroundColor: "#4648D4",
                    tension: 0.3,
                    yAxisID: "y1",
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: true },
                y1: { beginAtZero: false, position: "right", grid: { drawOnChartArea: false } },
            },
            plugins: { legend: { position: "bottom" } },
        },
    });
}

function renderRecommendationCard(rec, kind) {
    const badge = PRIORITY_BADGE[rec.priority] || PRIORITY_BADGE.Low;
    return `
        <div class="p-md rounded-xl border border-outline-variant bg-surface-container-low">
            <div class="flex justify-between items-start gap-sm">
                <div>
                    <p class="font-semibold text-on-surface">${CashPilot.escapeHtml(rec.vendor)}</p>
                    <p class="text-xs text-on-surface-variant">${CashPilot.formatCurrency(rec.amount)} &middot; Due ${CashPilot.escapeHtml(rec.due_date || "Unknown")}</p>
                </div>
                <span class="px-sm py-xs rounded-lg font-label-md text-xs ${badge}">${rec.priority}</span>
            </div>
            <p class="text-sm text-on-surface-variant mt-sm leading-relaxed">${CashPilot.escapeHtml(rec.why)}</p>
            <p class="text-xs font-semibold text-primary mt-sm">${CashPilot.escapeHtml(rec.suggested_action)}</p>
        </div>
    `;
}

function renderPaymentRecs(list) {
    document.getElementById("paymentRecsEmpty").classList.toggle("hidden", list.length > 0);
    document.getElementById("paymentRecsList").innerHTML = list.map((r) => renderRecommendationCard(r, "payment")).join("");
}

function renderReceivableRecs(list) {
    document.getElementById("receivableRecsEmpty").classList.toggle("hidden", list.length > 0);
    document.getElementById("receivableRecsList").innerHTML = list.map((r) => renderRecommendationCard(r, "receivable")).join("");
}

function renderRisks(risks) {
    document.getElementById("risksEmpty").classList.toggle("hidden", risks.length > 0);
    document.getElementById("risksList").innerHTML = risks.map((risk) => `
        <div class="p-md rounded-xl border border-outline-variant bg-surface-container-low flex items-start gap-md">
            <span class="px-sm py-xs rounded-lg font-label-md text-xs shrink-0 ${SEVERITY_BADGE[risk.severity] || SEVERITY_BADGE.medium}">${risk.severity}</span>
            <div>
                <p class="font-semibold text-on-surface text-sm">${CashPilot.escapeHtml(risk.title)}</p>
                <p class="text-sm text-on-surface-variant mt-1">${CashPilot.escapeHtml(risk.message)}</p>
            </div>
        </div>
    `).join("");
}

// ---------------------------------------------------------------------------
// Payment Plan generation (reuses the existing GET /payment-plan endpoint —
// the pay-now/delay grouping already built for the old runway.html page)
// ---------------------------------------------------------------------------

document.getElementById("generatePaymentPlanBtn").addEventListener("click", async () => {
    const btn = document.getElementById("generatePaymentPlanBtn");
    const resultEl = document.getElementById("paymentPlanResult");

    btn.disabled = true;
    resultEl.classList.remove("hidden");
    resultEl.innerHTML = `<p class="text-xs text-on-surface-variant flex items-center gap-xs"><span class="material-symbols-outlined animate-spin text-sm">progress_activity</span> Generating plan…</p>`;

    try {
        const plan = await CashPilot.apiJson("/payment-plan");

        const renderGroup = (title, items, colorClass) => `
            <p class="text-xs font-bold uppercase tracking-wider ${colorClass} mb-xs">${title} (${items.length})</p>
            ${items.length
                ? `<ul class="space-y-1 mb-md">${items.map((i) => `<li class="text-xs text-on-surface-variant flex justify-between"><span>${CashPilot.escapeHtml(i.vendor)}</span><span class="font-mono-data">${CashPilot.formatCurrency(i.amount)}</span></li>`).join("")}</ul>`
                : `<p class="text-xs text-on-surface-variant mb-md">None</p>`}
        `;

        resultEl.innerHTML = `
            <p class="text-xs text-on-surface-variant mb-md">Remaining balance after paying now: <span class="font-bold text-on-surface">${CashPilot.formatCurrency(plan.remaining_balance)}</span></p>
            ${renderGroup("Pay Now", plan.pay_now, "text-error")}
            ${renderGroup("Delay", plan.delay, "text-secondary")}
        `;
    } catch (err) {
        resultEl.innerHTML = `<p class="text-xs text-error">${CashPilot.escapeHtml(err.message || "Could not generate a payment plan.")}</p>`;
    } finally {
        btn.disabled = false;
    }
});

// ---------------------------------------------------------------------------
// Vendor Negotiation (reuses the existing POST /vendor-negotiation endpoint
// and the payables already loaded for Payment Planning — no extra fetch)
// ---------------------------------------------------------------------------

let negotiationGoal = "extension";

function populateNegotiationInvoiceOptions() {
    const select = document.getElementById("negotiationInvoiceSelect");
    const unpaidPayables = (lastOverview && lastOverview.payment_recommendations) || [];

    if (!unpaidPayables.length) {
        select.innerHTML = '<option value="">No unpaid payables yet</option>';
        return;
    }

    select.innerHTML = unpaidPayables
        .map((inv) => `<option value="${inv.id}">${CashPilot.escapeHtml(inv.vendor)} — ${CashPilot.formatCurrency(inv.amount)} (due ${CashPilot.escapeHtml(inv.due_date || "Unknown")})</option>`)
        .join("");
}

document.getElementById("negotiationGoalButtons").addEventListener("click", (e) => {
    const btn = e.target.closest(".goal-btn");
    if (!btn) return;
    negotiationGoal = btn.dataset.goal;
    document.querySelectorAll("#negotiationGoalButtons .goal-btn").forEach((b) => {
        const active = b === btn;
        b.classList.toggle("border-primary", active);
        b.classList.toggle("text-primary", active);
        b.classList.toggle("bg-surface-container-highest", active);
        b.classList.toggle("border-outline-variant", !active);
        b.classList.toggle("text-on-surface-variant", !active);
        b.classList.toggle("bg-surface-container-lowest", !active);
    });
});

document.getElementById("generateDraftBtn").addEventListener("click", async () => {
    const select = document.getElementById("negotiationInvoiceSelect");
    const invoiceId = Number(select.value);
    const draftEl = document.getElementById("negotiationDraft");
    const btn = document.getElementById("generateDraftBtn");

    if (!invoiceId) {
        CashPilot.toast("Select an unpaid invoice first.", "error");
        return;
    }

    const invoice = (lastOverview.payment_recommendations || []).find((i) => i.id === invoiceId);
    if (!invoice) return;

    btn.disabled = true;
    draftEl.textContent = "Generating…";

    try {
        const data = await CashPilot.apiJson("/vendor-negotiation", {
            method: "POST",
            body: JSON.stringify({
                vendor: invoice.vendor,
                amount: invoice.amount,
                due_date: invoice.due_date,
                category: invoice.category,
                goal: negotiationGoal,
            }),
        });
        draftEl.textContent = data.message;
    } catch (err) {
        draftEl.textContent = "";
        CashPilot.toast(err.message || "Could not generate a draft right now.", "error");
    } finally {
        btn.disabled = false;
    }
});

document.getElementById("copyDraftBtn").addEventListener("click", async () => {
    const text = document.getElementById("negotiationDraft").textContent;
    if (!text || !text.trim()) return;
    try {
        await navigator.clipboard.writeText(text);
        CashPilot.toast("Copied to clipboard.", "success");
    } catch (err) {
        CashPilot.toast("Could not copy to clipboard.", "error");
    }
});

// ---------------------------------------------------------------------------
// AI CFO Recommendations (Gemini narrative, loaded independently)
// ---------------------------------------------------------------------------

async function loadAiRecommendations() {
    const el = document.getElementById("aiRecsContent");
    el.innerHTML = `
        <div class="flex items-center gap-sm text-on-surface-variant text-sm">
            <span class="material-symbols-outlined animate-spin text-base">progress_activity</span>
            Generating recommendations…
        </div>
    `;

    try {
        const data = await CashPilot.apiJson("/cfo/ai-recommendations");

        const recsHtml = data.recommendations.map((r) => `
            <div class="p-md rounded-xl border border-outline-variant bg-surface-container-low">
                <div class="flex justify-between items-start gap-sm">
                    <p class="font-semibold text-on-surface text-sm">${CashPilot.escapeHtml(r.title)}</p>
                    <span class="px-sm py-xs rounded-lg font-label-md text-xs shrink-0 ${PRIORITY_BADGE[r.priority] || PRIORITY_BADGE.Medium}">${r.priority}</span>
                </div>
                <p class="text-sm text-on-surface-variant mt-1 leading-relaxed">${CashPilot.escapeHtml(r.reason)}</p>
                <p class="text-xs font-semibold text-primary mt-sm">${CashPilot.escapeHtml(r.action)}</p>
            </div>
        `).join("");

        el.innerHTML = `
            <p class="text-sm text-on-surface leading-relaxed">${CashPilot.escapeHtml(data.summary)}</p>
            <div class="space-y-sm">${recsHtml || '<p class="text-sm text-on-surface-variant">No specific recommendations right now.</p>'}</div>
        `;
    } catch (err) {
        el.innerHTML = `
            <div class="flex items-start gap-sm text-on-surface-variant text-sm">
                <span class="material-symbols-outlined text-base">info</span>
                <span>${CashPilot.escapeHtml(err.message || "AI recommendations are unavailable right now.")}</span>
            </div>
            <button id="retryAiRecsBtn" class="mt-sm px-md py-xs rounded-lg border border-outline-variant text-sm font-label-md hover:bg-white/10">Retry</button>
        `;
        const retryBtn = document.getElementById("retryAiRecsBtn");
        if (retryBtn) retryBtn.addEventListener("click", loadAiRecommendations);
    }
}

// ---------------------------------------------------------------------------
// Scenario Simulator
// ---------------------------------------------------------------------------

function populateScenarioInvoiceOptions() {
    updateScenarioFieldVisibility();
}

function currentScenarioInvoiceList() {
    if (!lastOverview) return [];
    const type = document.getElementById("scenarioType").value;
    return type === "accelerate_receivable"
        ? lastOverview.receivable_recommendations
        : lastOverview.payment_recommendations;
}

function updateScenarioFieldVisibility() {
    const type = document.getElementById("scenarioType").value;
    const invoiceField = document.getElementById("scenarioInvoiceField");
    const daysField = document.getElementById("scenarioDaysField");
    const percentField = document.getElementById("scenarioPercentField");

    const needsInvoice = type === "delay_payable" || type === "accelerate_receivable";
    invoiceField.classList.toggle("hidden", !needsInvoice);
    daysField.classList.toggle("hidden", type === "expense_increase");
    percentField.classList.toggle("hidden", type !== "expense_increase");

    if (needsInvoice) {
        const list = currentScenarioInvoiceList();
        const select = document.getElementById("scenarioInvoiceId");
        if (!list.length) {
            select.innerHTML = '<option value="">No eligible invoices</option>';
        } else {
            select.innerHTML = list.map((inv) =>
                `<option value="${inv.id}">${CashPilot.escapeHtml(inv.vendor)} — ${CashPilot.formatCurrency(inv.amount)} (due ${CashPilot.escapeHtml(inv.due_date || "Unknown")})</option>`
            ).join("");
        }
    }
}

document.getElementById("scenarioType").addEventListener("change", updateScenarioFieldVisibility);

document.getElementById("scenarioForm").addEventListener("submit", async (e) => {
    e.preventDefault();

    const type = document.getElementById("scenarioType").value;
    const body = { scenario_type: type };

    if (type === "delay_payable" || type === "accelerate_receivable") {
        const invoiceId = document.getElementById("scenarioInvoiceId").value;
        if (!invoiceId) {
            CashPilot.toast("Select an invoice to simulate this scenario.", "error");
            return;
        }
        body.invoice_id = Number(invoiceId);
        body.days = Number(document.getElementById("scenarioDays").value) || 0;
    } else {
        body.percent = Number(document.getElementById("scenarioPercent").value) || 0;
    }

    const submitBtn = document.getElementById("scenarioSubmitBtn");
    submitBtn.disabled = true;
    submitBtn.textContent = "Running…";

    try {
        const result = await CashPilot.apiJson("/cfo/scenario", {
            method: "POST",
            body: JSON.stringify(body),
        });
        renderScenarioResult(result);
    } catch (err) {
        CashPilot.toast(err.message || "Could not run this scenario.", "error");
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Run Scenario";
    }
});

function renderScenarioResult(result) {
    const { baseline, projected, description } = result;

    const delta = (a, b) => Math.round(b - a);
    const deltaPill = (value, higherIsBetter = true) => {
        if (value === 0) {
            return `<span class="text-[10px] font-semibold text-on-surface-variant bg-surface-container px-1.5 py-0.5 rounded-full">No change</span>`;
        }
        const good = higherIsBetter ? value > 0 : value < 0;
        const arrow = value > 0 ? "▲" : "▼";
        const cls = good ? "text-emerald-700 bg-emerald-50" : "text-red-700 bg-red-50";
        return `<span class="text-[10px] font-semibold ${cls} px-1.5 py-0.5 rounded-full">${arrow} ${Math.abs(value)}</span>`;
    };
    const riskColor = {
        Low: "text-emerald-600",
        Medium: "text-secondary",
        High: "text-orange-600",
        Critical: "text-error",
    };

    const resultEl = document.getElementById("scenarioResult");
    // Swap out of the dashed empty-state look now that there's a real result.
    resultEl.className = "p-lg rounded-xl border border-outline-variant bg-primary-fixed/10";
    resultEl.innerHTML = `
        <div class="flex items-center gap-sm mb-lg pb-md border-b border-outline-variant/60">
            <span class="material-symbols-outlined text-primary">auto_awesome</span>
            <p class="font-semibold text-on-surface text-sm">${CashPilot.escapeHtml(description)}</p>
        </div>
        <div class="grid grid-cols-2 gap-md">
            <div class="p-md rounded-lg bg-surface-container-lowest border border-outline-variant">
                <p class="text-xs text-on-surface-variant mb-xs">Cash Runway</p>
                <p class="text-2xl font-bold text-on-surface">${projected.runway_days}<span class="text-xs font-normal text-on-surface-variant ml-1">days</span></p>
                <div class="mt-xs">${deltaPill(delta(baseline.runway_days, projected.runway_days), true)}</div>
            </div>
            <div class="p-md rounded-lg bg-surface-container-lowest border border-outline-variant">
                <p class="text-xs text-on-surface-variant mb-xs">Health Score</p>
                <p class="text-2xl font-bold text-on-surface">${projected.health_score}<span class="text-xs font-normal text-on-surface-variant ml-1">/100</span></p>
                <div class="mt-xs">${deltaPill(delta(baseline.health_score, projected.health_score), true)}</div>
            </div>
            <div class="p-md rounded-lg bg-surface-container-lowest border border-outline-variant">
                <p class="text-xs text-on-surface-variant mb-xs">Cash Balance</p>
                <p class="text-2xl font-bold text-on-surface">${CashPilot.formatCurrency(projected.balance)}</p>
            </div>
            <div class="p-md rounded-lg bg-surface-container-lowest border border-outline-variant">
                <p class="text-xs text-on-surface-variant mb-xs">Risk Level</p>
                <p class="text-2xl font-bold ${riskColor[projected.risk_level] || ""}">${projected.risk_level}</p>
            </div>
        </div>
    `;
}

// ---------------------------------------------------------------------------
// Small helper shared by the render* functions above.
// ---------------------------------------------------------------------------

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}
