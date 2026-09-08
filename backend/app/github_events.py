import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bounty, BountyStatus, PaymentAccount
from app.payment_provider import dispatch_payout
from app.services import create_payment, transition

ISSUE_REF = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.I)


def referenced_issues(text: str) -> list[int]:
    return sorted({int(x) for x in ISSUE_REF.findall(text or "")})


def _bounties(db: Session, repository: str, numbers: list[int]):
    if not numbers:
        return []
    return list(db.scalars(select(Bounty).where(Bounty.repository == repository, Bounty.issue_number.in_(numbers))))


def _auto_payment(db: Session, bounty: Bounty) -> None:
    if not bounty.solver_github:
        return
    account = db.scalars(select(PaymentAccount).where(
        PaymentAccount.owner_github == bounty.solver_github,
        PaymentAccount.currency == bounty.currency,
        PaymentAccount.active.is_(True),
    )).first()
    if not account:
        return
    payment = create_payment(db, bounty, "DIRECT_BANK_TRANSFER", None, account.id)
    try:
        transfer_id = dispatch_payout(payment, account)
    except Exception:
        transfer_id = None
    if transfer_id:
        payment.transfer_reference = transfer_id
        db.commit()


def handle_pull_request(db: Session, payload: dict) -> int:
    repo = payload.get("repository", {}).get("full_name")
    pr = payload.get("pull_request", {})
    numbers = referenced_issues((pr.get("title") or "") + "\n" + (pr.get("body") or ""))
    if not repo or not numbers:
        return 0
    changed = 0
    for bounty in _bounties(db, repo, numbers):
        if payload.get("action") in {"opened", "reopened", "synchronize"} and BountyStatus(bounty.status) == BountyStatus.CLAIMED:
            bounty.pull_request_number = pr.get("number")
            transition(db, bounty, BountyStatus.PR_SUBMITTED)
            changed += 1
        elif payload.get("action") == "closed" and pr.get("merged"):
            state = BountyStatus(bounty.status)
            if state in {BountyStatus.PR_SUBMITTED, BountyStatus.CI_PASSED}:
                bounty.pull_request_number = pr.get("number")
                transition(db, bounty, BountyStatus.MERGED)
                _auto_payment(db, bounty)
                changed += 1
    return changed


def handle_check_run(db: Session, payload: dict) -> int:
    check = payload.get("check_run", {})
    if payload.get("action") != "completed" or check.get("conclusion") != "success":
        return 0
    repo = payload.get("repository", {}).get("full_name")
    pr_numbers = [p.get("number") for p in check.get("pull_requests", []) if p.get("number")]
    if not repo or not pr_numbers:
        return 0
    bounties = list(db.scalars(select(Bounty).where(Bounty.repository == repo, Bounty.pull_request_number.in_(pr_numbers))))
    changed = 0
    for bounty in bounties:
        if BountyStatus(bounty.status) == BountyStatus.PR_SUBMITTED:
            transition(db, bounty, BountyStatus.CI_PASSED)
            changed += 1
    return changed
