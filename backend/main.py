import os
import re
import json
import tempfile
from fastapi.middleware.cors import CORSMiddleware

from fastapi import FastAPI, UploadFile, File

from database import SessionLocal
from models import (
    Invoice,
    ManualExpenseRequest,
    InvoiceUpdateRequest,
    VendorNegotiationRequest,
)
from pydantic import BaseModel, field_validator
from langchain_google_genai import ChatGoogleGenerativeAI
from models import UpdateBalanceRequest
from extraction import get_document_text, extract_invoice_fields, ExtractionError
from scoring import priority_score, is_valid_due_date
from categories import normalize_category
import cfo
import ai_errors
import storage.s3_service as s3_service
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


# Schema is owned entirely by Alembic now (see backend/alembic/) — run
# `alembic upgrade head` before starting the app. No create-on-import here.

app = FastAPI()

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
_env_origins = [origin.strip() for origin in _cors_origins_env.split(",") if origin.strip()]

_default_dev_origins = [
    "http://localhost:8080",
    "http://localhost:8081",
    "http://localhost:8082",
    "http://localhost:8083",
    "http://localhost:8084",
    "http://localhost:8085",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8081",
    "http://127.0.0.1:8082",
    "http://127.0.0.1:8083",
    "http://127.0.0.1:8084",
    "http://127.0.0.1:8085",
]

# Always-allowed production frontend(s), independent of whatever CORS_ORIGINS
# happens to be set to on the server. render.yaml's own CORS_ORIGINS value
# can drift out of sync with the real Vercel deployment URL (exactly what
# broke signup/register in production); listing the known-current frontend
# here means a code deploy alone fixes it, without depending on someone also
# updating the Render dashboard's environment variables.
_default_prod_origins = [
    "https://cash-flow-frd2.vercel.app",
]

# CORS_ORIGINS (comma-separated) drives which origins may call this API.
# Previously this env var was parsed but never actually used, so every
# deployment silently fell back to the localhost dev list — the browser
# would block every request from a real frontend domain. Set CORS_ORIGINS
# in production (e.g. to the Vercel deployment URL); the localhost entries
# stay allowed too so local frontend dev keeps working against a deployed API.
CORS_ORIGINS = (
    _env_origins + _default_dev_origins + _default_prod_origins
    if _env_origins
    else _default_dev_origins + _default_prod_origins
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"message": "CashPilot Backend Running"}


MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
SUPPORTED_UPLOAD_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}


