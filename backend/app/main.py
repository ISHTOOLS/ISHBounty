import hashlib, hmac, json
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db import Base, engine, get_db
from app.github_events import handle_check_run, handle_pull_request
from app.models import Payment
from app.schemas import BountyCreate, BountyRead, ClaimRequest, PaymentCreate, PaymentRead, TransitionRequest, WebhookResult
from app.services import claim, create_bounty, create_payment, get_bounty, list_bounties, mark_paid, transition

settings = get_settings()
Base.metadata.create_all(bind=engine)
app = FastAPI(title="ISHBounty API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=False, allow_methods=["GET","POST"], allow_headers=["*"])

def require_bounty(db, bounty_id):
    bounty = get_bounty(db, bounty_id)
    if not bounty: raise HTTPException(404, "bounty not found")
    return bounty

@app.get("/health")
def health(): return {"status":"ok","service":"ishbounty-api","environment":settings.app_env}

@app.post("/api/bounties", response_model=BountyRead, status_code=201)
def create(data: BountyCreate, db: Session = Depends(get_db)): return create_bounty(db, data)

@app.get("/api/bounties", response_model=list[BountyRead])
def all_bounties(db: Session = Depends(get_db)): return list_bounties(db)

@app.get("/api/bounties/{bounty_id}", response_model=BountyRead)
def one(bounty_id: str, db: Session = Depends(get_db)): return require_bounty(db, bounty_id)

@app.post("/api/bounties/{bounty_id}/claim", response_model=BountyRead)
def claim_bounty(bounty_id: str, data: ClaimRequest, db: Session = Depends(get_db)):
    try: return claim(db, require_bounty(db,bounty_id), data.solver_github)
    except ValueError as e: raise HTTPException(409, str(e))

@app.post("/api/bounties/{bounty_id}/transition", response_model=BountyRead)
def change_status(bounty_id: str, data: TransitionRequest, db: Session = Depends(get_db)):
    try: return transition(db, require_bounty(db,bounty_id), data.status)
    except ValueError as e: raise HTTPException(409, str(e))

@app.post("/api/bounties/{bounty_id}/payment", response_model=PaymentRead, status_code=201)
def payment(bounty_id: str, data: PaymentCreate, db: Session = Depends(get_db)):
    try: return create_payment(db, require_bounty(db,bounty_id), data.method, data.transfer_reference)
    except ValueError as e: raise HTTPException(409, str(e))

@app.post("/api/bounties/{bounty_id}/payment/paid", response_model=PaymentRead)
def paid(bounty_id: str, data: PaymentCreate, db: Session = Depends(get_db)):
    bounty = require_bounty(db,bounty_id)
    payment = db.query(Payment).filter(Payment.bounty_id == bounty.id).order_by(Payment.created_at.desc()).first()
    if not payment: raise HTTPException(404, "payment not found")
    try: return mark_paid(db,bounty,payment,data.transfer_reference)
    except ValueError as e: raise HTTPException(409, str(e))

@app.post("/api/github/webhook", response_model=WebhookResult)
async def github_webhook(request: Request, x_github_event: str = Header(default="unknown"), x_hub_signature_256: str | None = Header(default=None), db: Session = Depends(get_db)):
    body = await request.body()
    secret = settings.github_webhook_secret
    if secret:
        if not x_hub_signature_256: raise HTTPException(401,"missing signature")
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, x_hub_signature_256): raise HTTPException(401,"invalid signature")
    try: payload = json.loads(body or b"{}")
    except json.JSONDecodeError: raise HTTPException(400,"invalid JSON")
    if x_github_event == "pull_request": handle_pull_request(db, payload)
    elif x_github_event == "check_run": handle_check_run(db, payload)
    return {"accepted": True, "event": x_github_event}
