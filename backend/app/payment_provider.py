"""Production payout-provider boundary.

The provider is deliberately HTTP-adapter based: credentials stay in the
runtime secret store and no banking credentials are committed to Git.
A provider must return a durable transfer id; ISHBounty never invents one.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.models import Payment, PaymentAccount
from app.payment_accounts import get_payout_iban


def dispatch_payout(payment: Payment, account: PaymentAccount) -> str | None:
    settings = get_settings()
    url = settings.payment_api_url
    token = settings.get_secret("payment_api_token", settings.payment_api_token)
    if not url or not token:
        return None
    iban = get_payout_iban(account)
    payload = json.dumps({
        "idempotency_key": payment.id,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "destination": {"iban": iban},
        "metadata": {"bounty_id": payment.bounty_id},
    }).encode()
    request = Request(url, data=payload, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Idempotency-Key": payment.id,
    })
    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode())
    transfer_id = data.get("transfer_id") or data.get("id")
    if not transfer_id:
        raise RuntimeError("payment provider returned no transfer id")
    return str(transfer_id)


def verify_provider_signature(body: bytes, signature: str | None) -> bool:
    secret = get_settings().get_secret("payment_webhook_secret", get_settings().payment_webhook_secret)
    if not secret or not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
