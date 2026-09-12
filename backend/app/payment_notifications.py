from datetime import timedelta
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Bounty, BountyStatus, Payment, PaymentStatus

def process_notification(db: Session, *, amount: Decimal, currency: str, transfer_reference: str | None):
    ref = transfer_reference.strip()[:255] if transfer_reference else None
    if ref:
        payment = db.scalars(select(Payment).where(Payment.transfer_reference == ref, Payment.currency == currency)).first()
        if payment and payment.status != PaymentStatus.PAID.value:
            bounty = db.get(Bounty, payment.bounty_id)
            if bounty and BountyStatus(bounty.status) == BountyStatus.PAYMENT_PENDING and payment.amount == amount:
                payment.status = PaymentStatus.PAID.value
                bounty.status = BountyStatus.PAID.value
                db.commit()
                return {"decision": "AUTO_PAID", "matched_payment_id": payment.id, "candidates": [payment.id]}
    candidates = list(db.scalars(select(Payment).where(
        Payment.amount == amount,
        Payment.currency == currency,
        Payment.status.in_([PaymentStatus.PENDING.value, PaymentStatus.PROOF_SUBMITTED.value])
    ).order_by(Payment.created_at.desc())))
    return {"decision": "REVIEW_REQUIRED" if candidates else "NO_MATCH", "matched_payment_id": None, "candidates": [p.id for p in candidates]}
