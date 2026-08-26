"""AI CFO calculation engine.

Every number the /cfo/* routes return is computed here, deterministically,
from real Invoice/User data. Gemini (called only from main.py's
/cfo/ai-recommendations route) is handed the output of these functions as
plain text and asked to narrate it — it never computes a financial figure
itself.

All functions operate on a plain SimpleInvoice list rather than live
SQLAlchemy rows, so the exact same functions can be re-run against a
hypothetically-mutated copy of that list for the scenario simulator (see
apply_scenario) without a second, drifting implementation.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from scoring import priority_score
from categories import normalize_category

DATE_FMT = "%d-%m-%Y"

SAFETY_THRESHOLD = 25000  # same reference safety buffer used elsewhere in the app


@dataclass
class SimpleInvoice:
    id: int
    vendor: str
    amount: float
    due_date: str | None
    category: str | None
    transaction_type: str
    is_paid: bool
    invoice_date: str | None = None


def to_simple(invoice) -> SimpleInvoice:
    """Snapshot an ORM Invoice row into a plain object, safe to use after the
    DB session that loaded it has closed."""
    return SimpleInvoice(
        id=invoice.id,
        vendor=invoice.vendor,
        amount=invoice.amount,
        due_date=invoice.due_date,
        category=invoice.category,
        transaction_type=invoice.transaction_type,
        is_paid=bool(invoice.is_paid),
        invoice_date=invoice.invoice_date,
    )


def parse_due_date(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, DATE_FMT).date()
    except ValueError:
        return None


def fmt_currency(amount) -> str:
    return f"₹{amount:,.0f}"


def _outstanding(invoices, transaction_type):
    return [
        i for i in invoices
        if i.transaction_type == transaction_type and not i.is_paid
    ]


HISTORY_MONTHS = 3  # how many complete calendar months back to look for a burn average


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + delta
    return total // 12, total % 12 + 1


def compute_monthly_burn(invoices, today=None) -> dict:
    """Best available signal for "typical monthly payable burn".

    Primary: average payable spend per calendar month, over the last
    HISTORY_MONTHS *complete* months (the current, still-in-progress month
    is excluded so a partial month never skews the average). Grouped by
    invoice_date — the date the expense was actually issued/incurred — not
    due_date, which only says when it's scheduled to be *paid* and can put a
    months-old expense in a future bucket (or vice versa). Both paid and
    unpaid payables count, as long as their invoice_date falls in the
    window; invoices with no invoice_date at all (common for manually-added
    expenses — only the OCR upload/review flow captures this field) simply
    can't be placed on the timeline and are excluded, not guessed at.
    Averages only over the months that actually have data, so 1 or 2
    populated months still produce a real average instead of forcing a full
    3-month requirement.

    Fallback: if none of the last HISTORY_MONTHS months have any dated
    payable history, the current outstanding (unpaid) payables total is
    used instead — the same figure this calculation used before.

    Returns {"monthly_burn": float, "method": "historical_average" | "current_payables_fallback"}.
    """
    today = today or datetime.today().date()

    window_keys = set()
    key = (today.year, today.month)
    for _ in range(HISTORY_MONTHS):
        key = _add_months(key[0], key[1], -1)
        window_keys.add(key)

    monthly_totals: dict[tuple[int, int], float] = {}
    for inv in invoices:
        if inv.transaction_type != "payable":
            continue
        due = parse_due_date(inv.invoice_date)  # same DD-MM-YYYY parser, applied to invoice_date
        if due is None:
            continue
        month_key = (due.year, due.month)
        if month_key not in window_keys:
            continue
        monthly_totals[month_key] = monthly_totals.get(month_key, 0) + inv.amount

    if monthly_totals:
        monthly_burn = sum(monthly_totals.values()) / len(monthly_totals)
        return {"monthly_burn": round(monthly_burn, 2), "method": "historical_average"}

    current_payables = sum(i.amount for i in _outstanding(invoices, "payable"))
    return {"monthly_burn": round(current_payables, 2), "method": "current_payables_fallback"}


def compute_runway(invoices, balance, today=None) -> dict:
    """Single source of truth for cash runway — used by /dashboard, the AI
    CFO health score (and everything derived from it), and the scenario
    simulator, so the figure can't drift between screens again.

    (balance / monthly_burn) * 30 is unchanged; only how monthly_burn itself
    is determined has improved — see compute_monthly_burn. Returns 365 (the
    existing display-layer "365+" cap) whenever there's no burn signal at
    all, exactly as before.
    """
    burn = compute_monthly_burn(invoices, today=today)
    monthly_burn = burn["monthly_burn"]

    if monthly_burn > 0:
        runway_days = round((balance / monthly_burn) * 30)
    else:
        runway_days = 365

    return {
        "runway_days": runway_days,
        "monthly_burn": monthly_burn,
        "runway_method": burn["method"] if monthly_burn > 0 else "no_burn_cap",
    }


def category_breakdown(invoices) -> list[dict]:
    """Total spend per category, largest first. Used by the AI Copilot to
    answer "what's my biggest expense" from real totals, not a guess."""
    totals: dict[str, float] = {}
    for i in invoices:
        category = normalize_category(i.category) if i.category else "Uncategorized"
        totals[category] = totals.get(category, 0) + i.amount
    return [
        {"category": category, "amount": round(amount, 2)}
        for category, amount in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    ]


def find_invoice_by_vendor(invoices, vendor_name, transaction_type=None):
    """Resolves a free-text vendor name (as extracted by Gemini from a
    question) to a real invoice. Gemini can name a vendor but never knows a
    real invoice ID, so this is the deterministic bridge between "the user
    said 'Vendor ABC'" and an actual SimpleInvoice the scenario simulator or
    negotiation flow can act on. Prefers unpaid invoices and exact-name
    matches over partial ones; case-insensitive throughout.
    """
    if not vendor_name:
        return None

    candidates = [
        i for i in invoices
        if not i.is_paid and (transaction_type is None or i.transaction_type == transaction_type)
    ]

    needle = vendor_name.strip().lower()

    exact = [i for i in candidates if i.vendor.strip().lower() == needle]
    if exact:
        return exact[0]

    partial = [i for i in candidates if needle in i.vendor.strip().lower() or i.vendor.strip().lower() in needle]
    if partial:
        return partial[0]

    return None


# ---------------------------------------------------------------------------
# 1. Cash Flow Forecast — pure arithmetic, no AI involved.
# ---------------------------------------------------------------------------

FORECAST_HORIZONS = [
    ("Today", 0),
    ("7 Days", 7),
    ("30 Days", 30),
    ("60 Days", 60),
    ("90 Days", 90),
]


def compute_cash_flow_forecast(invoices, balance, today=None) -> list[dict]:
    today = today or datetime.today().date()

    dated = []
    for inv in invoices:
        if inv.is_paid:
            continue
        due = parse_due_date(inv.due_date)
        if due is None:
            continue
        dated.append((inv, due))

    buckets = []
    opening = balance
    prev_days = None

    for label, days in FORECAST_HORIZONS:
        window_end = today + timedelta(days=days)

        incoming = 0.0
        outgoing = 0.0

        for inv, due in dated:
            if prev_days is None:
                in_window = due <= window_end
            else:
                window_start_exclusive = today + timedelta(days=prev_days)
                in_window = window_start_exclusive < due <= window_end

            if not in_window:
                continue

            if inv.transaction_type == "receivable":
                incoming += inv.amount
            else:
                outgoing += inv.amount

        closing = opening + incoming - outgoing

        buckets.append({
            "label": label,
            "days": days,
            "opening_balance": round(opening, 2),
            "incoming": round(incoming, 2),
            "outgoing": round(outgoing, 2),
            "closing_balance": round(closing, 2),
        })

        opening = closing
        prev_days = days

    return buckets


# ---------------------------------------------------------------------------
# 2. Financial Health Score (0-100)
# ---------------------------------------------------------------------------

def _band_score(value, bands):
    """bands: list of (threshold, score) sorted descending by threshold;
    returns the score for the first threshold value meets/exceeds."""
    for threshold, score in bands:
        if value >= threshold:
            return score
    return bands[-1][1]


def compute_financial_health(invoices, balance, forecast=None) -> dict:
    forecast = forecast if forecast is not None else compute_cash_flow_forecast(invoices, balance)

    payables = _outstanding(invoices, "payable")
    receivables = _outstanding(invoices, "receivable")

    total_payables = sum(i.amount for i in payables)
    total_receivables = sum(i.amount for i in receivables)

    today = datetime.today().date()
    overdue = [i for i in payables if (parse_due_date(i.due_date) or today) < today]
    overdue_amount = sum(i.amount for i in overdue)

    # Sum of the Today + 7 Days + 30 Days buckets' outgoing = obligations due
    # in the next 30 days, reusing the forecast instead of re-scanning.
    upcoming_30d = sum(b["outgoing"] for b in forecast if b["days"] <= 30)

    runway = compute_runway(invoices, balance)
    runway_days = runway["runway_days"]

    vendor_totals: dict[str, float] = {}
    for i in payables:
        vendor_totals[i.vendor] = vendor_totals.get(i.vendor, 0) + i.amount
    top_vendor, top_vendor_amount = max(vendor_totals.items(), key=lambda kv: kv[1], default=(None, 0))
    vendor_share = (top_vendor_amount / total_payables) if total_payables > 0 else 0

    # --- component scores (each 0-100) -----------------------------------

    runway_score = _band_score(runway_days, [
        (90, 100), (60, 85), (30, 65), (14, 40), (7, 20), (0, 5),
    ])

    if upcoming_30d > 0:
        liquidity_ratio = balance / upcoming_30d
        liquidity_score = max(0, min(liquidity_ratio / 2.0, 1.0)) * 100
    else:
        liquidity_score = 100 if balance > 0 else 50

    overdue_score = 100 if total_payables <= 0 else max(0, 100 - (overdue_amount / total_payables) * 100)

    if total_payables > 0:
        receivables_score = max(0, min((total_receivables / total_payables), 1.0)) * 100
    else:
        receivables_score = 100

    if total_payables <= 0 or vendor_share <= 0.3:
        concentration_score = 100
    elif vendor_share >= 0.8:
        concentration_score = 0
    else:
        concentration_score = 100 * (0.8 - vendor_share) / 0.5

    weights = {
        "runway": 0.35,
        "liquidity": 0.25,
        "overdue": 0.20,
        "receivables": 0.10,
        "concentration": 0.10,
    }

    raw_score = (
        runway_score * weights["runway"]
        + liquidity_score * weights["liquidity"]
        + overdue_score * weights["overdue"]
        + receivables_score * weights["receivables"]
        + concentration_score * weights["concentration"]
    )
    score = max(0, min(round(raw_score), 100))

    if score >= 80:
        rating = "Excellent"
    elif score >= 60:
        rating = "Good"
    elif score >= 40:
        rating = "Average"
    else:
        rating = "Poor"

    breakdown = [
        {"factor": "Cash Runway", "weight": weights["runway"], "score": round(runway_score),
         "detail": f"{runway_days} days of runway at current outstanding payables."},
        {"factor": "Liquidity Coverage", "weight": weights["liquidity"], "score": round(liquidity_score),
         "detail": f"{fmt_currency(balance)} on hand vs. {fmt_currency(upcoming_30d)} due in the next 30 days."},
        {"factor": "Overdue Payables", "weight": weights["overdue"], "score": round(overdue_score),
         "detail": f"{fmt_currency(overdue_amount)} overdue out of {fmt_currency(total_payables)} outstanding."},
        {"factor": "Receivables Coverage", "weight": weights["receivables"], "score": round(receivables_score),
         "detail": f"{fmt_currency(total_receivables)} outstanding receivables vs. {fmt_currency(total_payables)} outstanding payables."},
        {"factor": "Vendor Concentration", "weight": weights["concentration"], "score": round(concentration_score),
         "detail": (f"{top_vendor} accounts for {vendor_share * 100:.0f}% of outstanding payables."
                    if top_vendor else "No outstanding payables.")},
    ]

    explanation = (
        f"Your Financial Health Score is {score}/100 ({rating}). "
        f"It's calculated from five weighted factors: cash runway (35%), liquidity coverage against the "
        f"next 30 days of obligations (25%), overdue payables (20%), receivables coverage of what you owe (10%), "
        f"and vendor concentration risk (10%). "
        f"You have {runway_days} days of runway, {fmt_currency(overdue_amount)} overdue out of "
        f"{fmt_currency(total_payables)} in outstanding payables, and {fmt_currency(total_receivables)} in "
        f"outstanding receivables."
    )

    return {
        "score": score,
        "rating": rating,
        "breakdown": breakdown,
        "explanation": explanation,
        "metrics": {
            "runway_days": runway_days,
            "monthly_burn": runway["monthly_burn"],
            "runway_method": runway["runway_method"],
            "total_outstanding_payables": round(total_payables, 2),
            "total_outstanding_receivables": round(total_receivables, 2),
            "overdue_payables_count": len(overdue),
            "overdue_payables_amount": round(overdue_amount, 2),
            "upcoming_30d_obligations": round(upcoming_30d, 2),
            "top_vendor": top_vendor,
            "top_vendor_share": round(vendor_share, 4),
        },
    }


def risk_level_from_score(score: int) -> str:
    """Maps a 0-100 health score to the app's existing Critical/High/Medium/Low
    vocabulary (inverted: a high health score is Low risk)."""
    if score >= 80:
        return "Low"
    if score >= 60:
        return "Medium"
    if score >= 40:
        return "High"
    return "Critical"


# ---------------------------------------------------------------------------
# 3 & 4. Smart Payment / Receivable Recommendations
# ---------------------------------------------------------------------------

def _risk_band(score: int) -> str:
    if score >= 80:
        return "Critical"
    if score >= 60:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def rank_payment_recommendations(invoices, balance, today=None) -> list[dict]:
    today = today or datetime.today().date()
    payables = _outstanding(invoices, "payable")
    if not payables:
        return []

    largest_amount = max(i.amount for i in payables)
    results = []

    for inv in payables:
        score = priority_score(inv)
        band = _risk_band(score)
        due = parse_due_date(inv.due_date)
        days_left = (due - today).days if due else None
        is_largest = inv.amount == largest_amount
        category_lower = (inv.category or "").lower()
        is_business_critical = "rent" in category_lower or "salary" in category_lower

        # Tied to `band` (not just days_left) so this text can never say
        # "safe to delay" while suggested_action says "Pay Now" — a large
        # rent/salary payable can be Critical/High priority even far out.
        if days_left is None:
            why = "Due date could not be determined — confirm it to prioritize this correctly."
        elif days_left < 0:
            why = f"Overdue by {abs(days_left)} day(s)"
            why += ", and it's your largest outstanding payable" if is_largest else ""
            why += " — pay this first to limit further risk."
        elif band == "Critical":
            why = f"Due in {days_left} day(s) with a critical priority score — pay this now."
        elif band == "High":
            why = f"Due in {days_left} day(s) with a high priority score — pay soon to stay ahead of it."
        elif band == "Medium":
            why = f"Due in {days_left} days with a medium priority score — plan the payment, no immediate rush."
        else:
            why = f"Due in {days_left} days with ample buffer — safe to delay if cash is tight elsewhere."

        if is_business_critical:
            why += " This is a business-critical category (rent/salary)."

        results.append({
            "id": inv.id,
            "vendor": inv.vendor,
            "amount": inv.amount,
            "due_date": inv.due_date,
            "category": inv.category,
            "score": score,
            "priority": band,
            "suggested_action": "Pay Now" if band in ("Critical", "High") else "Can Delay",
            "why": why,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def rank_receivable_recommendations(invoices, today=None) -> list[dict]:
    today = today or datetime.today().date()
    receivables = _outstanding(invoices, "receivable")
    if not receivables:
        return []

    results = []
    for inv in receivables:
        score = priority_score(inv)
        band = _risk_band(score)
        due = parse_due_date(inv.due_date)
        days_left = (due - today).days if due else None

        # Tied to `band` for the same reason as rank_payment_recommendations —
        # keeps this text consistent with suggested_action in every case.
        if days_left is None:
            why = "Due date could not be determined — confirm it to plan follow-up."
        elif days_left < 0:
            why = f"Overdue by {abs(days_left)} day(s) — follow up immediately to protect cash flow."
        elif band == "Critical":
            why = f"Due in {days_left} day(s) with a critical priority score — follow up now."
        elif band == "High":
            why = f"Due in {days_left} day(s) with a high priority score — send a reminder now so payment arrives on time."
        elif band == "Medium":
            why = f"Due in {days_left} days — a check-in reminder is worthwhile."
        else:
            why = f"Due in {days_left} days — low urgency, monitor for now."

        results.append({
            "id": inv.id,
            "vendor": inv.vendor,
            "amount": inv.amount,
            "due_date": inv.due_date,
            "category": inv.category,
            "score": score,
            "priority": band,
            "suggested_action": "Follow Up Now" if band in ("Critical", "High") else "Monitor",
            "why": why,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# 5. Business Risk Analysis
# ---------------------------------------------------------------------------

def compute_business_risks(invoices, balance, health: dict, forecast: list[dict]) -> list[dict]:
    risks = []
    metrics = health["metrics"]

    if metrics["runway_days"] < 30:
        risks.append({
            "type": "low_runway",
            "severity": "critical" if metrics["runway_days"] < 14 else "high",
            "title": "Low Cash Runway",
            "message": f"Only {metrics['runway_days']} days of runway remain at the current outstanding payables burn.",
        })

    if metrics["overdue_payables_count"] > 0:
        share = (
            metrics["overdue_payables_amount"] / metrics["total_outstanding_payables"]
            if metrics["total_outstanding_payables"] > 0 else 0
        )
        risks.append({
            "type": "overdue_invoices",
            "severity": "critical" if share >= 0.5 else ("high" if metrics["overdue_payables_count"] >= 3 else "medium"),
            "title": "Overdue Invoices",
            "message": (
                f"{metrics['overdue_payables_count']} payable(s) totaling {fmt_currency(metrics['overdue_payables_amount'])} "
                f"are overdue ({share * 100:.0f}% of outstanding payables)."
            ),
        })

    if metrics["top_vendor"] and metrics["top_vendor_share"] >= 0.4:
        risks.append({
            "type": "vendor_concentration",
            "severity": "high" if metrics["top_vendor_share"] >= 0.6 else "medium",
            "title": "Heavy Vendor Dependence",
            "message": f"{metrics['top_vendor']} accounts for {metrics['top_vendor_share'] * 100:.0f}% of your outstanding payables.",
        })

    deficit_bucket = next((b for b in forecast if b["closing_balance"] < 0), None)
    if deficit_bucket:
        risks.append({
            "type": "cash_deficit",
            "severity": "critical",
            "title": "Projected Cash Deficit",
            "message": f"Projected balance goes negative by the {deficit_bucket['label']} mark ({fmt_currency(deficit_bucket['closing_balance'])}).",
        })

    outgoings = [b["outgoing"] for b in forecast if b["outgoing"] > 0]
    if len(outgoings) >= 2:
        avg_outgoing = sum(outgoings) / len(outgoings)
        spike_bucket = next((b for b in forecast if avg_outgoing > 0 and b["outgoing"] >= avg_outgoing * 2), None)
        if spike_bucket:
            risks.append({
                "type": "payment_spike",
                "severity": "medium",
                "title": "Upcoming Payment Spike",
                "message": f"Outgoing payments in the {spike_bucket['label']} window ({fmt_currency(spike_bucket['outgoing'])}) are well above your average.",
            })

    if balance < SAFETY_THRESHOLD:
        risks.append({
            "type": "cash_deficit",
            "severity": "medium",
            "title": "Below Safety Threshold",
            "message": f"Current balance {fmt_currency(balance)} is below the {fmt_currency(SAFETY_THRESHOLD)} safety threshold.",
        })

    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    risks.sort(key=lambda r: severity_rank.get(r["severity"], 9))
    return risks


# ---------------------------------------------------------------------------
# 6. Scenario Simulator
# ---------------------------------------------------------------------------

class ScenarioError(Exception):
    pass


def _shift_due_date(due_date: str | None, delta_days: int) -> str | None:
    parsed = parse_due_date(due_date)
    if parsed is None:
        return due_date
    return (parsed + timedelta(days=delta_days)).strftime(DATE_FMT)


def apply_scenario(invoices: list[SimpleInvoice], scenario: dict) -> list[SimpleInvoice]:
    """Returns a new list with one hypothetical mutation applied. Never
    mutates the input list — the caller re-runs the same deterministic
    functions against this copy to get the "projected" side of a comparison."""

    scenario_type = scenario.get("scenario_type")
    result = list(invoices)

    if scenario_type == "delay_payable":
        invoice_id = scenario.get("invoice_id")
        days = scenario.get("days") or 0
        found = False
        for idx, inv in enumerate(result):
            if inv.id == invoice_id and inv.transaction_type == "payable":
                result[idx] = replace(inv, due_date=_shift_due_date(inv.due_date, days))
                found = True
                break
        if not found:
            raise ScenarioError("Payable invoice not found")

    elif scenario_type == "accelerate_receivable":
        invoice_id = scenario.get("invoice_id")
        days = scenario.get("days") or 0
        found = False
        for idx, inv in enumerate(result):
            if inv.id == invoice_id and inv.transaction_type == "receivable":
                result[idx] = replace(inv, due_date=_shift_due_date(inv.due_date, -days))
                found = True
                break
        if not found:
            raise ScenarioError("Receivable invoice not found")

    elif scenario_type == "expense_increase":
        percent = scenario.get("percent") or 0
        factor = 1 + (percent / 100)
        result = [
            replace(inv, amount=round(inv.amount * factor, 2)) if inv.transaction_type == "payable" and not inv.is_paid
            else inv
            for inv in result
        ]

    else:
        raise ScenarioError(f"Unknown scenario_type: {scenario_type}")

    return result


def describe_scenario(scenario: dict, invoices: list[SimpleInvoice]) -> str:
    scenario_type = scenario.get("scenario_type")
    if scenario_type == "delay_payable":
        inv = next((i for i in invoices if i.id == scenario.get("invoice_id")), None)
        name = inv.vendor if inv else "the selected vendor"
        return f"Delay payment to {name} by {scenario.get('days') or 0} day(s)"
    if scenario_type == "accelerate_receivable":
        inv = next((i for i in invoices if i.id == scenario.get("invoice_id")), None)
        name = inv.vendor if inv else "the selected customer"
        return f"{name} pays {scenario.get('days') or 0} day(s) early"
    if scenario_type == "expense_increase":
        return f"Expenses increase by {scenario.get('percent') or 0}%"
    return "Scenario"