def _cleanup_orphaned_s3_object(key: str) -> None:
    """Best-effort delete after a failed extraction. Never raises — a cleanup
    failure here must not mask the real extraction error the client is about
    to receive."""
    try:
        s3_service.delete_file(key)
    except s3_service.S3StorageError as exc:
        print(f"Failed to clean up orphaned S3 object {key}: {exc}")


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

    if not s3_service.is_configured():
        raise HTTPException(status_code=503, detail="File storage is not configured on the server.")

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

    s3_key = s3_service.build_object_key(current_user.id, original_name)

    try:
        s3_service.upload_file(contents, s3_key, content_type=file.content_type)
    except s3_service.S3StorageError:
        raise HTTPException(status_code=502, detail="Could not upload the file. Please try again.")

    # extraction.py needs a real filesystem path (PyMuPDF), so the S3 upload
    # is mirrored into a temp file for the duration of the extraction call.
    tmp_fd, filepath = tempfile.mkstemp(suffix=f".{extension}")
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(contents)

        text = get_document_text(llm, filepath, extension)
        fields = extract_invoice_fields(llm, text)
    except ExtractionError as exc:
        _cleanup_orphaned_s3_object(s3_key)
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        # Already normalized by ai_errors.call_gemini() (e.g. 429 quota
        # exhausted, 503 AI outage) inside get_document_text/
        # extract_invoice_fields — pass it through as-is instead of letting
        # the generic handler below flatten it back to a plain 502.
        _cleanup_orphaned_s3_object(s3_key)
        raise
    except Exception:
        _cleanup_orphaned_s3_object(s3_key)
        raise HTTPException(
            status_code=502,
            detail="Extraction failed unexpectedly. Please try again or enter the invoice manually.",
        )
    finally:
        os.remove(filepath)

    return {
        "message": "Invoice extracted successfully",
        "needs_review": fields["needs_review"],
        "extracted": fields,
        "s3_key": s3_key,
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

        # "Upcoming Bills" means unpaid payables specifically — matches the
        # AI CFO's upcoming_30d_obligations (compute_cash_flow_forecast),
        # which already excludes paid invoices and receivables. Without
        # these two filters this figure could count money coming IN
        # (receivables) or bills already paid as if still owed.
        if invoice.transaction_type != "payable" or invoice.is_paid:
            continue

        try:

            due = datetime.strptime(
                invoice.due_date,
                "%d-%m-%Y"
            )

            if due <= datetime.today() + timedelta(days=30):

                upcoming_bills += invoice.amount

        except (TypeError, ValueError):
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

    # Cash runway is computed by the one shared cfo.compute_runway() function
    # — same calculation the AI CFO page uses — so this can't drift from it
    # again. total_payables above is intentionally left as the sum of all
    # payables; it feeds the separate "Total Payables" stat tile, not runway.
    runway = cfo.compute_runway(invoices, current_balance)

    db.close()

    return {
        "current_balance": current_balance,
        "total_payables": total_payables,
        "upcoming_bills":upcoming_bills,
        "total_receivables": total_receivables,
        "cash_runway": runway["runway_days"],
        "monthly_burn": runway["monthly_burn"],
        "runway_method": runway["runway_method"],
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

            "description": invoice.description,

            "paid_at": invoice.paid_at

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

        category = normalize_category(invoice.category)

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

    _cleanup_orphaned_s3_object(invoice.s3_key)

    db.delete(invoice)

    db.commit()

    db.close()

    return {
        "message": "Invoice deleted"
    }


@app.get("/invoice/{invoice_id}/download-url")
def get_invoice_download_url(
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

    db.close()

    if not invoice or not invoice.s3_key:
        raise HTTPException(status_code=404, detail="Invoice not found")

    try:
        url = s3_service.generate_presigned_url(invoice.s3_key)
    except s3_service.S3StorageError:
        raise HTTPException(status_code=502, detail="Could not generate a download link. Please try again.")

    return {"url": url}


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
        update_data["category"] = normalize_category(update_data["category"])

    # Track when an invoice was marked paid so payment-delay analytics can
    # compare paid_at against due_date. Only stamp it on the transition to
    # paid; clear it if the user un-marks the invoice as paid.
    if "is_paid" in update_data:
        if update_data["is_paid"] and not invoice.is_paid:
            invoice.paid_at = datetime.today().strftime("%d-%m-%Y")
        elif not update_data["is_paid"]:
            invoice.paid_at = None

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
        "paid_at": invoice.paid_at,
    }

    db.close()

    return result


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

    category=normalize_category(data.category),

    due_date=data.due_date,

    transaction_type=
        data.transaction_type,

    user_id=current_user.id,

    invoice_number=(data.invoice_number or "").strip() or None,

    invoice_date=(data.invoice_date or "").strip() or None,

    gst=(data.gst or "").strip() or None,

    payment_terms=(data.payment_terms or "").strip() or None,

    description=(data.description or "").strip() or None,

    s3_key=data.s3_key,

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
        Invoice.is_paid == False,
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


def _generate_vendor_negotiation_email(llm, vendor, amount, due_date, category, goal) -> str:
    """Shared by the /vendor-negotiation route and the AI Copilot's
    vendor_negotiation intent, so there's exactly one negotiation prompt in
    the codebase instead of two copies drifting apart.
    """

    goal_text = {
        "extension": "requesting a payment extension",
        "discount": "requesting an early-payment discount",
        "installments": "requesting to split the payment into installments",
    }.get(goal, "requesting a payment extension")

    prompt = f"""
You are CashPilot AI, an expert CFO assistant helping a business negotiate with a vendor.

Vendor: {vendor}
Amount Due: ₹{amount}
Due Date: {due_date}
Category: {category or "General"}
Negotiation Goal: {goal_text}

Write a short, professional email to this vendor {goal_text}, preserving the
business relationship while protecting the company's liquidity. Be specific
and courteous. Do not invent numbers beyond what's provided.

Return ONLY the email body as plain text. No subject line, no markdown, no
code blocks, no HTML tags.
"""

    response = ai_errors.call_gemini(llm, prompt)
    return response.content


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

    message = _generate_vendor_negotiation_email(
        llm, data.vendor, data.amount, data.due_date, data.category, data.goal
    )

    return {
        "message": message
    }


# =============================================================================
# AI CFO — Financial Health Score, Cash Flow Forecast, Smart Recommendations,
# Business Risk Analysis, and the Scenario Simulator.
#
# Every number below comes from cfo.py's pure calculation functions, run
# against the user's real Invoice/User rows. Gemini (in /cfo/ai-recommendations
# only) is given the *results* of those calculations as text and asked to
# narrate them — it is never the source of a financial number.
# =============================================================================

def _load_simple_invoices(current_user: User):
    """Fetches the user's invoices and snapshots them into plain objects
    before closing the DB session, so the pure cfo.py functions never touch
    a SQLAlchemy session."""
    db = SessionLocal()
    invoices = db.query(Invoice).filter(Invoice.user_id == current_user.id).all()
    simple = [cfo.to_simple(i) for i in invoices]
    db.close()
    return simple


def _serialize_invoice(inv) -> dict:
    return {
        "id": inv.id,
        "vendor": inv.vendor,
        "amount": inv.amount,
        "due_date": inv.due_date,
        "category": inv.category,
        "transaction_type": inv.transaction_type,
    }


@app.get("/cfo/overview")
def cfo_overview(current_user: User = Depends(get_current_user)):

    invoices = _load_simple_invoices(current_user)
    balance = current_user.current_balance

    forecast = cfo.compute_cash_flow_forecast(invoices, balance)
    health = cfo.compute_financial_health(invoices, balance, forecast=forecast)
    payment_recommendations = cfo.rank_payment_recommendations(invoices, balance)
    receivable_recommendations = cfo.rank_receivable_recommendations(invoices)
    risks = cfo.compute_business_risks(invoices, balance, health, forecast)

    return {
        "health_score": health,
        "forecast": forecast,
        "payment_recommendations": payment_recommendations,
        "receivable_recommendations": receivable_recommendations,
        "risks": risks,
    }


@app.get("/cfo/ai-recommendations")
def cfo_ai_recommendations(current_user: User = Depends(get_current_user)):
    """Gemini-narrated actionable recommendations, grounded in the same
    server-computed numbers as /cfo/overview. Split into its own endpoint so
    the rest of the AI CFO page can render immediately without waiting on
    this (slower, AI-backed) call — same pattern as analytics.html loading
    /analytics-insights separately from /analytics-summary.
    """

    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="AI features are not configured. Set GOOGLE_API_KEY on the server.",
        )

    invoices = _load_simple_invoices(current_user)
    balance = current_user.current_balance

    forecast = cfo.compute_cash_flow_forecast(invoices, balance)
    health = cfo.compute_financial_health(invoices, balance, forecast=forecast)
    payment_recommendations = cfo.rank_payment_recommendations(invoices, balance)
    receivable_recommendations = cfo.rank_receivable_recommendations(invoices)
    risks = cfo.compute_business_risks(invoices, balance, health, forecast)

    top_payables = ", ".join(
        f"{r['vendor']} ({cfo.fmt_currency(r['amount'])}, {r['priority']}, due {r['due_date']})"
        for r in payment_recommendations[:5]
    ) or "None"

    top_receivables = ", ".join(
        f"{r['vendor']} ({cfo.fmt_currency(r['amount'])}, {r['priority']}, due {r['due_date']})"
        for r in receivable_recommendations[:5]
    ) or "None"

    risk_summary = "; ".join(f"{r['title']}: {r['message']}" for r in risks) or "None identified"

    summary = f"""
Financial Health Score: {health['score']}/100 ({health['rating']})
Cash Runway: {health['metrics']['runway_days']} days
Current Balance: {cfo.fmt_currency(balance)}
Outstanding Payables: {cfo.fmt_currency(health['metrics']['total_outstanding_payables'])}
Outstanding Receivables: {cfo.fmt_currency(health['metrics']['total_outstanding_receivables'])}
Overdue Payables: {health['metrics']['overdue_payables_count']} totaling {cfo.fmt_currency(health['metrics']['overdue_payables_amount'])}
Top Payment Priorities: {top_payables}
Top Receivable Follow-ups: {top_receivables}
Identified Risks: {risk_summary}
"""

    prompt = f"""
You are CashPilot AI, an expert CFO assistant. Below is this business's real,
already-calculated financial position. Do not invent or alter any numbers —
only reference the figures given.

{summary}

Return ONLY a single valid JSON object with exactly this shape:
{{
  "summary": "one or two sentence overall assessment",
  "recommendations": [
    {{
      "priority": "Critical" | "High" | "Medium" | "Low",
      "title": "short action title",
      "reason": "one to two sentence explanation referencing the real numbers above",
      "action": "short imperative next step, e.g. 'Delay this payment' or 'Follow up today'"
    }}
  ]
}}

Provide 3 to 5 recommendations (e.g. delaying a specific low-urgency payable,
collecting a specific overdue receivable, reducing discretionary spending,
raising the minimum cash reserve) grounded strictly in the data above, ranked
most important first. No markdown, no code fences, no extra text outside the
JSON object.
"""

    response = ai_errors.call_gemini(llm, prompt)

    raw = (response.content or "").strip()

    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if not match:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
    json_text = match.group(1) if (match and match.lastindex) else (match.group(0) if match else raw)

    try:
        parsed = json.loads(json_text)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=502, detail="AI recommendations could not be generated. Please try again.")

    valid_priorities = {"Critical", "High", "Medium", "Low"}

    return {
        "summary": str(parsed.get("summary") or ""),
        "recommendations": [
            {
                "priority": r.get("priority") if r.get("priority") in valid_priorities else "Medium",
                "title": str(r.get("title") or ""),
                "reason": str(r.get("reason") or ""),
                "action": str(r.get("action") or ""),
            }
            for r in (parsed.get("recommendations") or [])
            if isinstance(r, dict)
        ],
    }


