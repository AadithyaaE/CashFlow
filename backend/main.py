import os
import re
from fastapi.middleware.cors import CORSMiddleware

from fastapi import FastAPI, UploadFile, File

from database import SessionLocal, engine
from models import (
    Base,
    Invoice,
    ManualExpenseRequest,
    InvoiceUpdateRequest,
    VendorNegotiationRequest,
)
from pydantic import BaseModel, field_validator
from langchain_google_genai import ChatGoogleGenerativeAI
from models import ScenarioRequest, ChatRequest, UpdateBalanceRequest
from extraction import get_document_text, extract_invoice_fields, ExtractionError
import bcrypt
from jose import jwt, JWTError
from models import User
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    company_name: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v):
        if not v or not v.strip():
            raise ValueError("Name is required")
        return v.strip()

    @field_validator("email")
    @classmethod
    def email_is_valid(cls, v):
        v = (v or "").strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("password")
    @classmethod
    def password_is_strong(cls, v):
        if not v or len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v):
        # Must mirror RegisterRequest's normalization, or a user who signed
        # up as "Foo@Bar.com" (stored lowercased) can't log back in with the
        # same casing they registered with.
        return (v or "").strip().lower()


class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v):
        return (v or "").strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_is_strong(cls, v):
        if not v or len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    import secrets as _secrets
    SECRET_KEY = _secrets.token_hex(32)
    print(
        "WARNING: JWT_SECRET_KEY not set in environment. Using a random "
        "key generated for this process only — all sessions will be "
        "invalidated on restart. Set JWT_SECRET_KEY in backend/.env."
    )

ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="login"
)


ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
PASSWORD_RESET_EXPIRE_MINUTES = 30

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")


def create_access_token(data: dict):

    to_encode = data.copy()

    expire = datetime.utcnow() + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    to_encode.update(
        {
            "exp": expire
        }
    )

    encoded_jwt = jwt.encode(
        to_encode,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    return encoded_jwt


def create_password_reset_token(email: str) -> str:

    # Carries a "purpose" claim so this can never be accepted by
    # get_current_user as a regular session token, and expires much sooner
    # than a normal login session.
    expire = datetime.utcnow() + timedelta(
        minutes=PASSWORD_RESET_EXPIRE_MINUTES
    )

    return jwt.encode(
        {"email": email, "purpose": "password_reset", "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes of input; truncate explicitly so
    # long passwords fail closed instead of raising inside the library.
    pw_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, hashed: str) -> bool:
    pw_bytes = password.encode("utf-8")[:72]
    try:
        return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))
    except ValueError:
        return False


def get_current_user(
    token: str = Depends(oauth2_scheme)
):

    credentials_exception = HTTPException(
        status_code=401,
        detail="Invalid authentication",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:

        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        email = payload.get("email")

        # Password-reset tokens are single-purpose and must never be usable
        # as a session token, even though they're signed with the same key.
        if email is None or payload.get("purpose") is not None:
            raise credentials_exception

    except JWTError:

        raise credentials_exception

    db = SessionLocal()

    user = db.query(User).filter(
        User.email == email
    ).first()

    db.close()

    if user is None:
        raise credentials_exception

    return user


Base.metadata.create_all(bind=engine)

# Lightweight migration: add columns introduced after the table was first
# created, since create_all() only creates missing tables, not columns.
with engine.connect() as _conn:
    from sqlalchemy import text as _text

    _existing_cols = {
        row[1] for row in _conn.execute(_text("PRAGMA table_info(users)"))
    }
    if "company_name" not in _existing_cols:
        _conn.execute(_text("ALTER TABLE users ADD COLUMN company_name VARCHAR"))
        _conn.commit()

    _existing_invoice_cols = {
        row[1] for row in _conn.execute(_text("PRAGMA table_info(invoices)"))
    }
    if "is_paid" not in _existing_invoice_cols:
        _conn.execute(_text("ALTER TABLE invoices ADD COLUMN is_paid BOOLEAN DEFAULT 0"))
        _conn.commit()

    for _col in ("invoice_number", "invoice_date", "gst", "payment_terms", "description"):
        if _col not in _existing_invoice_cols:
            _conn.execute(_text(f"ALTER TABLE invoices ADD COLUMN {_col} VARCHAR"))
            _conn.commit()

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


def is_valid_due_date(value):
    # Mirrors the "%d-%m-%Y" format every other part of this file expects
    # (priority_score, /dashboard, etc.) so invoices created here don't
    # silently fail to score/sort/alert correctly later.
    try:
        datetime.strptime(value, "%d-%m-%Y")
        return True
    except (TypeError, ValueError):
        return False


GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

llm = None

if GOOGLE_API_KEY:

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=GOOGLE_API_KEY
    )

