from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4
from sqlalchemy import DateTime, Float, String, Text
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
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    repository: Mapped[str] = mapped_column(String(255), index=True)
    issue_number: Mapped[int] = mapped_column(index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    sponsor_github: Mapped[str] = mapped_column(String(100))
    solver_github: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default=BountyStatus.OPEN.value, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    bounty_id: Mapped[str] = mapped_column(String(36), index=True)
    method: Mapped[str] = mapped_column(String(40), default="DIRECT_BANK_TRANSFER")
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default=PaymentStatus.PENDING.value)
    transfer_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