class CfoScenarioRequest(BaseModel):
    scenario_type: str  # "delay_payable" | "accelerate_receivable" | "expense_increase"
    invoice_id: int | None = None
    days: int | None = None
    percent: float | None = None


@app.post("/cfo/scenario")
def cfo_scenario(
    data: CfoScenarioRequest,
    current_user: User = Depends(get_current_user),
):

    if data.scenario_type not in ("delay_payable", "accelerate_receivable", "expense_increase"):
        raise HTTPException(
            status_code=400,
            detail="scenario_type must be 'delay_payable', 'accelerate_receivable', or 'expense_increase'",
        )

    if data.scenario_type in ("delay_payable", "accelerate_receivable") and not data.invoice_id:
        raise HTTPException(status_code=400, detail="invoice_id is required for this scenario_type")

    invoices = _load_simple_invoices(current_user)
    balance = current_user.current_balance

    scenario = data.model_dump()

    baseline_forecast = cfo.compute_cash_flow_forecast(invoices, balance)
    baseline_health = cfo.compute_financial_health(invoices, balance, forecast=baseline_forecast)

    try:
        projected_invoices = cfo.apply_scenario(invoices, scenario)
    except cfo.ScenarioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    projected_forecast = cfo.compute_cash_flow_forecast(projected_invoices, balance)
    projected_health = cfo.compute_financial_health(projected_invoices, balance, forecast=projected_forecast)

    return {
        "description": cfo.describe_scenario(scenario, invoices),
        "baseline": {
            "balance": balance,
            "runway_days": baseline_health["metrics"]["runway_days"],
            "health_score": baseline_health["score"],
            "risk_level": cfo.risk_level_from_score(baseline_health["score"]),
        },
        "projected": {
            "balance": balance,
            "runway_days": projected_health["metrics"]["runway_days"],
            "health_score": projected_health["score"],
            "risk_level": cfo.risk_level_from_score(projected_health["score"]),
        },
        "forecast": projected_forecast,
    }


