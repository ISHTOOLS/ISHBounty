import hashlib
import hmac
import json

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import Base, engine, ensure_payment_destination_schema, get_db
from app.github_events import handle_check_run, handle_pull_request
from app.models import BountyStatus, Payment, PaymentStatus, WebhookDelivery
from app.payment_accounts import create_payment_account, delete_payment_account, get_payment_account, list_payment_accounts
from app.payment_provider import verify_provider_signature
from app.schemas import BountyCreate, BountyRead, ClaimRequest, PaymentAccountCreate, PaymentAccountRead, PaymentCreate, PaymentInstructionRead, PaymentProofRequest, PaymentRead, TransitionRequest, WebhookResult
from app.services import claim, create_bounty, create_payment, get_bounty, get_payment_instruction, list_bounties, mark_paid, submit_payment_proof, transition

settings = get_settings()
Base.metadata.create_all(bind=engine)
ensure_payment_destination_schema()
app = FastAPI(title="ISHBounty API", version="1.2.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=False, allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])


def require_api_key(x_ishbounty_api_key: str | None = Header(default=None)) -> None:
    current = get_settings()
    if current.app_env.lower() in {"development", "test"}:
        return
    configured_api_key = current.effective_api_key
    if not configured_api_key:
        raise HTTPException(503, "API authentication is not configured")
    if not x_ishbounty_api_key or not hmac.compare_digest(configured_api_key, x_ishbounty_api_key):
        raise HTTPException(401, "invalid API key")


def require_bounty(db, bounty_id):
    bounty = get_bounty(db, bounty_id)
    if not bounty:
        raise HTTPException(404, "bounty not found")
    return bounty


@app.get("/health")
def health():
    return {"status": "ok", "service": "ishbounty-api", "environment": settings.app_env}


@app.post("/api/bounties", response_model=BountyRead, status_code=201, dependencies=[Depends(require_api_key)])
def create(data: BountyCreate, db: Session = Depends(get_db)):
    try:
        return create_bounty(db, data)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/api/bounties", response_model=list[BountyRead])
def all_bounties(db: Session = Depends(get_db)):
    return list_bounties(db)


@app.get("/api/bounties/{bounty_id}", response_model=BountyRead)
def one(bounty_id: str, db: Session = Depends(get_db)):
    return require_bounty(db, bounty_id)


@app.post("/api/bounties/{bounty_id}/claim", response_model=BountyRead, dependencies=[Depends(require_api_key)])
def claim_bounty(bounty_id: str, data: ClaimRequest, db: Session = Depends(get_db)):
    try:
        return claim(db, require_bounty(db, bounty_id), data.solver_github)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/bounties/{bounty_id}/transition", response_model=BountyRead, dependencies=[Depends(require_api_key)])
def change_status(bounty_id: str, data: TransitionRequest, db: Session = Depends(get_db)):
    try:
        return transition(db, require_bounty(db, bounty_id), data.status)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/payment-accounts", response_model=PaymentAccountRead, status_code=201, dependencies=[Depends(require_api_key)])
def add_payment_account(data: PaymentAccountCreate, db: Session = Depends(get_db)):
    try:
        return create_payment_account(
            db,
            data.owner_github,
            data.currency,
            data.destination_type,
            data.destination_value,
            data.bank_name,
        )
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/api/payment-accounts", response_model=list[PaymentAccountRead], dependencies=[Depends(require_api_key)])
def payment_accounts(owner_github: str | None = None, db: Session = Depends(get_db)):
    return list_payment_accounts(db, owner_github)


@app.delete("/api/payment-accounts/{account_id}", status_code=204, dependencies=[Depends(require_api_key)])
def remove_payment_account(account_id: str, db: Session = Depends(get_db)):
    account = get_payment_account(db, account_id)
    if not account:
        raise HTTPException(404, "payment account not found")
    try:
        delete_payment_account(db, account)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/bounties/{bounty_id}/payment", response_model=PaymentRead, status_code=201, dependencies=[Depends(require_api_key)])
def payment(bounty_id: str, data: PaymentCreate, db: Session = Depends(get_db)):
    if data.method != "DIRECT_BANK_TRANSFER":
        raise HTTPException(400, "only DIRECT_BANK_TRANSFER is supported for API-less payments")
    try:
        return create_payment(db, require_bounty(db, bounty_id), data.method, data.transfer_reference, data.payment_account_id)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/api/bounties/{bounty_id}/payment/instruction", response_model=PaymentInstructionRead, dependencies=[Depends(require_api_key)])
def payment_instruction(bounty_id: str, db: Session = Depends(get_db)):
    bounty = require_bounty(db, bounty_id)
    payment = db.query(Payment).filter(Payment.bounty_id == bounty.id).order_by(Payment.created_at.desc()).first()
    if not payment:
        raise HTTPException(404, "payment not found")
    try:
        return get_payment_instruction(db, bounty, payment)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/bounties/{bounty_id}/payment/proof", response_model=PaymentRead, dependencies=[Depends(require_api_key)])
def payment_proof(bounty_id: str, data: PaymentProofRequest, db: Session = Depends(get_db)):
    bounty = require_bounty(db, bounty_id)
    payment = db.query(Payment).filter(Payment.bounty_id == bounty.id).order_by(Payment.created_at.desc()).first()
    if not payment:
        raise HTTPException(404, "payment not found")
    try:
        return submit_payment_proof(db, bounty, payment, data.transfer_reference)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/bounties/{bounty_id}/payment/paid", response_model=PaymentRead, dependencies=[Depends(require_api_key)])
def paid(bounty_id: str, data: PaymentCreate, db: Session = Depends(get_db)):
    bounty = require_bounty(db, bounty_id)
    payment = db.query(Payment).filter(Payment.bounty_id == bounty.id).order_by(Payment.created_at.desc()).first()
    if not payment:
        raise HTTPException(404, "payment not found")
    try:
        return mark_paid(db, bounty, payment, data.transfer_reference)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/github/webhook", response_model=WebhookResult)
async def github_webhook(request: Request, x_github_event: str = Header(default="unknown"), x_github_delivery: str | None = Header(default=None), x_hub_signature_256: str | None = Header(default=None), db: Session = Depends(get_db)):
    body = await request.body()
    webhook_secret = get_settings().effective_github_webhook_secret
    if not webhook_secret:
        raise HTTPException(503, "GitHub webhook authentication is not configured")
    if not x_github_delivery:
        raise HTTPException(400, "missing GitHub delivery id")
    if not x_hub_signature_256:
        raise HTTPException(401, "missing signature")
    expected = "sha256=" + hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(401, "invalid signature")
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as e:
        raise HTTPException(400, "invalid JSON") from e
    delivery = WebhookDelivery(delivery_id=x_github_delivery, event=x_github_event)
    db.add(delivery)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"accepted": True, "event": x_github_event}
    if x_github_event == "pull_request":
        handle_pull_request(db, payload)
    elif x_github_event == "check_run":
        handle_check_run(db, payload)
    db.commit()
    return {"accepted": True, "event": x_github_event}


