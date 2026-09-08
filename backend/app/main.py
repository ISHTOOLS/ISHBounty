import hashlib
import hmac
import json

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import Base, engine, get_db
from app.github_events import handle_check_run, handle_pull_request
from app.models import Payment, WebhookDelivery
from app.schemas import BountyCreate, BountyRead, ClaimRequest, PaymentCreate, PaymentRead, TransitionRequest, WebhookResult
from app.services import claim, create_bounty, create_payment, get_bounty, list_bounties, mark_paid, transition

settings = get_settings()
Base.metadata.create_all(bind=engine)
app = FastAPI(title="ISHBounty API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def require_api_key(x_ishbounty_api_key: str | None = Header(default=None)) -> None:
    """Protect state-changing application APIs in production."""
    current = get_settings()
    if current.app_env.lower() in {"development", "test"}:
        return
    if not current.api_key:
        raise HTTPException(503, "API authentication is not configured")
    if not x_ishbounty_api_key or not hmac.compare_digest(current.api_key, x_ishbounty_api_key):
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


@app.post("/api/bounties/{bounty_id}/payment", response_model=PaymentRead, status_code=201, dependencies=[Depends(require_api_key)])
def payment(bounty_id: str, data: PaymentCreate, db: Session = Depends(get_db)):
    try:
        return create_payment(db, require_bounty(db, bounty_id), data.method, data.transfer_reference)
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
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default="unknown"),
    x_github_delivery: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    body = await request.body()
    webhook_secret = get_settings().github_webhook_secret
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