# =============================================================================
# AI Financial Copilot — natural-language questions answered by classifying
# intent with Gemini, then dispatching to the SAME deterministic cfo.py
# functions every other AI CFO feature already uses (rank_payment_
# recommendations, compute_financial_health, apply_scenario, etc.). Gemini
# only classifies the question and, for the two open-ended intents, narrates
# already-computed real numbers — it is never the source of a financial
# figure, matching the rest of the app's AI design.
# =============================================================================

COPILOT_INTENTS = [
    "payment_priority",
    "receivable_followup",
    "overdue_invoices",
    "health_score",
    "improve_runway",
    "biggest_expense",
    "cash_this_month",
    "scenario_delay_payable",
    "scenario_accelerate_receivable",
    "scenario_expense_increase",
    "vendor_negotiation",
    "general",
]

DEFAULT_SCENARIO_DAYS = 5
DEFAULT_SCENARIO_PERCENT = 10


def _classify_copilot_question(llm, question: str) -> dict:
    prompt = f"""
You are an intent classifier for a small-business finance copilot. Read the
user's question and classify it into exactly one of these intents:

- payment_priority: which vendor/payable to pay first, payment priorities
- receivable_followup: which customer/receivable to follow up or collect from
- overdue_invoices: show/list overdue invoices or bills
- health_score: financial health score, why it is what it is, "how healthy is my business"
- improve_runway: how to extend/improve cash runway
- biggest_expense: biggest expense, top spending category
- cash_this_month: how much cash goes out/comes in this month
- scenario_delay_payable: "what if I delay paying X", "can I delay vendor X by N days"
- scenario_accelerate_receivable: "what if client/customer X pays early/sooner"
- scenario_expense_increase: "what if expenses increase by X%"
- vendor_negotiation: generate/draft a negotiation or payment-extension email to a vendor
- general: anything else finance-related, or anything not covered above (including non-finance questions)

User question: "{question}"

Return ONLY a single valid JSON object with exactly these keys:
{{
  "intent": one of the intent names above (as a plain string),
  "vendor_name": the vendor or customer name mentioned in the question, or null,
  "days": the number of days mentioned, as a plain number, or null,
  "percent": the percentage mentioned, as a plain number, or null
}}

No markdown, no code fences, no extra text outside the JSON object.
"""
    response = ai_errors.call_gemini(llm, prompt)
    raw = (response.content or "").strip()

    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if not match:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
    json_text = match.group(1) if (match and match.lastindex) else (match.group(0) if match else raw)

    try:
        parsed = json.loads(json_text)
    except (json.JSONDecodeError, TypeError):
        parsed = {}

    intent = parsed.get("intent")
    if intent not in COPILOT_INTENTS:
        intent = "general"

    def _to_number(value):
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    days_raw = _to_number(parsed.get("days"))
    percent_raw = _to_number(parsed.get("percent"))

    return {
        "intent": intent,
        "vendor_name": (parsed.get("vendor_name") or None) if isinstance(parsed.get("vendor_name"), str) else None,
        "days": int(round(days_raw)) if days_raw is not None else None,
        "percent": percent_raw,
    }


