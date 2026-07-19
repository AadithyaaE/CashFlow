// Shared API client + session/UI helpers used by every screen in public/screens/*.html.
// Loaded via <script src="api.js"></script> before each page's own inline script.

    const API_URL = window.__CASHPILOT_API_URL__ || "http://127.0.0.1:8000";

// Session token lives in localStorage when "Remember me" was checked
// (persists across browser restarts) or sessionStorage otherwise (cleared
// when the tab/browser closes). Both are checked on read so either mode
// works transparently everywhere else in the app.
function getToken() {
    return localStorage.getItem("token") || sessionStorage.getItem("token");
}

function setToken(token, remember) {
    if (remember) {
        localStorage.setItem("token", token);
        sessionStorage.removeItem("token");
    } else {
        sessionStorage.setItem("token", token);
        localStorage.removeItem("token");
    }
}

function clearToken() {
    localStorage.removeItem("token");
    sessionStorage.removeItem("token");
}

async function api(endpoint, options = {}) {

    const token = getToken();

    const headers = {

        ...(options.headers || {}),

        Authorization: token
            ? `Bearer ${token}`
            : ""

    };

    // Only set JSON content type if we're NOT uploading files
    if (!(options.body instanceof FormData)) {

        headers["Content-Type"] = "application/json";

    }

    let response;

    try {

        response = await fetch(
            API_URL + endpoint,
            {

                ...options,

                headers

            }
        );

    } catch (networkError) {

        throw new Error("Could not reach the server. Check your connection and try again.");

    }

    if (response.status === 401) {

        clearToken();
        localStorage.removeItem("user");
        sessionStorage.removeItem("user");

        if (!location.pathname.endsWith("index.html") && location.pathname !== "/") {

            CashPilot.toast("Session expired. Please sign in again.", "error");

            setTimeout(() => {
                window.location.href = "/screens/index.html";
            }, 900);

        }

        return response;

    }

    return response;

}

// Parses a JSON API response, throwing a readable Error on failure so callers
// can rely on try/catch instead of re-checking response.ok everywhere.
async function apiJson(endpoint, options = {}) {

    const response = await api(endpoint, options);

    if (!response) {
        throw new Error("Not authenticated");
    }

    let data = null;

    try {
        data = await response.json();
    } catch (_) {
        data = null;
    }

    if (!response.ok) {

        const detail = data && (data.detail || data.message);

        const message = Array.isArray(detail)
            ? detail.map((d) => d.msg || JSON.stringify(d)).join(", ")
            : (detail || `Request failed (${response.status})`);

        throw new Error(message);

    }

    return data;

}

