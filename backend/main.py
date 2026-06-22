import os
import fitz
import re
from fastapi.middleware.cors import CORSMiddleware

from fastapi import FastAPI, UploadFile, File

from database import SessionLocal, engine
from models import Base, Invoice,ManualExpenseRequest
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from models import ScenarioRequest,ChatRequest



Base.metadata.create_all(bind=engine)
CURRENT_BALANCE = 75000

app = FastAPI()

def priority_score(invoice):

        try:

            transaction_bonus = 0

            if invoice.transaction_type == "receivable":

                transaction_bonus = 15

            due_date = datetime.strptime(
                invoice.due_date,
                "%d-%m-%Y"
            )

            days_left = (
                due_date -
                datetime.today()
            ).days

            if days_left <= 0:

                due_score = 50

            elif days_left <= 3:

                due_score = 45

            elif days_left <= 7:

                due_score = 35

            elif days_left <= 15:

                due_score = 20

            else:

                due_score = 10

        except:

            due_score = 10

        amount_score = min(
            invoice.amount / 1000,
            30
        )

        category = (
            invoice.category or ""
        ).lower()

        if "rent" in category:

            category_score = 20

        elif "salary" in category:

            category_score = 20

        elif (
            "utility" in category or
            "utilities" in category
        ):

            category_score = 15

        else:

            category_score = 5

        score = (

    (due_score / 50) * 0.50 +

    (amount_score / 30) * 0.30 +

    (category_score / 20) * 0.20

) * 100

        score += transaction_bonus

        return min(
            round(score),
            100
        )

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_FOLDER = "uploads"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def extract_pdf_text(filepath):
    doc = fitz.open(filepath)

    text = ""

    for page in doc:
        text += page.get_text()

    return text


import re

def parse_invoice(text):

    import re

    amount = 0
    amount_inr = 0
    vendor = "Unknown Vendor"
    due_date = "Unknown"
    category = "General"
    currency = "INR"

    # ==========================
    # AMOUNT + CURRENCY
    # ==========================

    amount_match = re.search(
        r"Amount:\s*([$₹€£])?\s*([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE
    )

    if not amount_match:

        amount_match = re.search(
            r"Total\s+Due\s+([$₹€£])?\s*([\d,]+(?:\.\d+)?)",
            text,
            re.IGNORECASE
        )

    if not amount_match:

        amount_match = re.search(
            r"Total\s+([$₹€£])?\s*([\d,]+(?:\.\d+)?)",
            text,
            re.IGNORECASE
        )

    if not amount_match:

        amount_match = re.search(
            r"([$₹€£])\s*([\d,]+(?:\.\d+)?)",
            text
        )

    if amount_match:

        symbol = amount_match.group(1)

        amount = float(
            amount_match.group(2)
            .replace(",", "")
        )

        if symbol == "$":
            currency = "USD"

        elif symbol == "€":
            currency = "EUR"

        elif symbol == "£":
            currency = "GBP"

        else:
            currency = "INR"

    # ==========================
    # CONVERT TO INR
    # ==========================

    exchange_rates = {
        "INR": 1,
        "USD": 86,
        "EUR": 99,
        "GBP": 116
    }

    amount_inr = round(
        amount *
        exchange_rates.get(
            currency,
            1
        ),
        2
    )

    # ==========================
    # VENDOR
    # ==========================

    vendor_match = re.search(
        r"Vendor:\s*(.*)",
        text,
        re.IGNORECASE
    )

    if vendor_match:

        vendor = vendor_match.group(1).strip()

    else:

        from_match = re.search(
            r"From:\s*\n?([^\n]+)",
            text,
            re.IGNORECASE
        )

        if from_match:

            vendor = (
                from_match.group(1)
                .strip()
            )

    # ==========================
    # DUE DATE
    # ==========================

    due_date_match = re.search(
        r"Due Date:\s*(.*)",
        text,
        re.IGNORECASE
    )

    if due_date_match:

        due_date = (
            due_date_match.group(1)
            .strip()
        )

    # ==========================
    # CATEGORY
    # ==========================

    category_match = re.search(
        r"Category:\s*(.*)",
        text,
        re.IGNORECASE
    )

    if category_match:

        category = (
            category_match.group(1)
            .strip()
        )

    else:

        lower_text = text.lower()

        if (
            "aws" in lower_text or
            "amazon web services" in lower_text
        ):

            category = "Cloud Services"

        elif (
            "azure" in lower_text or
            "microsoft azure" in lower_text
        ):

            category = "Cloud Services"

        elif (
            "google workspace" in lower_text
        ):

            category = "Software"

        elif (
            "stripe" in lower_text
        ):

            category = "Payments"

        elif (
            "rent" in lower_text
        ):

            category = "Rent"

        elif (
            "utility" in lower_text or
            "electricity" in lower_text or
            "internet" in lower_text
        ):

            category = "Utilities"

    return {

        "vendor": vendor,

        "amount": amount_inr,

        "currency": currency,

        "due_date": due_date,

        "category": category

    }