def _copilot_grounding_summary(balance, health, extra: str = "") -> str:
    return f"""
Financial Health Score: {health['score']}/100 ({health['rating']})
Cash Runway: {health['metrics']['runway_days']} days
Current Balance: {cfo.fmt_currency(balance)}
Outstanding Payables: {cfo.fmt_currency(health['metrics']['total_outstanding_payables'])}
Outstanding Receivables: {cfo.fmt_currency(health['metrics']['total_outstanding_receivables'])}
Overdue Payables: {health['metrics']['overdue_payables_count']} totaling {cfo.fmt_currency(health['metrics']['overdue_payables_amount'])}
Vendor Concentration: {(health['metrics']['top_vendor'] or 'None')} at {health['metrics']['top_vendor_share'] * 100:.0f}% of payables
{extra}
"""


def _narrate_copilot_answer(llm, question, intent, invoices, balance, health, forecast) -> str:
    """The only two intents that get real AI narration — everything else is
    answered directly from deterministic text already produced by cfo.py."""

    extra = ""
    if intent == "improve_runway":
        payment_recs = cfo.rank_payment_recommendations(invoices, balance)[:3]
        risks = cfo.compute_business_risks(invoices, balance, health, forecast)
        top_recs = ", ".join(
            f"{r['vendor']} ({r['priority']}, {cfo.fmt_currency(r['amount'])})" for r in payment_recs
        ) or "None"
        risk_lines = "; ".join(r["message"] for r in risks) or "None identified"
        extra = f"Top payables by priority: {top_recs}\nIdentified risks: {risk_lines}"

    summary = _copilot_grounding_summary(balance, health, extra)

    prompt = f"""
You are CashPilot AI, an AI CFO copilot embedded in a small-business finance
app. You ONLY answer questions about this business's cash flow, runway,
payables, receivables, vendors, or expenses, using ONLY the real data below.
Never invent a number that is not given here.

If the question is not about business finance, reply exactly:
I can only answer questions about your business finances.

Business Data:
{summary}

User Question: {question}

Keep the answer under 120 words, specific, and grounded in the numbers above.
"""

    response = ai_errors.call_gemini(llm, prompt)
    return (response.content or "").strip()


