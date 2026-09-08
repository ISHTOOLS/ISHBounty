from decimal import Decimal
from pydantic import BaseModel, Field
from app.models import BountyStatus, Currency, PaymentStatus

class BountyCreate(BaseModel):
    repository: str = Field(min_length=1, max_length=255)
    issue_number: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: Currency
    sponsor_github: str = Field(min_length=1, max_length=100)

class BountyRead(BountyCreate):
    id: str
    status: BountyStatus
    solver_github: str | None = None

class ClaimRequest(BaseModel):
    solver_github: str = Field(min_length=1, max_length=100)

class TransitionRequest(BaseModel):
    status: BountyStatus

class PaymentCreate(BaseModel):
    method: str = "DIRECT_BANK_TRANSFER"
    transfer_reference: str | None = Field(default=None, max_length=255)

class PaymentRead(BaseModel):
    id: str
    bounty_id: str
    method: str
    currency: Currency
    amount: Decimal
    status: PaymentStatus
    transfer_reference: str | None = None

class WebhookResult(BaseModel):
    accepted: bool
    event: str
