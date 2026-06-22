from sqlalchemy import Column, Integer, String, Float
from database import Base
from pydantic import BaseModel


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)

    vendor = Column(String)
    amount = Column(Float)

    due_date = Column(String)

    category = Column(String)
    transaction_type = Column(
    String,
    default="payable"
)


class ManualExpenseRequest(
    BaseModel
):

    vendor: str

    amount: float

    category: str

    due_date: str

    transaction_type: str



class ScenarioRequest(BaseModel):

    current_balance: float

    scenario_cost: float

    projected_balance: float

    projected_runway: int

    total_payables: float