def _run_copilot_scenario(intent, vendor_name, days, percent, invoices, balance, baseline_health):
    scenario_type = {
        "scenario_delay_payable": "delay_payable",
        "scenario_accelerate_receivable": "accelerate_receivable",
        "scenario_expense_increase": "expense_increase",
    }[intent]

    actions = [{"label": "Open Scenario Simulator", "type": "scroll_to_section", "section": "scenario-simulator"}]

    if scenario_type == "expense_increase":
        scenario = {
            "scenario_type": scenario_type,
            "percent": percent if percent is not None else DEFAULT_SCENARIO_PERCENT,
        }
    else:
        transaction_type = "payable" if scenario_type == "delay_payable" else "receivable"
        target = cfo.find_invoice_by_vendor(invoices, vendor_name, transaction_type=transaction_type)
        if target is None:
            who = "vendor" if transaction_type == "payable" else "customer"
            name_part = f' for "{vendor_name}"' if vendor_name else ""
            answer = (
                f"I couldn't find a matching unpaid {who} invoice{name_part}. "
                "Check the exact name in Invoice Hub and try again."
            )
            return answer, {"matched": False}, []
        scenario = {
            "scenario_type": scenario_type,
            "invoice_id": target.id,
            "days": days if days is not None else DEFAULT_SCENARIO_DAYS,
        }

    try:
        projected_invoices = cfo.apply_scenario(invoices, scenario)
    except cfo.ScenarioError as exc:
        return f"Couldn't run that scenario: {exc}", {"matched": False}, []

    projected_forecast = cfo.compute_cash_flow_forecast(projected_invoices, balance)
    projected_health = cfo.compute_financial_health(projected_invoices, balance, forecast=projected_forecast)

    description = cfo.describe_scenario(scenario, invoices)
    score_delta = projected_health["score"] - baseline_health["score"]
    runway_delta = projected_health["metrics"]["runway_days"] - baseline_health["metrics"]["runway_days"]

    answer = (
        f"{description}: your Health Score would go from {baseline_health['score']} to "
        f"{projected_health['score']} ({'+' if score_delta >= 0 else ''}{score_delta}), and runway from "
        f"{baseline_health['metrics']['runway_days']} to {projected_health['metrics']['runway_days']} days "
        f"({'+' if runway_delta >= 0 else ''}{runway_delta}). "
        f"Projected risk level: {cfo.risk_level_from_score(projected_health['score'])}."
    )

    data = {
        "matched": True,
        "description": description,
        "baseline": {
            "balance": balance,
            "runway_days": baseline_health["metrics"]["runway_days"],
            "health_score": baseline_health["score"],
            "risk_level": cfo.risk_level_from_score(baseline_health["score"]),
        },
        "projected": {
            "balance": balance,
            "runway_days": projected_health["metrics"]["runway_days"],
            "health_score": projected_health["score"],
            "risk_level": cfo.risk_level_from_score(projected_health["score"]),
        },
        "forecast": projected_forecast,
    }

    return answer, data, actions


def _run_copilot_negotiation(llm, vendor_name, invoices):
    target = cfo.find_invoice_by_vendor(invoices, vendor_name, transaction_type="payable")
    if target is None:
        name_part = f' for "{vendor_name}"' if vendor_name else ""
        answer = (
            f"I couldn't find a matching unpaid payable{name_part} to draft a negotiation email for. "
            "Check the vendor name in Invoice Hub and try again."
        )
        return answer, {"matched": False}

    email = _generate_vendor_negotiation_email(
        llm, target.vendor, target.amount, target.due_date, target.category, "extension"
    )
    return email, {"matched": True, "vendor": target.vendor, "invoice_id": target.id, "email": email}


