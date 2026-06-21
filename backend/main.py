import os
import fitz
import re
from fastapi.middleware.cors import CORSMiddleware

from fastapi import FastAPI, UploadFile, File

from database import SessionLocal, engine
from models import Base, Invoice
from pydantic import BaseModel

Base.metadata.create_all(bind=engine)

app = FastAPI()

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

    db = SessionLocal()

    invoices = db.query(Invoice).all()

    global CURRENT_BALANCE

    current_balance = CURRENT_BALANCE

    total_payables = sum(
        invoice.amount
        for invoice in invoices
    )

    today = datetime.today().date()

    future_invoices = []

    for invoice in invoices:

        due_date = None

        try:

            due_date = datetime.strptime(
                invoice.due_date,
                "%d-%m-%Y"
            )

        except:

            try:

                due_date = datetime.strptime(
                    invoice.due_date,
                    "%B %d, %Y"
                )

            except:

                continue

        if due_date.date() >= today:

            future_invoices.append(
                (
                    due_date,
                    invoice.amount
                )
            )

    future_invoices.sort(
        key=lambda x: x[0]
    )

    remaining_balance = current_balance

    runway_days = 365

    for due_date, amount in future_invoices:

        remaining_balance -= amount

        if remaining_balance <= 0:

            runway_days = max(
                (
                    due_date.date() - today
                ).days,
                0
            )

            break

    print("TODAY:", today)
    print("FUTURE INVOICES:", future_invoices)
    print("RUNWAY DAYS:", runway_days)

    db.close()

    return {
        "current_balance": current_balance,
        "total_payables": total_payables,
        "cash_runway": runway_days,
        "invoice_count": len(invoices)
    }
@app.get("/invoices")
def get_invoices():

    db = SessionLocal()

    invoices = db.query(Invoice).all()

    result = []

    for invoice in invoices:
        result.append({
            "id": invoice.id,
            "vendor": invoice.vendor,
            "amount": invoice.amount,
            "due_date": invoice.due_date,
            "category": invoice.category
        })

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
class ScenarioRequest(BaseModel):
    amount: float


@app.post("/simulate-scenario")
def simulate_scenario(data: ScenarioRequest):

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

    invoices = db.query(Invoice).all()

    results = []

    for invoice in invoices:

        score = 50

        if invoice.amount > 10000:
            score += 30

        elif invoice.amount > 5000:
            score += 15

        category = (
            invoice.category or ""
        ).lower()

        if (
            "utility" in category or
            "salary" in category or
            "rent" in category
        ):
            score += 20

        action = (
            "Pay Immediately"
            if score >= 70
            else "Delay Priority"
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
                f"Priority score {score} based on invoice value and category."
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
