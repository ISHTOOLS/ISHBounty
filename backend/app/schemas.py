from decimal import Decimal

from pydantic import BaseModel, Field

from app.models import BountyStatus, Currency, PaymentDestinationType, PaymentStatus


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


class PaymentAccountCreate(BaseModel):
    owner_github: str = Field(min_length=1, max_length=100)
    currency: Currency
    destination_type: PaymentDestinationType = PaymentDestinationType.IBAN
    destination_value: str | None = Field(default=None, min_length=3, max_length=255)
    iban: str | None = Field(default=None, min_length=5, max_length=64)
    bank_name: str | None = Field(default=None, max_length=255)

    def resolved_destination_value(self) -> str:
        value = self.destination_value or self.iban
        if not value:
            raise ValueError("destination_value is required")
        return value


class PaymentAccountRead(BaseModel):
    id: str
    owner_github: str
    currency: Currency
    destination_type: PaymentDestinationType
    destination_masked: str
    iban_masked: str | None = None
    iban_fingerprint: str | None = None
    destination_fingerprint: str | None = None
    bank_name: str | None = None
    active: bool


class PaymentCreate(BaseModel):
    method: str = "DIRECT_BANK_TRANSFER"
    payment_account_id: str | None = None
    transfer_reference: str | None = Field(default=None, max_length=255)


class PaymentProofRequest(BaseModel):
    transfer_reference: str = Field(min_length=1, max_length=255)


class PaymentRead(BaseModel):
    id: str
    bounty_id: str
    payment_account_id: str | None = None
    method: str
    currency: Currency
    amount: Decimal
    status: PaymentStatus
    transfer_reference: str | None = None


class PaymentInstructionRead(BaseModel):
    payment_id: str
    bounty_id: str
    beneficiary_github: str
    bank_name: str | None = None
    destination_type: PaymentDestinationType
    destination_value: str
    iban: str | None = None
    amount: Decimal
    currency: Currency
    reference: str
    status: PaymentStatus


class WebhookResult(BaseModel):
    accepted: bool
    event: str