class CopilotRequest(BaseModel):
    question: str


@app.post("/cfo/copilot")
def cfo_copilot(
    data: CopilotRequest,
    current_user: User = Depends(get_current_user),
):

    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="AI features are not configured. Set GOOGLE_API_KEY on the server.",
        )

    if not data.question or not data.question.strip():
        raise HTTPException(status_code=400, detail="Question is required")

    invoices = _load_simple_invoices(current_user)
    balance = current_user.current_balance

    classification = _classify_copilot_question(llm, data.question)
    intent = classification["intent"]
    vendor_name = classification["vendor_name"]
    days = classification["days"]
    percent = classification["percent"]

    forecast = cfo.compute_cash_flow_forecast(invoices, balance)
    health = cfo.compute_financial_health(invoices, balance, forecast=forecast)

    payload = None
    actions = []

    if intent == "payment_priority":
        recs = cfo.rank_payment_recommendations(invoices, balance)
        if recs:
            top = recs[0]
            answer = f"Pay {top['vendor']} first — {top['why']}"
            payload = {"recommendations": recs[:5]}
            actions = [
                {"label": "View Invoice", "type": "view_invoice", "invoice_id": top["id"]},
                {"label": "Generate Payment Plan", "type": "generate_payment_plan"},
            ]
        else:
            answer = "You don't have any outstanding payables right now."
            payload = {"recommendations": []}

    elif intent == "receivable_followup":
        recs = cfo.rank_receivable_recommendations(invoices)
        if recs:
            top = recs[0]
            answer = f"Follow up with {top['vendor']} first — {top['why']}"
            payload = {"recommendations": recs[:5]}
            actions = [{"label": "View Invoice", "type": "view_invoice", "invoice_id": top["id"]}]
        else:
            answer = "You don't have any outstanding receivables right now."
            payload = {"recommendations": []}

    elif intent == "overdue_invoices":
        today = datetime.today().date()
        overdue = [
            _serialize_invoice(i) for i in invoices
            if not i.is_paid and (cfo.parse_due_date(i.due_date) or today) < today
        ]
        if overdue:
            total = sum(i["amount"] for i in overdue)
            answer = f"You have {len(overdue)} overdue invoice(s) totaling {cfo.fmt_currency(total)}."
        else:
            answer = "You have no overdue invoices right now."
        payload = {"invoices": overdue}

    elif intent == "health_score":
        answer = health["explanation"]
        payload = {"health_score": health}
        actions = [{"label": "View Full Breakdown", "type": "scroll_to_section", "section": "financial-overview"}]

    elif intent == "biggest_expense":
        breakdown = cfo.category_breakdown([i for i in invoices if i.transaction_type == "payable"])
        if breakdown:
            top = breakdown[0]
            answer = f"Your biggest expense category is {top['category']} at {cfo.fmt_currency(top['amount'])}."
        else:
            answer = "You don't have any payables recorded yet to break down by category."
        payload = {"categories": breakdown}

    elif intent == "cash_this_month":
        bucket_30 = next((b for b in forecast if b["days"] == 30), None)
        if bucket_30:
            answer = (
                f"Based on invoices due within 30 days, {cfo.fmt_currency(bucket_30['outgoing'])} is projected to "
                f"go out and {cfo.fmt_currency(bucket_30['incoming'])} is projected to come in, for a projected "
                f"balance of {cfo.fmt_currency(bucket_30['closing_balance'])}."
            )
        else:
            answer = "No upcoming invoices are due within the next 30 days."
        payload = {"forecast": forecast}

    elif intent in ("scenario_delay_payable", "scenario_accelerate_receivable", "scenario_expense_increase"):
        answer, payload, actions = _run_copilot_scenario(intent, vendor_name, days, percent, invoices, balance, health)

    elif intent == "vendor_negotiation":
        answer, payload = _run_copilot_negotiation(llm, vendor_name, invoices)

    else:  # "improve_runway" and "general" — genuine open-ended AI narration
        answer = _narrate_copilot_answer(llm, data.question, intent, invoices, balance, health, forecast)

    return {
        "answer": answer,
        "intent": intent,
        "data": payload,
        "actions": actions,
    }