from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BountyStatus(StrEnum):
    OPEN = "OPEN"
    CLAIMED = "CLAIMED"
    PR_SUBMITTED = "PR_SUBMITTED"
    CI_PASSED = "CI_PASSED"
    MERGED = "MERGED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class Currency(StrEnum):
    TRY = "TRY"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    PROOF_SUBMITTED = "PROOF_SUBMITTED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class Bounty(Base):
    __tablename__ = "bounties"
    __table_args__ = (UniqueConstraint("repository", "issue_number", name="uq_bounty_repository_issue"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    repository: Mapped[str] = mapped_column(String(255), index=True)
    issue_number: Mapped[int] = mapped_column(index=True)
    pull_request_number: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3))
    sponsor_github: Mapped[str] = mapped_column(String(100))
    solver_github: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default=BountyStatus.OPEN.value, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class PaymentAccount(Base):
    __tablename__ = "payment_accounts"
    __table_args__ = (UniqueConstraint("owner_github", "currency", name="uq_payment_account_owner_currency"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_github: Mapped[str] = mapped_column(String(100), index=True)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    secret_key: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    iban_fingerprint: Mapped[str] = mapped_column(String(64))
    iban_masked: Mapped[str] = mapped_column(String(64))
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    bounty_id: Mapped[str] = mapped_column(String(36), index=True)
    payment_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(40), default="DIRECT_BANK_TRANSFER")
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=PaymentStatus.PENDING.value)
    transfer_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    delivery_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
