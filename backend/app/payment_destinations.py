"""Secure payment-destination management for IBAN and Kolay Adres.

Full destination values are stored only in ISHV2UltraCore. SQL keeps only
non-secret metadata, a fingerprint and a masked display value.
"""

from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.ishv2ultracore import ISHV2UltraCore
from app.models import Currency, PaymentDestination, PaymentDestinationType


def _store() -> ISHV2UltraCore:
    settings = get_settings()
    if not settings.ishv2ultracore_store_path or not settings.ishv2ultracore_master_key:
        raise ValueError("payment destination encryption is not configured")
    return ISHV2UltraCore(settings.ishv2ultracore_store_path, settings.ishv2ultracore_master_key)


def normalize_tckn(value: str) -> str:
    value = re.sub(r"\s+", "", value)
    if not re.fullmatch(r"\d{11}", value) or value[0] == "0":
        raise ValueError("invalid TCKN")
    digits = [int(char) for char in value]
    if digits[10] != sum(digits[:10]) % 10:
        raise ValueError("invalid TCKN checksum")
    if digits[9] != ((sum(digits[0:9:2]) * 7 - sum(digits[1:9:2])) % 10):
        raise ValueError("invalid TCKN checksum")
    return value


def normalize_phone(value: str) -> str:
    value = re.sub(r"[\s()\-]", "", value)
    if value.startswith("00"):
        value = "+" + value[2:]
    if value.startswith("0") and len(value) == 11:
        value = "+90" + value[1:]
    elif value.startswith("5") and len(value) == 10:
        value = "+90" + value
    if not re.fullmatch(r"\+90[5-9]\d{9}", value):
        raise ValueError("invalid Turkish phone number")
    return value


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("invalid email address")
    return value


def normalize_destination(destination_type: PaymentDestinationType, value: str) -> str:
    if destination_type == PaymentDestinationType.IBAN:
        from app.payment_accounts import normalize_iban
        return normalize_iban(value)
    if destination_type == PaymentDestinationType.PHONE:
        return normalize_phone(value)
    if destination_type == PaymentDestinationType.EMAIL:
        return normalize_email(value)
    if destination_type == PaymentDestinationType.TCKN:
        return normalize_tckn(value)
    raise ValueError("unsupported payment destination type")


def mask_destination(destination_type: PaymentDestinationType, value: str) -> str:
    if destination_type == PaymentDestinationType.IBAN:
        from app.payment_accounts import mask_iban
        return mask_iban(value)
    if destination_type == PaymentDestinationType.PHONE:
        return value[:3] + " *** *** " + value[-2:]
    if destination_type == PaymentDestinationType.EMAIL:
        local, domain = value.split("@", 1)
        return (local[:2] + "***" if len(local) > 2 else local + "***") + "@" + domain
    if destination_type == PaymentDestinationType.TCKN:
        return "*" * 7 + value[-4:]
    raise ValueError("unsupported payment destination type")


def create_payment_destination(
    db: Session,
    owner_github: str,
    currency: Currency,
    destination_type: PaymentDestinationType,
    destination: str,
    bank_name: str | None = None,
):
    normalized = normalize_destination(destination_type, destination)
    existing = db.scalars(
        select(PaymentDestination).where(
            PaymentDestination.owner_github == owner_github,
            PaymentDestination.currency == currency.value,
            PaymentDestination.destination_type == destination_type.value,
        )
    ).first()
    if existing:
        raise ValueError("payment destination already exists for owner, currency and type")

    destination_id = str(uuid4())
    store = _store()
    fingerprint = store.set(destination_id, normalized)
    item = PaymentDestination(
        id=destination_id,
        owner_github=owner_github,
        currency=currency.value,
        destination_type=destination_type.value,
        secret_key=destination_id,
        value_fingerprint=fingerprint,
        value_masked=mask_destination(destination_type, normalized),
        bank_name=bank_name,
        active=True,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        store.remove(destination_id)
        raise ValueError("payment destination already exists") from exc
    db.refresh(item)
    return item


def list_payment_destinations(db: Session, owner_github: str | None = None):
    query = select(PaymentDestination).where(PaymentDestination.active.is_(True)).order_by(PaymentDestination.created_at.desc())
    if owner_github:
        query = query.where(PaymentDestination.owner_github == owner_github)
    return list(db.scalars(query))


def get_payment_destination(db: Session, destination_id: str):
    return db.get(PaymentDestination, destination_id)


def delete_payment_destination(db: Session, item: PaymentDestination) -> None:
    _store().remove(item.secret_key)
    item.active = False
    db.commit()


def verify_payment_destination(item: PaymentDestination, owner_github: str, currency: str) -> None:
    if not item.active:
        raise ValueError("payment destination is inactive")
    if item.owner_github != owner_github:
        raise ValueError("payment destination owner mismatch")
    if item.currency != currency:
        raise ValueError("payment destination currency mismatch")
    if _store().get(item.secret_key) is None:
        raise ValueError("payment destination secret is unavailable")


def get_payment_destination_value(item: PaymentDestination) -> str:
    return _store().get(item.secret_key) or (_ for _ in ()).throw(
        ValueError("payment destination secret is unavailable")
    )