else:

    print("WARNING: Gemini API key not found. AI features disabled.")

_cors_origins_env = os.getenv("CORS_ORIGINS", "")
CORS_ORIGINS = [o.strip() for o in _cors_origins_env.split(",") if o.strip()] or [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_FOLDER = "uploads"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.get("/")
def home():
    return {"message": "CashPilot Backend Running"}


MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
SUPPORTED_UPLOAD_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}


@app.post("/upload-invoice")
async def upload_invoice(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """Extracts structured fields from an uploaded invoice (PDF, scanned PDF,
    or JPG/PNG image) and returns them for the user to review and edit.

    This does NOT create an Invoice record — the frontend shows the
    extracted fields in a preview and only persists them once the user
    confirms, via the existing POST /manual-expense endpoint.
    """

    original_name = os.path.basename(file.filename or "")
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""

    if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Only PDF, JPG, JPEG, or PNG files are supported",
        )

    contents = await file.read()

    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds the 10 MB upload limit")

    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    import uuid

    safe_name = f"{current_user.id}_{uuid.uuid4().hex}_{re.sub(r'[^A-Za-z0-9._-]', '_', original_name)}"

    filepath = os.path.join(
        UPLOAD_FOLDER,
        safe_name
    )

    with open(filepath, "wb") as f:
        f.write(contents)

    try:
        text = get_document_text(llm, filepath, extension)
        fields = extract_invoice_fields(llm, text)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Extraction failed unexpectedly. Please try again or enter the invoice manually.",
        )

    return {
        "message": "Invoice extracted successfully",
        "needs_review": fields["needs_review"],
        "extracted": fields,
    }





from datetime import datetime


@app.get("/dashboard")
def dashboard(
    current_user: User = Depends(get_current_user)
):

    from datetime import datetime, timedelta

    upcoming_bills = 0
    db = SessionLocal()

    invoices = db.query(Invoice).filter(
    Invoice.user_id == current_user.id
).all()
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





    current_balance = current_user.current_balance

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


@app.post("/update-balance")
def update_balance(
    data: UpdateBalanceRequest,
    current_user: User = Depends(get_current_user)
):

    db = SessionLocal()

    user = db.query(User).filter(
        User.id == current_user.id
    ).first()

    user.current_balance = data.balance

    db.commit()
    db.refresh(user)

    db.close()

    return {
        "current_balance": user.current_balance
    }

@app.get("/invoices")
def get_invoices(
    current_user: User = Depends(get_current_user)
):
    db = SessionLocal()

    invoices = db.query(
        Invoice
    ).filter(
        Invoice.user_id == current_user.id
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

            "id": invoice.id,

            "vendor": invoice.vendor,

            "amount": invoice.amount,

            "due_date": invoice.due_date,

            "category": invoice.category,

            "transaction_type": invoice.transaction_type,

            "ai_score": score,

            "risk_level": risk_level,

            "is_paid": bool(invoice.is_paid),

            "invoice_number": invoice.invoice_number,

            "invoice_date": invoice.invoice_date,

            "gst": invoice.gst,

            "payment_terms": invoice.payment_terms,

            "description": invoice.description

        })

    result.sort(
        key=lambda x: x["ai_score"],
        reverse=True
    )

    db.close()

    return result

