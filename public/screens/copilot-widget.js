// Global AI Financial Copilot — one floating widget mounted on every
// protected page (dashboard, invoices, analytics, ai-cfo, settings).
// Reuses the existing POST /cfo/copilot endpoint exactly as it already works
// on the AI CFO page — this file only relocates that rendering logic so it's
// available everywhere, and adds cross-page chat persistence via
// sessionStorage. The question sent to the backend is never altered; "page
// awareness" is frontend-only framing (greeting, suggestions, placeholder).
(function () {
    if (window.__cashpilotCopilotMounted) return;
    window.__cashpilotCopilotMounted = true;

    const HISTORY_KEY = "cashpilot_copilot_history";
    const MAX_HISTORY = 30;

    const pageInfo = CashPilot.currentPageInfo();

    // --- Mount markup ---------------------------------------------------------

    const root = document.createElement("div");
    root.id = "cashpilot-copilot-root";
    root.innerHTML = `
        <button id="gcpFab" aria-label="Open AI Copilot" class="fixed bottom-6 right-6 z-[9998] w-14 h-14 rounded-full bg-primary text-on-primary shadow-xl flex items-center justify-center hover:scale-105 active:scale-95 transition-transform">
            <span class="material-symbols-outlined text-2xl" style="font-variation-settings:'FILL' 1;">smart_toy</span>
        </button>

        <div id="gcpPanel" class="hidden fixed z-[9999] inset-0 md:inset-auto md:bottom-24 md:right-6 w-full h-full md:w-[380px] md:h-[600px] md:rounded-2xl bg-surface-container-lowest shadow-2xl border border-outline-variant flex flex-col overflow-hidden opacity-0 scale-95 origin-bottom-right transition-all duration-200">
            <div class="bg-primary p-md flex items-center gap-md shrink-0">
                <div class="bg-white/20 p-xs rounded-lg">
                    <span class="material-symbols-outlined text-white" style="font-variation-settings:'FILL' 1;">smart_toy</span>
                </div>
                <div class="flex-1 min-w-0">
                    <h3 class="text-white font-bold leading-none text-base">AI Financial Copilot</h3>
                    <p class="text-white/80 text-xs mt-1 truncate">On ${CashPilot.escapeHtml(pageInfo.label)}</p>
                </div>
                <button id="gcpCloseBtn" aria-label="Close" class="text-white/80 hover:text-white transition-colors">
                    <span class="material-symbols-outlined">close</span>
                </button>
            </div>

            <div id="gcpMessages" class="flex-1 overflow-y-auto p-md space-y-md bg-surface-container-low/30"></div>

            <div id="gcpSuggestions" class="p-sm border-t border-outline-variant bg-white flex flex-wrap gap-xs shrink-0"></div>

            <div class="p-sm border-t border-outline-variant bg-white shrink-0">
                <form id="gcpForm" class="relative">
                    <input id="gcpInput" class="w-full bg-surface-container-low border-none rounded-xl pr-12 text-sm focus:ring-1 focus:ring-primary py-sm px-md" placeholder="Ask your AI Financial Copilot…" type="text" autocomplete="off" />
                    <button type="submit" id="gcpSendBtn" aria-label="Send" class="absolute right-1 top-1/2 -translate-y-1/2 text-primary p-xs hover:scale-105 transition-transform">
                        <span class="material-symbols-outlined text-lg">send</span>
                    </button>
                </form>
            </div>
        </div>
    `;
    document.body.appendChild(root);

    const fab = document.getElementById("gcpFab");
    const panel = document.getElementById("gcpPanel");
    const messagesEl = document.getElementById("gcpMessages");
    const suggestionsEl = document.getElementById("gcpSuggestions");

    // --- Open / close -----------------------------------------------------

    function openPanel() {
        fab.classList.add("hidden");
        panel.classList.remove("hidden");
        requestAnimationFrame(() => panel.classList.remove("opacity-0", "scale-95"));
        document.getElementById("gcpInput").focus();
    }

    function closePanel() {
        panel.classList.add("opacity-0", "scale-95");
        setTimeout(() => {
            panel.classList.add("hidden");
            fab.classList.remove("hidden");
        }, 200);
    }

    fab.addEventListener("click", openPanel);
    document.getElementById("gcpCloseBtn").addEventListener("click", closePanel);
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !panel.classList.contains("hidden")) closePanel();
    });

    // --- Page-aware suggestions ---------------------------------------------

    suggestionsEl.innerHTML = pageInfo.suggestions.map((s) =>
        `<button type="button" class="gcp-suggestion px-sm py-xs rounded-full border border-outline-variant text-xs text-on-surface-variant hover:border-primary hover:text-primary transition-all">${CashPilot.escapeHtml(s)}</button>`
    ).join("");
    suggestionsEl.querySelectorAll(".gcp-suggestion").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.getElementById("gcpInput").value = btn.textContent.trim();
            document.getElementById("gcpForm").requestSubmit();
        });
    });

    // --- History persistence (survives full-page navigation) ----------------

    function loadHistory() {
        try {
            return JSON.parse(sessionStorage.getItem(HISTORY_KEY) || "[]");
        } catch (_) {
            return [];
        }
    }

    function saveHistory(list) {
        sessionStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(-MAX_HISTORY)));
    }

    const history = loadHistory();

    function appendHistory(entry) {
        history.push(entry);
        saveHistory(history);
    }

    // --- Rendering ------------------------------------------------------------

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function renderWelcome() {
        messagesEl.insertAdjacentHTML("beforeend", `
            <div class="flex flex-col items-start max-w-[95%]">
                <div class="bg-white border border-outline-variant p-md rounded-xl rounded-tl-none shadow-xs text-sm text-on-surface leading-relaxed">
                    ${CashPilot.escapeHtml(pageInfo.greeting)}
                </div>
                <span class="text-[10px] text-on-surface-variant mt-xs px-1">Copilot</span>
            </div>
        `);
    }

    function renderUserMessage(text, persist = true) {
        messagesEl.insertAdjacentHTML("beforeend", `
            <div class="flex justify-end">
                <div class="bg-primary text-white px-md py-sm rounded-xl rounded-tr-none max-w-[90%] text-sm">
                    ${CashPilot.escapeHtml(text)}
                </div>
            </div>
        `);
        if (persist) appendHistory({ type: "user", text });
        scrollToBottom();
    }

    function renderBotMessage(innerHtml, persistEntry) {
        messagesEl.insertAdjacentHTML("beforeend", `
            <div class="flex flex-col items-start max-w-[95%]">
                <div class="bg-white border border-outline-variant p-md rounded-xl rounded-tl-none shadow-xs text-sm text-on-surface leading-relaxed space-y-sm">
                    ${innerHtml}
                </div>
                <span class="text-[10px] text-on-surface-variant mt-xs px-1">Copilot</span>
            </div>
        `);
        if (persistEntry) appendHistory(persistEntry);
        scrollToBottom();
        return messagesEl.lastElementChild;
    }

    function renderTyping() {
        messagesEl.insertAdjacentHTML("beforeend", `
            <div class="flex justify-start" data-gcp-typing>
                <div class="bg-white border border-outline-variant px-md py-sm rounded-xl rounded-tl-none text-on-surface-variant text-sm animate-pulse">Thinking…</div>
            </div>
        `);
        scrollToBottom();
        return messagesEl.querySelector("[data-gcp-typing]");
    }

    function invoiceRow(inv) {
        return `<div class="flex justify-between items-center text-xs py-1.5 border-b border-outline-variant last:border-0">
            <span class="text-on-surface">${CashPilot.escapeHtml(inv.vendor)}</span>
            <span class="text-on-surface-variant">${CashPilot.escapeHtml(inv.due_date || "Unknown")}</span>
            <span class="font-mono-data font-semibold">${CashPilot.formatCurrency(inv.amount)}</span>
        </div>`;
    }

    // Renders the `data` payload for intents where showing real rows/numbers
    // is more useful than prose alone — same behavior as the version this
    // was extracted from on the AI CFO page.
    function renderData(intent, data) {
        if (!data) return "";

        if (intent === "overdue_invoices" && data.invoices) {
            if (!data.invoices.length) return "";
            return `<div class="mt-sm">${data.invoices.map(invoiceRow).join("")}</div>`;
        }

        if ((intent === "payment_priority" || intent === "receivable_followup") && data.recommendations) {
            return `<div class="mt-sm">${data.recommendations.slice(0, 5).map(invoiceRow).join("")}</div>`;
        }

        if (intent === "biggest_expense" && data.categories && data.categories.length) {
            return `<div class="mt-sm">${data.categories.slice(0, 5).map((c) => `
                <div class="flex justify-between text-xs py-1.5 border-b border-outline-variant last:border-0">
                    <span class="text-on-surface">${CashPilot.escapeHtml(c.category)}</span>
                    <span class="font-mono-data font-semibold">${CashPilot.formatCurrency(c.amount)}</span>
                </div>
            `).join("")}</div>`;
        }

        if (intent.startsWith("scenario_") && data.matched) {
            const delta = (a, b) => (b - a >= 0 ? "+" : "") + Math.round(b - a);
            return `
                <div class="mt-sm grid grid-cols-2 gap-sm">
                    <div class="p-sm rounded-lg bg-surface-container-low border border-outline-variant">
                        <p class="text-[10px] text-on-surface-variant">Runway</p>
                        <p class="text-sm font-bold">${CashPilot.formatRunwayDays(data.projected.runway_days)}d <span class="text-[10px] font-normal text-on-surface-variant">(${delta(data.baseline.runway_days, data.projected.runway_days)}d)</span></p>
                    </div>
                    <div class="p-sm rounded-lg bg-surface-container-low border border-outline-variant">
                        <p class="text-[10px] text-on-surface-variant">Health Score</p>
                        <p class="text-sm font-bold">${data.projected.health_score} <span class="text-[10px] font-normal text-on-surface-variant">(${delta(data.baseline.health_score, data.projected.health_score)})</span></p>
                    </div>
                </div>
            `;
        }

        return "";
    }

    // Some actions (scroll_to_section, generate_payment_plan) only make
    // sense on the AI CFO page. If their target isn't on the current page,
    // fall back to navigating there instead of silently doing nothing.
    function runAction(action) {
        if (action.type === "scroll_to_section") {
            const el = document.getElementById(action.section);
            if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
            else window.location.href = `/screens/ai-cfo.html#${action.section}`;
        } else if (action.type === "generate_payment_plan") {
            const btn = document.getElementById("generatePaymentPlanBtn");
            if (btn) {
                document.getElementById("financial-overview")?.scrollIntoView({ behavior: "smooth", block: "start" });
                setTimeout(() => btn.click(), 400);
            } else {
                window.location.href = "/screens/ai-cfo.html#generate-payment-plan";
            }
        } else if (action.type === "view_invoice") {
            window.location.href = "/screens/invoices.html";
        }
    }

    function renderActionsHtml(actions) {
        if (!actions || !actions.length) return "";
        const buttons = actions.map((a, i) =>
            `<button type="button" class="gcp-action px-sm py-xs rounded-lg border border-primary text-primary text-xs font-bold hover:bg-primary-fixed/10 transition-all" data-action-index="${i}">${CashPilot.escapeHtml(a.label)}</button>`
        ).join("");
        return `<div class="flex flex-wrap gap-xs pt-sm">${buttons}</div>`;
    }

    function renderResult(result, persist = true) {
        const dataHtml = renderData(result.intent, result.data);
        const actionsHtml = renderActionsHtml(result.actions);

        const msgEl = renderBotMessage(
            `<p>${CashPilot.escapeHtml(result.answer)}</p>${dataHtml}${actionsHtml}`,
            persist ? { type: "bot", result } : null
        );

        if (result.actions && result.actions.length) {
            msgEl.querySelectorAll(".gcp-action").forEach((btn) => {
                btn.addEventListener("click", () => runAction(result.actions[Number(btn.dataset.actionIndex)]));
            });
        }
    }

    // --- Submit -----------------------------------------------------------

    let busy = false;

    document.getElementById("gcpForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        if (busy) return;

        const input = document.getElementById("gcpInput");
        const question = input.value.trim();
        if (!question) return;

        renderUserMessage(question);
        input.value = "";

        busy = true;
        const typingEl = renderTyping();

        try {
            const result = await CashPilot.apiJson("/cfo/copilot", {
                method: "POST",
                body: JSON.stringify({ question }),
            });
            typingEl.remove();
            renderResult(result);
        } catch (err) {
            typingEl.remove();
            const safeMessage = `<p>${CashPilot.escapeHtml(err.message || "I couldn't reach the server. Please try again.")}</p>`;
            renderBotMessage(safeMessage, { type: "bot-simple", html: safeMessage });
        } finally {
            busy = false;
        }
    });

    // --- Restore history on load, or show the page-aware welcome ------------

    if (history.length) {
        history.forEach((entry) => {
            if (entry.type === "user") renderUserMessage(entry.text, false);
            else if (entry.type === "bot") renderResult(entry.result, false);
            else if (entry.type === "bot-simple") renderBotMessage(entry.html, false);
        });
    } else {
        renderWelcome();
    }
})();
