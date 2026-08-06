from sqlalchemy import Column, Integer, String, Float, Boolean
from database import Base
from pydantic import BaseModel
from sqlalchemy import ForeignKey

class Invoice(Base):

    __tablename__ = "invoices"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        index=True
    )

    vendor = Column(String)

    amount = Column(Float)

    due_date = Column(String, index=True)

    category = Column(String)

    transaction_type = Column(
        String,
        default="payable",
        index=True
    )

    currency = Column(
    String,
    default="INR"
)

    is_paid = Column(Boolean, default=False, index=True)

    invoice_number = Column(String, nullable=True)

    invoice_date = Column(String, nullable=True)

    gst = Column(String, nullable=True)

    payment_terms = Column(String, nullable=True)

    description = Column(String, nullable=True)

    paid_at = Column(String, nullable=True)

class ManualExpenseRequest(
    BaseModel
):

    vendor: str

    amount: float

    category: str

    due_date: str

    transaction_type: str

    invoice_number: str | None = None

    invoice_date: str | None = None

    gst: str | None = None

    payment_terms: str | None = None

    description: str | None = None


class InvoiceUpdateRequest(BaseModel):

    vendor: str | None = None

    amount: float | None = None

    category: str | None = None

    due_date: str | None = None

    transaction_type: str | None = None

    is_paid: bool | None = None


class VendorNegotiationRequest(BaseModel):

    vendor: str

    amount: float

    due_date: str
    category: str | None = None
    goal: str = "extension"


class ScenarioRequest(BaseModel):

    current_balance: float

    scenario_cost: float

    projected_balance: float

    projected_runway: int

    total_payables: float


class ChatRequest(BaseModel):
    question: str


class User(Base):

    __tablename__ = "users"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    name = Column(String)

    email = Column(
        String,
        unique=True,
        index=True
    )

    password = Column(String)

    company_name = Column(String, nullable=True)

    current_balance = Column(
        Float,
        default=75000
    )


class UpdateBalanceRequest(BaseModel):
    balance: float