const CashPilot = {

    API_URL,

    apiJson,

    // --- Session token (see getToken/setToken/clearToken above) -----------

    getToken,
    setToken,
    clearToken,

    // --- Auth guard ---------------------------------------------------

    isLoggedIn() {
        return Boolean(getToken());
    },

    requireAuth() {
        if (!this.isLoggedIn()) {
            window.location.href = "/screens/index.html";
        }
    },

    redirectIfLoggedIn(destination = "/screens/dashboard.html") {
        if (this.isLoggedIn()) {
            window.location.href = destination;
        }
    },

    logout() {
        clearToken();
        localStorage.removeItem("user");
        sessionStorage.removeItem("user");
        window.location.href = "/screens/index.html";
    },

    // --- Current user ----------------------------------------------------

    _meCache: null,

    async getCurrentUser({ force = false } = {}) {

        if (this._meCache && !force) return this._meCache;

        const me = await apiJson("/me");

        this._meCache = me;

        localStorage.setItem("user", me.name || "");

        return me;

    },

    initials(name) {

        if (!name) return "?";

        return name
            .trim()
            .split(/\s+/)
            .slice(0, 2)
            .map((p) => p[0].toUpperCase())
            .join("");

    },

    // Populates any element carrying these data-hooks with the logged-in
    // user's identity, and wires every [data-action="logout"] element.
    async hydrateUserChrome() {

        document.querySelectorAll('[data-action="logout"]').forEach((el) => {
            el.addEventListener("click", (e) => {
                e.preventDefault();
                this.logout();
            });
        });

        try {

            const me = await this.getCurrentUser();

            document.querySelectorAll("[data-user-name]").forEach((el) => {
                el.textContent = me.name || "Account";
            });

            document.querySelectorAll("[data-user-email]").forEach((el) => {
                el.textContent = me.email || "";
            });

            document.querySelectorAll("[data-user-company]").forEach((el) => {
                el.textContent = me.company_name || "";
            });

            document.querySelectorAll("[data-user-initials]").forEach((el) => {
                el.textContent = this.initials(me.name);
            });

            return me;

        } catch (err) {

            // api() already redirects to login on 401; anything else, fail quiet.
            return null;

        }

    },

    // Call once per protected page: enforces auth + hydrates nav chrome.
    async initPage() {
        this.requireAuth();
        this.stripDevWidget();
        return this.hydrateUserChrome();
    },

    stripDevWidget() {
        document.querySelectorAll("[data-page-switcher]").forEach((el) => el.remove());
    },

    // --- Formatting -------------------------------------------------------

    escapeHtml(value) {

        const div = document.createElement("div");
        div.textContent = value === null || value === undefined ? "" : String(value);
        return div.innerHTML;

    },

    formatCurrency(amount) {

        const n = Number(amount) || 0;

        return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });

    },

    // Backend dates come back as "DD-MM-YYYY" strings that the native Date
    // constructor cannot parse reliably. Returns a Date or null.
    parseBackendDate(value) {

        if (!value) return null;

        const match = /^(\d{1,2})-(\d{1,2})-(\d{4})$/.exec(value.trim());

        if (!match) return null;

        const [, day, month, year] = match;

        const date = new Date(Number(year), Number(month) - 1, Number(day));

        return isNaN(date.getTime()) ? null : date;

    },

    // --- Toast notifications (replaces alert()) ---------------------------

    _ensureToastHost() {

        let host = document.getElementById("cp-toast-host");

        if (!host) {

            host = document.createElement("div");
            host.id = "cp-toast-host";
            host.style.cssText =
                "position:fixed;bottom:20px;right:20px;z-index:99999;display:flex;flex-direction:column;gap:8px;max-width:360px;";
            document.body.appendChild(host);

        }

        return host;

    },

    toast(message, type = "success", duration = 4000) {

        const host = this._ensureToastHost();

        const colors = {
            success: "#16a34a",
            error: "#dc2626",
            info: "#4648d4",
            warning: "#d97706",
        };

        const el = document.createElement("div");

        el.style.cssText = `
            background:#fff;
            border-left:4px solid ${colors[type] || colors.info};
            box-shadow:0 8px 24px rgba(0,0,0,0.12);
            border-radius:10px;
            padding:12px 16px;
            font-family:Inter,sans-serif;
            font-size:14px;
            color:#191c1e;
            opacity:0;
            transform:translateY(8px);
            transition:opacity 0.2s ease, transform 0.2s ease;
        `;

        el.textContent = message;

        host.appendChild(el);

        requestAnimationFrame(() => {
            el.style.opacity = "1";
            el.style.transform = "translateY(0)";
        });

        setTimeout(() => {

            el.style.opacity = "0";
            el.style.transform = "translateY(8px)";

            setTimeout(() => el.remove(), 200);

        }, duration);

    },

    // --- Confirm dialog (replaces confirm()) -------------------------------

    confirm({ title = "Are you sure?", message = "", confirmLabel = "Confirm", danger = true } = {}) {

        return new Promise((resolve) => {

            const overlay = document.createElement("div");

            overlay.style.cssText =
                "position:fixed;inset:0;background:rgba(15,17,20,0.45);z-index:100000;display:flex;align-items:center;justify-content:center;padding:16px;font-family:Inter,sans-serif;";

            const confirmColor = danger ? "#dc2626" : "#4648d4";

            overlay.innerHTML = `
                <div style="background:#fff;border-radius:16px;max-width:360px;width:100%;padding:24px;box-shadow:0 20px 40px rgba(0,0,0,0.2);">
                    <h3 style="font-size:17px;font-weight:700;margin:0 0 8px;color:#191c1e;">${this.escapeHtml(title)}</h3>
                    <p style="font-size:14px;color:#565e74;margin:0 0 20px;line-height:1.5;">${this.escapeHtml(message)}</p>
                    <div style="display:flex;gap:10px;justify-content:flex-end;">
                        <button data-cp-cancel style="padding:9px 16px;border-radius:10px;border:1px solid #c7c4d7;background:#fff;font-size:14px;font-weight:600;cursor:pointer;">Cancel</button>
                        <button data-cp-confirm style="padding:9px 16px;border-radius:10px;border:none;background:${confirmColor};color:#fff;font-size:14px;font-weight:600;cursor:pointer;">${this.escapeHtml(confirmLabel)}</button>
                    </div>
                </div>
            `;

            document.body.appendChild(overlay);

            const cleanup = (result) => {
                overlay.remove();
                resolve(result);
            };

            overlay.querySelector("[data-cp-cancel]").addEventListener("click", () => cleanup(false));
            overlay.querySelector("[data-cp-confirm]").addEventListener("click", () => cleanup(true));
            overlay.addEventListener("click", (e) => {
                if (e.target === overlay) cleanup(false);
            });

        });

    },

};

window.CashPilot = CashPilot;
