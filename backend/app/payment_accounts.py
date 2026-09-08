"""Secure payout-account management.

Full IBAN values are stored only in ISHV2UltraCore. The SQL database keeps
non-secret metadata, a SHA-256 fingerprint, and a masked representation.
"""

from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.ishv2ultracore import ISHV2UltraCore
from app.models import Currency, PaymentAccount

_COUNTRY_IBAN_LENGTHS = {"TR": 26, "DE": 22, "FR": 27, "GB": 22, "NL": 18, "ES": 24, "IT": 27, "BE": 16, "AT": 20, "CH": 21, "LU": 20, "IE": 22, "PT": 25}


def normalize_iban(value: str) -> str:
    iban = re.sub(r"\s+", "", value).upper()
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]+", iban):
        raise ValueError("invalid IBAN format")
    expected = _COUNTRY_IBAN_LENGTHS.get(iban[:2])
    if expected and len(iban) != expected:
        raise ValueError("invalid IBAN length")
    if len(iban) < 15 or len(iban) > 34:
        raise ValueError("invalid IBAN length")
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(ord(char) - 55) if char.isalpha() else char for char in rearranged)
    if int(numeric) % 97 != 1:
        raise ValueError("invalid IBAN checksum")
    return iban


def mask_iban(iban: str) -> str:
    normalized = normalize_iban(iban)
    if len(normalized) <= 8:
        return "*" * len(normalized)
    return normalized[:4] + "*" * (len(normalized) - 8) + normalized[-4:]


def _store() -> ISHV2UltraCore:
    settings = get_settings()
    if not settings.ishv2ultracore_store_path or not settings.ishv2ultracore_master_key:
        raise ValueError("payment account encryption is not configured")
    return ISHV2UltraCore(settings.ishv2ultracore_store_path, settings.ishv2ultracore_master_key)


def create_payment_account(db: Session, owner_github: str, currency: Currency, iban: str, bank_name: str | None):
    normalized = normalize_iban(iban)
    existing = db.scalars(select(PaymentAccount).where(PaymentAccount.owner_github == owner_github, PaymentAccount.currency == currency.value)).first()
    if existing:
        raise ValueError("payment account already exists for owner and currency")
    account_id = str(uuid4())
    store = _store()
    fingerprint = store.set(account_id, normalized)
    account = PaymentAccount(id=account_id, owner_github=owner_github, currency=currency.value, secret_key=account_id, iban_fingerprint=fingerprint, iban_masked=mask_iban(normalized), bank_name=bank_name, active=True)
    db.add(account)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        store.remove(account_id)
        raise ValueError("payment account already exists") from exc
    db.refresh(account)
    return account


def list_payment_accounts(db: Session, owner_github: str | None = None):
    query = select(PaymentAccount).where(PaymentAccount.active.is_(True)).order_by(PaymentAccount.created_at.desc())
    if owner_github:
        query = query.where(PaymentAccount.owner_github == owner_github)
    return list(db.scalars(query))


def get_payment_account(db: Session, account_id: str):
    return db.get(PaymentAccount, account_id)


def delete_payment_account(db: Session, account: PaymentAccount) -> None:
    _store().remove(account.secret_key)
    account.active = False
    db.commit()


def verify_payment_account_owner_currency(account: PaymentAccount, owner_github: str, currency: str) -> None:
    if not account.active:
        raise ValueError("payment account is inactive")
    if account.owner_github != owner_github:
        raise ValueError("payment account owner mismatch")
    if account.currency != currency:
        raise ValueError("payment account currency mismatch")
    if _store().get(account.secret_key) is None:
        raise ValueError("payment account secret is unavailable")


def get_payout_iban(account: PaymentAccount) -> str:
    """Retrieve the IBAN only at the final payout-provider boundary."""
    return _store().get(account.secret_key) or (_ for _ in ()).throw(ValueError("payment account secret is unavailable"))
