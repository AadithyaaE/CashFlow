// AI CFO page — orchestrates /cfo/overview, /cfo/ai-recommendations, and
// /cfo/scenario. Every number rendered here comes straight from the backend;
// this file only formats and displays it (and, for the scenario form,
// collects the user's hypothetical input before sending it to the server).

CashPilot.initPage();

let lastOverview = null;
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
        setText("sidebarBalance", CashPilot.formatCurrency(data.current_balance));
        setText("sidebarRunway", `${Math.ceil(data.cash_runway)} days runway`);
    } catch (_) {
        // Non-critical widget — the rest of the page still works without it.
    }
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
                <p class="font-semibold text-on-surface text-sm">${CashPilot.escapeHtml(r.title)}</p>
                <p class="text-sm text-on-surface-variant mt-1 leading-relaxed">${CashPilot.escapeHtml(r.detail)}</p>
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

    const delta = (a, b) => (b - a >= 0 ? "+" : "") + Math.round(b - a);
    const riskColor = {
        Low: "text-emerald-600",
        Medium: "text-secondary",
        High: "text-orange-600",
        Critical: "text-error",
    };

    document.getElementById("scenarioResult").innerHTML = `
        <p class="font-semibold text-on-surface mb-md">${CashPilot.escapeHtml(description)}</p>
        <div class="grid grid-cols-2 gap-md">
            <div class="p-sm rounded-lg bg-surface-container-lowest border border-outline-variant">
                <p class="text-xs text-on-surface-variant">Cash Runway</p>
                <p class="font-bold text-on-surface">${projected.runway_days} days <span class="text-xs font-normal text-on-surface-variant">(${delta(baseline.runway_days, projected.runway_days)}d)</span></p>
            </div>
            <div class="p-sm rounded-lg bg-surface-container-lowest border border-outline-variant">
                <p class="text-xs text-on-surface-variant">Health Score</p>
                <p class="font-bold text-on-surface">${projected.health_score}/100 <span class="text-xs font-normal text-on-surface-variant">(${delta(baseline.health_score, projected.health_score)})</span></p>
            </div>
            <div class="p-sm rounded-lg bg-surface-container-lowest border border-outline-variant">
                <p class="text-xs text-on-surface-variant">Cash Balance</p>
                <p class="font-bold text-on-surface">${CashPilot.formatCurrency(projected.balance)}</p>
            </div>
            <div class="p-sm rounded-lg bg-surface-container-lowest border border-outline-variant">
                <p class="text-xs text-on-surface-variant">Risk Level</p>
                <p class="font-bold ${riskColor[projected.risk_level] || ""}">${projected.risk_level}</p>
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
