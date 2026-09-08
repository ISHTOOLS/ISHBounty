from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Bounty, BountyStatus, Payment, PaymentStatus

_ALLOWED = {
    BountyStatus.OPEN: {BountyStatus.CLAIMED, BountyStatus.CANCELLED},
    BountyStatus.CLAIMED: {BountyStatus.PR_SUBMITTED, BountyStatus.CANCELLED},
    BountyStatus.PR_SUBMITTED: {BountyStatus.CI_PASSED, BountyStatus.CANCELLED},
    BountyStatus.CI_PASSED: {BountyStatus.MERGED, BountyStatus.CANCELLED},
    BountyStatus.MERGED: {BountyStatus.PAYMENT_PENDING},
    BountyStatus.PAYMENT_PENDING: {BountyStatus.PAID, BountyStatus.DISPUTED},
    BountyStatus.PAID: set(),
    BountyStatus.DISPUTED: {BountyStatus.PAYMENT_PENDING, BountyStatus.CANCELLED},
    BountyStatus.CANCELLED: set(),
}

def create_bounty(db: Session, data):
    bounty = Bounty(**data.model_dump(), status=BountyStatus.OPEN.value)
    db.add(bounty); db.commit(); db.refresh(bounty)
    return bounty

def get_bounty(db: Session, bounty_id: str):
    return db.get(Bounty, bounty_id)

def list_bounties(db: Session):
    return list(db.scalars(select(Bounty).order_by(Bounty.created_at.desc())))

def transition(db: Session, bounty: Bounty, target: BountyStatus):
    current = BountyStatus(bounty.status)
    if target not in _ALLOWED[current]:
        raise ValueError(f"invalid transition: {current} -> {target}")
    bounty.status = target.value
    db.commit(); db.refresh(bounty)
    return bounty

def claim(db: Session, bounty: Bounty, solver: str):
    if BountyStatus(bounty.status) != BountyStatus.OPEN:
        raise ValueError("bounty is not open")
    bounty.solver_github = solver
    return transition(db, bounty, BountyStatus.CLAIMED)

def create_payment(db: Session, bounty: Bounty, method: str, reference: str | None):
    if BountyStatus(bounty.status) != BountyStatus.MERGED:
        raise ValueError("payment can only be created after merge")
    transition(db, bounty, BountyStatus.PAYMENT_PENDING)
    payment = Payment(bounty_id=bounty.id, method=method, currency=bounty.currency, amount=bounty.amount, transfer_reference=reference)
    db.add(payment); db.commit(); db.refresh(payment)
    return payment

def mark_paid(db: Session, bounty: Bounty, payment: Payment, reference: str | None):
    if BountyStatus(bounty.status) != BountyStatus.PAYMENT_PENDING:
        raise ValueError("bounty is not awaiting payment")
    payment.status = PaymentStatus.PAID.value
    payment.transfer_reference = reference or payment.transfer_reference
    bounty.status = BountyStatus.PAID.value
    db.commit(); db.refresh(payment); db.refresh(bounty)
    return payment
