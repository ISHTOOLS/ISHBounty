import hashlib
import hmac
import json
import os

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db import Base, engine
from app.main import app
from app.models import WebhookDelivery

client = TestClient(app)


def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def payload(issue_number=1, repository="acme/project"):
    return {
        "repository": repository,
        "issue_number": issue_number,
        "title": "Fix hard bug",
        "description": "Production issue",
        "amount": 1000,
        "currency": "TRY",
        "sponsor_github": "acme",
    }


def signed_webhook(payload_data, delivery_id="delivery-1", event="pull_request", secret="test-secret"):
    body = json.dumps(payload_data).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/github/webhook",
        headers={
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": signature,
        },
        content=body,
    )


def configure_webhook_secret(secret="test-secret"):
    os.environ["GITHUB_WEBHOOK_SECRET"] = secret
    get_settings.cache_clear()


def clear_webhook_secret():
    os.environ.pop("GITHUB_WEBHOOK_SECRET", None)
    get_settings.cache_clear()


def test_create_claim_and_lifecycle():
    reset_db()
    created = client.post("/api/bounties", json=payload()).json()
    bid = created["id"]
    assert created["status"] == "OPEN"
    claimed = client.post(f"/api/bounties/{bid}/claim", json={"solver_github": "dev"})
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "CLAIMED"
    for state in ["PR_SUBMITTED", "CI_PASSED", "MERGED"]:
        r = client.post(f"/api/bounties/{bid}/transition", json={"status": state})
        assert r.status_code == 200
    payment = client.post(f"/api/bounties/{bid}/payment", json={"method": "DIRECT_BANK_TRANSFER"})
    assert payment.status_code == 201
    paid = client.post(
        f"/api/bounties/{bid}/payment/paid",
        json={"method": "DIRECT_BANK_TRANSFER", "transfer_reference": "TRX-1"},
    )
    assert paid.status_code == 200
    assert client.get(f"/api/bounties/{bid}").json()["status"] == "PAID"


def test_invalid_transition_rejected():
    reset_db()
    created = client.post("/api/bounties", json=payload(issue_number=2)).json()
    r = client.post(f"/api/bounties/{created['id']}/transition", json={"status": "PAID"})
    assert r.status_code == 409


def test_duplicate_repository_issue_rejected():
    reset_db()
    first = client.post("/api/bounties", json=payload(issue_number=7))
    assert first.status_code == 201
    duplicate = client.post("/api/bounties", json=payload(issue_number=7))
    assert duplicate.status_code == 409


def test_production_api_key_required():
    reset_db()
    os.environ["APP_ENV"] = "production"
    os.environ["ISHB_API_KEY"] = "test-api-key"
    get_settings.cache_clear()
    try:
        denied = client.post("/api/bounties", json=payload(issue_number=80))
        assert denied.status_code == 401
        allowed = client.post(
            "/api/bounties",
            headers={"X-ISHBounty-API-Key": "test-api-key"},
            json=payload(issue_number=81),
        )
        assert allowed.status_code == 201
    finally:
        os.environ.pop("APP_ENV", None)
        os.environ.pop("ISHB_API_KEY", None)
        get_settings.cache_clear()


def test_production_without_api_key_is_unavailable():
    reset_db()
    os.environ["APP_ENV"] = "production"
    os.environ.pop("ISHB_API_KEY", None)
    get_settings.cache_clear()
    try:
        denied = client.post("/api/bounties", json=payload(issue_number=82))
        assert denied.status_code == 503
    finally:
        os.environ.pop("APP_ENV", None)
        get_settings.cache_clear()


def test_webhook_pr_check_and_merge_lifecycle():
    reset_db()
    configure_webhook_secret()
    try:
        created = client.post("/api/bounties", json=payload(issue_number=42, repository="owner/repo")).json()
        bid = created["id"]
        client.post(f"/api/bounties/{bid}/claim", json={"solver_github": "dev"})

        pr_payload = {
            "action": "opened",
            "repository": {"full_name": "owner/repo"},
            "pull_request": {"number": 99, "title": "Fix issue", "body": "Fixes #42"},
        }
        r = signed_webhook(pr_payload, "delivery-pr", "pull_request")
        assert r.status_code == 200
        assert client.get(f"/api/bounties/{bid}").json()["status"] == "PR_SUBMITTED"

        check_payload = {
            "action": "completed",
            "repository": {"full_name": "owner/repo"},
            "check_run": {"conclusion": "success", "pull_requests": [{"number": 99}]},
        }
        r = signed_webhook(check_payload, "delivery-check", "check_run")
        assert r.status_code == 200
        assert client.get(f"/api/bounties/{bid}").json()["status"] == "CI_PASSED"

        merge_payload = {
            "action": "closed",
            "repository": {"full_name": "owner/repo"},
            "pull_request": {"number": 99, "title": "Fix issue", "body": "Fixes #42", "merged": True},
        }
        r = signed_webhook(merge_payload, "delivery-merge", "pull_request")
        assert r.status_code == 200
        assert client.get(f"/api/bounties/{bid}").json()["status"] == "MERGED"
    finally:
        clear_webhook_secret()


def test_webhook_duplicate_delivery_is_idempotent():
    reset_db()
    configure_webhook_secret()
    try:
        created = client.post("/api/bounties", json=payload(issue_number=43, repository="owner/repo")).json()
        bid = created["id"]
        client.post(f"/api/bounties/{bid}/claim", json={"solver_github": "dev"})
        pr_payload = {
            "action": "opened",
            "repository": {"full_name": "owner/repo"},
            "pull_request": {"number": 100, "title": "Fix issue", "body": "Fixes #43"},
        }
        first = signed_webhook(pr_payload, "duplicate-delivery")
        second = signed_webhook(pr_payload, "duplicate-delivery")
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["accepted"] is True
        assert client.get(f"/api/bounties/{bid}").json()["status"] == "PR_SUBMITTED"
        assert len(client.get("/api/bounties").json()) == 2
    finally:
        clear_webhook_secret()


def test_webhook_requires_configuration_and_delivery_id():
    reset_db()
    clear_webhook_secret()
    payload_data = {"action": "ping"}
    missing_config = client.post(
        "/api/github/webhook",
        headers={"X-GitHub-Event": "ping"},
        json=payload_data,
    )
    assert missing_config.status_code == 503

    configure_webhook_secret()
    try:
        missing_delivery = client.post(
            "/api/github/webhook",
            headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": "sha256=bad"},
            json=payload_data,
        )
        assert missing_delivery.status_code == 400
    finally:
        clear_webhook_secret()


def test_webhook_invalid_signature_rejected():
    reset_db()
    configure_webhook_secret()
    try:
        r = client.post(
            "/api/github/webhook",
            headers={
                "X-GitHub-Event": "ping",
                "X-GitHub-Delivery": "bad-signature",
                "X-Hub-Signature-256": "sha256=bad",
            },
            json={"zen": "test"},
        )
        assert r.status_code == 401
    finally:
        clear_webhook_secret()
