from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bounty, BountyStatus, Payment, PaymentStatus, PaymentDestinationType
from app.payment_accounts import get_payment_account, get_payout_iban, verify_payment_account_owner_currency
from app.payment_destinations import get_payment_destination, get_payment_destination_value, verify_payment_destination

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
    existing = db.scalars(
        select(Bounty).where(
            Bounty.repository == data.repository,
            Bounty.issue_number == data.issue_number,
        )
    ).first()
    if existing:
        raise ValueError("bounty already exists for repository and issue")
    bounty = Bounty(**data.model_dump(), status=BountyStatus.OPEN.value)
    db.add(bounty)
    db.commit()
    db.refresh(bounty)
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
    db.commit()
    db.refresh(bounty)
    return bounty


def claim(db: Session, bounty: Bounty, solver: str):
    if BountyStatus(bounty.status) != BountyStatus.OPEN:
        raise ValueError("bounty is not open")
    bounty.solver_github = solver
    return transition(db, bounty, BountyStatus.CLAIMED)


def create_payment(
    db: Session,
    bounty: Bounty,
    method: str,
    reference: str | None,
    payment_account_id: str | None = None,
    payment_destination_id: str | None = None,
):
    if BountyStatus(bounty.status) != BountyStatus.MERGED:
        raise ValueError("payment can only be created after merge")
    if payment_account_id and payment_destination_id:
        raise ValueError("choose either payment_account_id or payment_destination_id")
    if not bounty.solver_github:
        raise ValueError("bounty has no solver")

    account = None
    destination = None
    if payment_account_id:
        account = get_payment_account(db, payment_account_id)
        if not account:
            raise ValueError("payment account not found")
        verify_payment_account_owner_currency(account, bounty.solver_github, bounty.currency)
    elif payment_destination_id:
        destination = get_payment_destination(db, payment_destination_id)
        if not destination:
            raise ValueError("payment destination not found")
        verify_payment_destination(destination, bounty.solver_github, bounty.currency)

    transition(db, bounty, BountyStatus.PAYMENT_PENDING)
    payment = Payment(
        bounty_id=bounty.id,
        payment_account_id=account.id if account else None,
        payment_destination_id=destination.id if destination else None,
        method=method,
        currency=bounty.currency,
        amount=bounty.amount,
        transfer_reference=reference,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def get_payment_instruction(db: Session, bounty: Bounty, payment: Payment):
    if bounty.solver_github is None:
        raise ValueError("bounty has no solver")

    if payment.payment_destination_id:
        destination = get_payment_destination(db, payment.payment_destination_id)
        if not destination or not destination.active:
            raise ValueError("beneficiary payment destination is unavailable")
        verify_payment_destination(destination, bounty.solver_github, bounty.currency)
        value = get_payment_destination_value(destination)
        destination_type = PaymentDestinationType(destination.destination_type)
        return {
            "payment_id": payment.id,
            "bounty_id": bounty.id,
            "beneficiary_github": bounty.solver_github,
            "destination_type": destination_type,
            "destination": value,
            "bank_name": destination.bank_name,
            "iban": None,
            "amount": payment.amount,
            "currency": payment.currency,
            "reference": payment.transfer_reference or payment.id,
            "status": payment.status,
        }

    if payment.payment_account_id is None:
        raise ValueError("payment has no beneficiary payment destination")
    account = get_payment_account(db, payment.payment_account_id)
    if not account or not account.active:
        raise ValueError("beneficiary payment account is unavailable")
    verify_payment_account_owner_currency(account, bounty.solver_github, bounty.currency)
    iban = get_payout_iban(account)
    return {
        "payment_id": payment.id,
        "bounty_id": bounty.id,
        "beneficiary_github": bounty.solver_github,
        "destination_type": PaymentDestinationType.IBAN,
        "destination": iban,
        "bank_name": account.bank_name,
        "iban": iban,
        "amount": payment.amount,
        "currency": payment.currency,
        "reference": payment.transfer_reference or payment.id,
        "status": payment.status,
    }


def submit_payment_proof(db: Session, bounty: Bounty, payment: Payment, reference: str):
    if BountyStatus(bounty.status) != BountyStatus.PAYMENT_PENDING:
        raise ValueError("bounty is not awaiting payment")
    if payment.status == PaymentStatus.PAID.value:
        return payment
    payment.status = PaymentStatus.PROOF_SUBMITTED.value
    payment.transfer_reference = reference
    db.commit()
    db.refresh(payment)
    return payment


def mark_paid(db: Session, bounty: Bounty, payment: Payment, reference: str | None):
    if BountyStatus(bounty.status) != BountyStatus.PAYMENT_PENDING:
        raise ValueError("bounty is not awaiting payment")
    payment.status = PaymentStatus.PAID.value
    payment.transfer_reference = reference or payment.transfer_reference
    bounty.status = BountyStatus.PAID.value
    db.commit()
    db.refresh(payment)
    db.refresh(bounty)
    return payment