@app.get("/")
def home():
    return {"message": "CashPilot Backend Running"}


@app.post("/upload-invoice")
async def upload_invoice(
    file: UploadFile = File(...)
):

    filepath = os.path.join(
        UPLOAD_FOLDER,
        file.filename
    )

    with open(filepath, "wb") as f:
        f.write(await file.read())

    text = extract_pdf_text(filepath)

    data = parse_invoice(text)

    db = SessionLocal()

    invoice = Invoice(
        vendor=data["vendor"],
        amount=data["amount"],
        due_date=data["due_date"],
        category=data["category"]
    )

    db.add(invoice)

    db.commit()

    db.close()

    return data





from datetime import datetime


@app.get("/dashboard")
def dashboard():

    from datetime import datetime, timedelta

    upcoming_bills = 0
    db = SessionLocal()

    invoices = db.query(Invoice).all()

    for invoice in invoices:

        try:

            due = datetime.strptime(
                invoice.due_date,
                "%d-%m-%Y"
            )

            if due <= datetime.today() + timedelta(days=30):

                upcoming_bills += invoice.amount

        except:
            pass

    

    

    global CURRENT_BALANCE

    current_balance = CURRENT_BALANCE

    total_payables = sum(
    invoice.amount
    for invoice in invoices
    if invoice.transaction_type == "payable"
)

    total_receivables = sum(
        invoice.amount
        for invoice in invoices
        if invoice.transaction_type == "receivable"
    )

    monthly_burn = total_payables

    if monthly_burn > 0:

        runway_days = round(
            (current_balance / monthly_burn) * 30
        )

    else:

        runway_days = 365

    db.close()

    return {
        "current_balance": current_balance,
        "total_payables": total_payables,
        "upcoming_bills":upcoming_bills,
        "total_receivables": total_receivables,
        "cash_runway": runway_days,
        "invoice_count": len(invoices),

 }

from datetime import datetime

def calculate_ai_score(invoice):

    score = 0

    try:

        due_date = datetime.strptime(
            invoice.due_date,
            "%d-%m-%Y"
        )

        days_left = (
            due_date -
            datetime.today()
        ).days

        if days_left < 0:

            score += 60

        elif days_left <= 3:

            score += 50

        elif days_left <= 7:

            score += 35

        elif days_left <= 15:

            score += 20

    except:

        pass

    score += min(
        invoice.amount / 1000,
        40
    )

    category = (
        invoice.category or ""
    ).lower()

    if (
        "rent" in category or
        "salary" in category or
        "utility" in category
    ):
        score += 35

    return min(
    round(score),
    100
)




@app.get("/invoices")
def get_invoices():

    db = SessionLocal()

    invoices = db.query(
        Invoice
    ).all()

    result = []

    for invoice in invoices:

        score = priority_score(
            invoice
        )

        if score >= 80:

            risk_level = "Critical"

        elif score >= 60:

            risk_level = "High"

        elif score >= 40:

            risk_level = "Medium"

        else:

            risk_level = "Low"

        result.append({

            "id":
                invoice.id,

            "vendor":
                invoice.vendor,

            "amount":
                invoice.amount,

            "due_date":
                invoice.due_date,

            "category":
                invoice.category,

            "transaction_type":
                invoice.transaction_type,

            "ai_score":
                score,

            "risk_level":
                risk_level

        })

    result.sort(
        key=lambda x: x["ai_score"],
        reverse=True
    )

    db.close()

    return result

@app.get("/analytics")
def analytics():

    db = SessionLocal()

    invoices = db.query(Invoice).all()

    categories = {}

    for invoice in invoices:

        category = invoice.category

        if category not in categories:
            categories[category] = 0

        categories[category] += invoice.amount

    db.close()

    return {
        "categories": categories
    }

@app.delete("/invoice/{invoice_id}")
def delete_invoice(invoice_id: int):

    db = SessionLocal()

    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id)
        .first()
    )

    if not invoice:
        db.close()
        return {"error": "Invoice not found"}

    db.delete(invoice)

    db.commit()

    db.close()

    return {
        "message": "Invoice deleted"
    }
