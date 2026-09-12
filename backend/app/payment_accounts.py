"""Secure payout-destination management.

IBAN and KOLAS destination values are stored only in ISHV2UltraCore. The SQL
 database keeps non-secret metadata, fingerprints, and masked representations.
"""

from __future__ import annotations

import re
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.ishv2ultracore import ISHV2UltraCore
from app.models import Currency, PaymentAccount, PaymentDestinationType

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


def normalize_kolas(value: str, destination_type: PaymentDestinationType) -> str:
    if destination_type == PaymentDestinationType.IBAN:
        return normalize_iban(value)
    if destination_type == PaymentDestinationType.PHONE:
        normalized = re.sub(r"[\s()\-]", "", value.strip())
        if normalized.startswith("00"):
            normalized = "+" + normalized[2:]
        if normalized.startswith("0") and len(normalized) == 11:
            normalized = "+90" + normalized[1:]
        if not re.fullmatch(r"\+?[1-9][0-9]{9,14}", normalized):
            raise ValueError("invalid phone KOLAS value")
        return normalized
    if destination_type == PaymentDestinationType.EMAIL:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("invalid email KOLAS value")
        return normalized
    if destination_type == PaymentDestinationType.TCKN:
        normalized = re.sub(r"\s+", "", value)
        if not re.fullmatch(r"[1-9][0-9]{10}", normalized):
            raise ValueError("invalid TCKN KOLAS value")
        digits = [int(char) for char in normalized]
        if sum(digits[:10]) % 10 != digits[10]:
            raise ValueError("invalid TCKN checksum")
        if ((sum(digits[0:10:2]) * 7 - sum(digits[1:10:2])) % 10) != digits[9]:
            raise ValueError("invalid TCKN checksum")
        return normalized
    raise ValueError("unsupported payment destination type")


def mask_kolas(value: str, destination_type: PaymentDestinationType) -> str:
    normalized = normalize_kolas(value, destination_type)
    if destination_type == PaymentDestinationType.IBAN:
        return mask_iban(normalized)
    if destination_type == PaymentDestinationType.PHONE:
        return normalized[:3] + "******" + normalized[-2:]
    if destination_type == PaymentDestinationType.EMAIL:
        local, domain = normalized.split("@", 1)
        visible = local[:1] if local else "*"
        return visible + "***@" + domain
    return "******" + normalized[-5:]


def _fingerprint(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _store() -> ISHV2UltraCore:
    settings = get_settings()
    if not settings.ishv2ultracore_store_path or not settings.ishv2ultracore_master_key:
        raise ValueError("payment account encryption is not configured")
    return ISHV2UltraCore(settings.ishv2ultracore_store_path, settings.ishv2ultracore_master_key)


def create_payment_account(
    db: Session,
    owner_github: str,
    currency: Currency,
    destination_type: PaymentDestinationType,
    destination_value: str,
    bank_name: str | None,
):
    normalized = normalize_kolas(destination_value, destination_type)
    existing = db.scalars(select(PaymentAccount).where(PaymentAccount.owner_github == owner_github, PaymentAccount.currency == currency.value)).first()
    if existing:
        raise ValueError("payment account already exists for owner and currency")
    account_id = str(uuid4())
    store = _store()
    fingerprint = store.set(account_id, normalized)
    account = PaymentAccount(
        id=account_id,
        owner_github=owner_github,
        currency=currency.value,
        secret_key=account_id,
        iban_fingerprint=fingerprint if destination_type == PaymentDestinationType.IBAN else None,
        iban_masked=mask_iban(normalized) if destination_type == PaymentDestinationType.IBAN else None,
        destination_type=destination_type.value,
        destination_fingerprint=fingerprint,
        destination_masked=mask_kolas(normalized, destination_type),
        bank_name=bank_name,
        active=True,
    )
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


def get_payout_destination(account: PaymentAccount) -> str:
    """Retrieve the destination only at the final payout-instruction boundary."""
    return _store().get(account.secret_key) or (_ for _ in ()).throw(ValueError("payment account secret is unavailable"))


def get_payout_iban(account: PaymentAccount) -> str:
    """Retrieve an IBAN for an optional licensed payout provider."""
    if account.destination_type != PaymentDestinationType.IBAN.value:
        raise ValueError("configured payout provider requires an IBAN destination")
    return get_payout_destination(account)
