from sqlalchemy import Column, Integer, String, Float
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
        ForeignKey("users.id")
    )

    vendor = Column(String)

    amount = Column(Float)

    due_date = Column(String)

    category = Column(String)

    transaction_type = Column(
        String,
        default="payable"
    )

    currency = Column(
    String,
    default="INR"
)
class ManualExpenseRequest(
    BaseModel
):

    vendor: str

    amount: float

    category: str

    due_date: str

    transaction_type: str


class InvoiceUpdateRequest(BaseModel):

    vendor: str | None = None

    amount: float | None = None

    category: str | None = None

    due_date: str | None = None

    transaction_type: str | None = None


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
        unique=True
    )

    password = Column(String)

    company_name = Column(String, nullable=True)

    current_balance = Column(
        Float,
        default=75000
    )


class UpdateBalanceRequest(BaseModel):
    balance: float