class ScenarioSimulationRequest(BaseModel):
    amount: float


@app.post("/simulate-scenario")
def simulate_scenario(data: ScenarioSimulationRequest):

    db = SessionLocal()

    invoices = db.query(Invoice).all()

    total_payables = sum(
        invoice.amount
        for invoice in invoices
    )

    current_balance = 75000

    new_balance = (
        current_balance -
        data.amount
    )

    runway = (
        new_balance /
        (total_payables / 30)
        if total_payables > 0
        else 0
    )

    db.close()

    return {
        "new_balance": new_balance,
        "new_runway": round(runway, 1)
    }

@app.get("/payment-priority")
def payment_priority():

    db = SessionLocal()

    invoices = db.query(
        Invoice
    ).filter(
        Invoice.transaction_type == "payable"
    ).all()

    from datetime import datetime

    results = []

    for invoice in invoices:

        # =====================
        # DUE DATE SCORE
        # MAX = 50
        # =====================

        try:

            due_date = datetime.strptime(
                invoice.due_date,
                "%d-%m-%Y"
            )

            days_left = (
                due_date -
                datetime.today()
            ).days

            if days_left <= 0:

                due_score = 50

            elif days_left <= 3:

                due_score = 45

            elif days_left <= 7:

                due_score = 35

            elif days_left <= 15:

                due_score = 20

            else:

                due_score = 10

        except:

            due_score = 10

        # =====================
        # AMOUNT SCORE
        # MAX = 30
        # =====================

        amount_score = min(
            invoice.amount / 1000,
            30
        )

        # =====================
        # CATEGORY SCORE
        # MAX = 20
        # =====================

        category = (
            invoice.category or ""
        ).lower()

        if "rent" in category:

            category_score = 20

        elif "salary" in category:

            category_score = 20

        elif (
            "utility" in category or
            "utilities" in category
        ):

            category_score = 15

        elif (
            "cloud" in category or
            "software" in category
        ):

            category_score = 10

        else:

            category_score = 5

        # =====================
# NORMALIZED WEIGHTED SCORE
# Due Date = 50%
# Amount = 30%
# Category = 20%
# =====================

        score = round(

            (

                (due_score / 50) * 0.50 +

                (amount_score / 30) * 0.30 +

                (category_score / 20) * 0.20

            ) * 100

        )

        # =====================
        # PRIORITY LEVEL
        # =====================

        if score >= 80:

            action = "Critical"

        elif score >= 60:

            action = "High"

        elif score >= 40:

            action = "Medium"

        else:

            action = "Low"

        # =====================
        # REASON
        # =====================

        reason = (
    "Weighted score based on "
    "50% due-date urgency, "
    "30% invoice value, "
    "and 20% business-critical category."
)
        results.append({

            "vendor":
                invoice.vendor,

            "amount":
                invoice.amount,

            "due_date":
                invoice.due_date,

            "score":
                score,

            "action":
                action,

            "reason":
                reason

        })

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    db.close()

    return results


@app.get("/analytics-summary")
def analytics_summary():

    db = SessionLocal()

    invoices = db.query(Invoice).all()

    total_spend = sum(
        i.amount
        for i in invoices
    )

    largest_invoice = max(
        [i.amount for i in invoices],
        default=0
    )

    categories = {}

    for invoice in invoices:

        category = invoice.category

        categories[category] = (
            categories.get(category, 0)
            + invoice.amount
        )

    db.close()

    return {
        "total_spend": total_spend,
        "largest_invoice": largest_invoice,
        "invoice_count": len(invoices),
        "categories": categories
    }


from pydantic import BaseModel

class BalanceRequest(BaseModel):
    balance: float


@app.post("/update-balance")
def update_balance(data: BalanceRequest):

    global CURRENT_BALANCE

    CURRENT_BALANCE = data.balance

    return {
        "success": True,
        "balance": CURRENT_BALANCE
    }


@app.get("/debug")
def debug():

    db = SessionLocal()

    invoices = db.query(Invoice).all()

    return [
        {
            "vendor": i.vendor,
            "due_date": i.due_date,
            "amount": i.amount
        }
        for i in invoices
    ]