@app.get("/analytics")
def analytics(
    current_user: User = Depends(get_current_user)
):

    db = SessionLocal()

    invoices = db.query(
        Invoice
    ).filter(
        Invoice.user_id == current_user.id
    ).all()

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
def delete_invoice(
    invoice_id: int,
    current_user: User = Depends(get_current_user)
):

    db = SessionLocal()

    invoice = (
        db.query(Invoice)
        .filter(
            Invoice.id == invoice_id,
            Invoice.user_id == current_user.id
        )
        .first()
    )

    if not invoice:
        db.close()
        raise HTTPException(status_code=404, detail="Invoice not found")

    db.delete(invoice)

    db.commit()

    db.close()

    return {
        "message": "Invoice deleted"
    }


@app.put("/invoice/{invoice_id}")
def update_invoice(
    invoice_id: int,
    data: InvoiceUpdateRequest,
    current_user: User = Depends(get_current_user)
):

    db = SessionLocal()

    invoice = (
        db.query(Invoice)
        .filter(
            Invoice.id == invoice_id,
            Invoice.user_id == current_user.id
        )
        .first()
    )

    if not invoice:
        db.close()
        raise HTTPException(status_code=404, detail="Invoice not found")

    update_data = data.model_dump(exclude_unset=True)

    if "transaction_type" in update_data and update_data["transaction_type"] not in (
        "payable",
        "receivable",
    ):
        db.close()
        raise HTTPException(
            status_code=400,
            detail="transaction_type must be 'payable' or 'receivable'",
        )

    if "amount" in update_data and update_data["amount"] is not None and update_data["amount"] <= 0:
        db.close()
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    if "vendor" in update_data and not (update_data["vendor"] or "").strip():
        db.close()
        raise HTTPException(status_code=400, detail="Vendor is required")

    if "category" in update_data and not (update_data["category"] or "").strip():
        db.close()
        raise HTTPException(status_code=400, detail="Category is required")

    if "due_date" in update_data and not is_valid_due_date(update_data["due_date"]):
        db.close()
        raise HTTPException(status_code=400, detail="Due date must be in DD-MM-YYYY format")

    if "vendor" in update_data and update_data["vendor"] is not None:
        update_data["vendor"] = update_data["vendor"].strip()

    if "category" in update_data and update_data["category"] is not None:
        update_data["category"] = update_data["category"].strip()

    for field, value in update_data.items():
        if value is not None:
            setattr(invoice, field, value)

    db.commit()
    db.refresh(invoice)

    result = {
        "id": invoice.id,
        "vendor": invoice.vendor,
        "amount": invoice.amount,
        "due_date": invoice.due_date,
        "category": invoice.category,
        "transaction_type": invoice.transaction_type,
        "is_paid": bool(invoice.is_paid),
    }

    db.close()

    return result


class ScenarioSimulationRequest(BaseModel):
    amount: float