@app.post("/api/payment/webhook", response_model=WebhookResult)
async def payment_webhook(request: Request, x_payment_signature: str | None = Header(default=None), db: Session = Depends(get_db)):
    body = await request.body()
    if not verify_provider_signature(body, x_payment_signature):
        raise HTTPException(401, "invalid payment provider signature")
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as e:
        raise HTTPException(400, "invalid JSON") from e
    payment_id = payload.get("payment_id")
    status = str(payload.get("status", "")).upper()
    if not payment_id:
        raise HTTPException(400, "missing payment_id")
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(404, "payment not found")
    bounty = get_bounty(db, payment.bounty_id)
    if not bounty:
        raise HTTPException(404, "bounty not found")
    if status in {"PAID", "SETTLED", "COMPLETED"}:
        if BountyStatus(bounty.status) == BountyStatus.PAID and payment.status == PaymentStatus.PAID.value:
            return {"accepted": True, "event": "payment"}
        if BountyStatus(bounty.status) != BountyStatus.PAYMENT_PENDING:
            raise HTTPException(409, "bounty is not awaiting payment")
        mark_paid(db, bounty, payment, payload.get("transfer_id") or payment.transfer_reference)
    elif status in {"FAILED", "REJECTED"}:
        if payment.status != PaymentStatus.PAID.value and BountyStatus(bounty.status) != BountyStatus.PAID:
            payment.status = PaymentStatus.DISPUTED.value
            db.commit()
    return {"accepted": True, "event": "payment"}