@app.post("/manual-expense")
def add_manual_expense(
    data: ManualExpenseRequest
):

    db = SessionLocal()

    invoice = Invoice(

    vendor=data.vendor,

    amount=data.amount,

    category=data.category,

    due_date=data.due_date,

    transaction_type=
        data.transaction_type

)

    db.add(invoice)

    db.commit()

    db.close()

    return {
        "success": True
    }




@app.get("/payment-plan")
def payment_plan(
    scenario_amount: float = 0
):

    db = SessionLocal()

    invoices = db.query(
        Invoice
    ).filter(
        Invoice.transaction_type == "payable"
    ).all()

    from datetime import datetime

    

    invoices.sort(
        key=priority_score,
        reverse=True
    )

    remaining_balance = (
        CURRENT_BALANCE -
        scenario_amount
    )

    pay_now = []
    delay = []

    SAFETY_THRESHOLD = 25000

    for invoice in invoices:

        if (
            remaining_balance -
            invoice.amount
        ) >= SAFETY_THRESHOLD:

            pay_now.append({

                "vendor":
                    invoice.vendor,

                "amount":
                    invoice.amount,

                "score":
                    priority_score(invoice)

            })

            remaining_balance -= (
                invoice.amount
            )

        else:

            delay.append({

                "vendor":
                    invoice.vendor,

                "amount":
                    invoice.amount,

                "score":
                    priority_score(invoice)

            })

    db.close()

    return {

        "pay_now":
            pay_now,

        "delay":
            delay,

        "remaining_balance":
            remaining_balance,

        "scenario_amount":
            scenario_amount

    }



@app.post("/ai-recommendation")
def ai_recommendation(
    data: ScenarioRequest
):

    prompt = f"""
You are an expert CFO.

Analyze the following scenario:

Current Balance: ₹{data.current_balance}
Scenario Cost: ₹{data.scenario_cost}
Projected Balance: ₹{data.projected_balance}
Projected Runway: {data.projected_runway} days
Total Payables: ₹{data.total_payables}

Return ONLY HTML.

Structure:

<h3>AI CFO Recommendation</h3>

<h4>Risk Level</h4>
<p><strong>[LOW / MEDIUM / HIGH / CRITICAL]</strong></p>

<h4>Recommendation</h4>
<p>...</p>

<h4>Key Concern</h4>
<p>...</p>

<h4>Suggested Action</h4>
<ul>
<li>...</li>
<li>...</li>
<li>...</li>
</ul>

Keep the response concise and professional.
Do not use markdown.
Do not use code blocks.
Return only HTML.
"""

    response = llm.invoke(
            prompt
        )

    return {
            "recommendation":
                response.content
        }


@app.post("/cfo-chat")
def cfo_chat(data: ChatRequest):

    from datetime import datetime, timedelta

    db = SessionLocal()

    invoices = db.query(
        Invoice
    ).all()

    upcoming_bills = 0

    for invoice in invoices:

        try:

            due = datetime.strptime(
                invoice.due_date,
                "%d-%m-%Y"
            )

            if (
                due <=
                datetime.today()
                + timedelta(days=30)
            ):

                upcoming_bills += (
                    invoice.amount
                )

        except:

            pass

    global CURRENT_BALANCE

    current_balance = (
        CURRENT_BALANCE
    )

    total_payables = sum(

        invoice.amount

        for invoice in invoices

        if invoice.transaction_type
        == "payable"

    )

    total_receivables = sum(

        invoice.amount

        for invoice in invoices

        if invoice.transaction_type
        == "receivable"

    )

    monthly_burn = (
        total_payables
    )

    if monthly_burn > 0:

        runway_days = round(

            (
                current_balance
                /
                monthly_burn
            )
            * 30

        )

    else:

        runway_days = 365

    prompt = f"""
You are CashPilot AI.

You are an AI CFO assistant.

You ONLY answer questions about:

- Cash flow
- Runway
- Payables
- Receivables
- Vendor payments
- Expenses
- Business finance

If the user asks anything outside business finance, reply exactly:

I can only answer questions about your business finances.

Business Data:

Current Balance: ₹{current_balance}

Cash Runway: {runway_days} days

Total Payables: ₹{total_payables}

Total Receivables: ₹{total_receivables}

Upcoming Bills (30 Days): ₹{upcoming_bills}

Invoice Count: {len(invoices)}

User Question:

{data.question}

Rules:

1. Use the business data above.
2. Mention actual numbers.
3. Give practical CFO recommendations.
4. Be concise.
5. Keep answer under 120 words.
"""

    response = llm.invoke(
        prompt
    )

    db.close()

    return {

        "answer":
            response.content

    }