@app.post("/simulate-scenario")
def simulate_scenario(
    data: ScenarioSimulationRequest,
    current_user: User = Depends(get_current_user)
):

    db = SessionLocal()

    invoices = db.query(Invoice).filter(
        Invoice.user_id == current_user.id
    ).all()

    total_payables = sum(
        invoice.amount
        for invoice in invoices
        if invoice.transaction_type == "payable"
    )

    current_balance = current_user.current_balance

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
def payment_priority(
    current_user: User = Depends(get_current_user)
):

    db = SessionLocal()

    invoices = db.query(
        Invoice
    ).filter(
        Invoice.transaction_type == "payable",
        Invoice.user_id == current_user.id
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
        # FINAL SCORE
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

        reason = (
            "Weighted score based on "
            "50% due-date urgency, "
            "30% invoice value, "
            "and 20% business-critical category."
        )

        results.append({

            "vendor": invoice.vendor,

            "amount": invoice.amount,

            "due_date": invoice.due_date,

            "score": score,

            "action": action,

            "reason": reason

        })

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    db.close()

    return results


@app.get("/analytics-summary")
def analytics_summary(
    current_user: User = Depends(get_current_user)
):

    db = SessionLocal()

    invoices = db.query(Invoice).filter(
        Invoice.user_id == current_user.id
    ).all()

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

@app.post("/manual-expense")
def add_manual_expense(
    data: ManualExpenseRequest,
    current_user: User = Depends(get_current_user)
):

    if data.transaction_type not in ("payable", "receivable"):
        raise HTTPException(
            status_code=400,
            detail="transaction_type must be 'payable' or 'receivable'",
        )

    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    if not data.vendor or not data.vendor.strip():
        raise HTTPException(status_code=400, detail="Vendor is required")

    if not data.category or not data.category.strip():
        raise HTTPException(status_code=400, detail="Category is required")

    if not is_valid_due_date(data.due_date):
        raise HTTPException(status_code=400, detail="Due date must be in DD-MM-YYYY format")

    db = SessionLocal()

    invoice = Invoice(

    vendor=data.vendor.strip(),

    amount=data.amount,

    category=data.category.strip(),

    due_date=data.due_date,

    transaction_type=
        data.transaction_type,

    user_id=current_user.id,

    invoice_number=(data.invoice_number or "").strip() or None,

    invoice_date=(data.invoice_date or "").strip() or None,

    gst=(data.gst or "").strip() or None,

    payment_terms=(data.payment_terms or "").strip() or None,

    description=(data.description or "").strip() or None,

)

    db.add(invoice)

    db.commit()
    db.refresh(invoice)

    result = {
        "id": invoice.id,
        "vendor": invoice.vendor,
        "amount": invoice.amount,
        "due_date": invoice.due_date,
        "category": invoice.category,
        "transaction_type": invoice.transaction_type,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "gst": invoice.gst,
        "payment_terms": invoice.payment_terms,
        "description": invoice.description,
    }

    db.close()

    return result


@app.get("/payment-plan")
def payment_plan(
    scenario_amount: float = 0,
    current_user: User = Depends(get_current_user)
):

    db = SessionLocal()

    invoices = db.query(
        Invoice
    ).filter(
        Invoice.transaction_type == "payable",
        Invoice.user_id == current_user.id
    ).all()

    invoices.sort(
        key=priority_score,
        reverse=True
    )

    remaining_balance = (
        current_user.current_balance -
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
    data: ScenarioRequest,
    current_user: User = Depends(get_current_user)
):

    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="AI features are not configured. Set GOOGLE_API_KEY on the server.",
        )

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
def cfo_chat(
    data: ChatRequest,
    current_user: User = Depends(get_current_user)
):

    if llm is None:

        return {
            "error": "Gemini API key not configured."
        }

    if not data.question or not data.question.strip():
        raise HTTPException(status_code=400, detail="Question is required")

    from datetime import datetime, timedelta

    db = SessionLocal()

    invoices = db.query(
        Invoice
    ).filter(
        Invoice.user_id == current_user.id
    ).all()

    upcoming_bills = 0

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

    current_balance = current_user.current_balance

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

    if total_payables > 0:

        runway_days = round(
            (current_balance / total_payables) * 30
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
4. Keep the answer under 120 words.
"""

    response = llm.invoke(prompt)

    db.close()

    return {
        "answer": response.content
    }

@app.post("/register")
def register(data: RegisterRequest):

    db = SessionLocal()

    existing = db.query(User).filter(
        User.email == data.email
    ).first()

    if existing:

        db.close()

        raise HTTPException(
            status_code=400,
            detail="An account with this email already exists",
        )

    user = User(
        name=data.name,
        email=data.email,
        password=hash_password(data.password),
        company_name=data.company_name,
    )

    db.add(user)

    db.commit()
    db.refresh(user)

    token = create_access_token(
        {"email": user.email}
    )

    db.close()

    return {
        "message": "Registration successful",
        "access_token": token,
        "token_type": "bearer",
        "name": user.name,
    }

@app.post("/login")
def login(data: LoginRequest):

    db = SessionLocal()

    user = db.query(User).filter(
        User.email == data.email
    ).first()

    if not user or not verify_password(data.password, user.password):

        db.close()

        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    token = create_access_token(
        {"email": user.email}
    )

    db.close()

    return {

        "access_token": token,

        "token_type": "bearer",

        "name": user.name

    }
@app.get("/me")
def me(

    current_user: User = Depends(get_current_user)

):

    return {

        "id": current_user.id,

        "name": current_user.name,

        "email": current_user.email,

        "company_name": current_user.company_name,

        "current_balance": current_user.current_balance,

    }


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    company_name: str | None = None


@app.put("/me")
def update_me(
    data: UpdateProfileRequest,
    current_user: User = Depends(get_current_user)
):

    db = SessionLocal()

    user = db.query(User).filter(User.id == current_user.id).first()

    if data.name is not None:
        if not data.name.strip():
            db.close()
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        user.name = data.name.strip()

    if data.company_name is not None:
        user.company_name = data.company_name.strip() or None

    db.commit()
    db.refresh(user)

    result = {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "company_name": user.company_name,
        "current_balance": user.current_balance,
    }

    db.close()

    return result


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_is_strong(cls, v):
        if not v or len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


@app.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user)
):

    db = SessionLocal()

    user = db.query(User).filter(User.id == current_user.id).first()

    if not verify_password(data.current_password, user.password):
        db.close()
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    user.password = hash_password(data.new_password)

    db.commit()

    db.close()

    return {"message": "Password updated successfully"}


@app.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest):

    db = SessionLocal()

    user = db.query(User).filter(User.email == data.email).first()

    db.close()

    # Always return the same generic response whether or not the email is
    # registered, so this endpoint can't be used to enumerate accounts.
    generic_response = {
        "message": "If an account exists for that email, a password reset link has been sent."
    }

    if user is None:
        return generic_response

    reset_token = create_password_reset_token(user.email)
    reset_link = f"{FRONTEND_URL}/screens/reset-password.html?token={reset_token}"

    # No transactional email provider is configured for this project, so the
    # reset link is logged server-side for local/dev use. Wire up a real
    # email provider (SendGrid, SES, etc.) here before shipping to
    # production — never return the token itself to the client.
    print(f"[password reset] {user.email} -> {reset_link}")

    return generic_response


@app.post("/reset-password")
def reset_password(data: ResetPasswordRequest):

    credentials_exception = HTTPException(
        status_code=400,
        detail="This reset link is invalid or has expired. Please request a new one.",
    )

    try:
        payload = jwt.decode(data.token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise credentials_exception

    if payload.get("purpose") != "password_reset":
        raise credentials_exception

    email = payload.get("email")

    if not email:
        raise credentials_exception

    db = SessionLocal()

    user = db.query(User).filter(User.email == email).first()

    if user is None:
        db.close()
        raise credentials_exception

    user.password = hash_password(data.new_password)

    db.commit()
    db.close()

    return {"message": "Password reset successfully. You can now log in with your new password."}


@app.post("/vendor-negotiation")
def vendor_negotiation(
    data: VendorNegotiationRequest,
    current_user: User = Depends(get_current_user)
):

    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="AI features are not configured. Set GOOGLE_API_KEY on the server.",
        )

    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    goal_text = {
        "extension": "requesting a payment extension",
        "discount": "requesting an early-payment discount",
        "installments": "requesting to split the payment into installments",
    }.get(data.goal, "requesting a payment extension")

    prompt = f"""
You are CashPilot AI, an expert CFO assistant helping a business negotiate with a vendor.

Vendor: {data.vendor}
Amount Due: ₹{data.amount}
Due Date: {data.due_date}
Category: {data.category or "General"}
Negotiation Goal: {goal_text}

Write a short, professional email to this vendor {goal_text}, preserving the
business relationship while protecting the company's liquidity. Be specific
and courteous. Do not invent numbers beyond what's provided.

Return ONLY the email body as plain text. No subject line, no markdown, no
code blocks, no HTML tags.
"""

    response = llm.invoke(prompt)

    return {
        "message": response.content
    }