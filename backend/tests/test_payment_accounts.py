import json
import os

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.ishv2ultracore import ISHV2UltraCore
from app.db import Base, engine
from app.main import app
from app.payment_accounts import mask_iban, normalize_iban

client = TestClient(app)
VALID_IBAN = "TR330006100519786457841326"


def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def configure_store(tmp_path):
    os.environ["ISHV2_ULTRACORE_STORE_PATH"] = str(tmp_path / "secrets.json")
    os.environ["ISHV2_ULTRACORE_MASTER_KEY"] = "test-master-key"
    get_settings.cache_clear()


def clear_store_config():
    os.environ.pop("ISHV2_ULTRACORE_STORE_PATH", None)
    os.environ.pop("ISHV2_ULTRACORE_MASTER_KEY", None)
    get_settings.cache_clear()


def test_iban_normalization_checksum_and_masking():
    spaced = "TR33 0006 1005 1978 6457 8413 26"
    assert normalize_iban(spaced) == VALID_IBAN
    masked = mask_iban(VALID_IBAN)
    assert masked.startswith("TR33")
    assert masked.endswith("1326")
    assert VALID_IBAN not in masked


def test_invalid_iban_rejected():
    invalid = VALID_IBAN[:-1] + "7"
    try:
        normalize_iban(invalid)
    except ValueError as exc:
        assert "checksum" in str(exc)
    else:
        raise AssertionError("invalid IBAN was accepted")


def test_payment_account_is_encrypted_and_masked(tmp_path):
    reset_db()
    configure_store(tmp_path)
    try:
        response = client.post(
            "/api/payment-accounts",
            json={
                "owner_github": "solver",
                "currency": "TRY",
                "iban": "TR33 0006 1005 1978 6457 8413 26",
                "bank_name": "Test Bank",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["currency"] == "TRY"
        assert data["iban_masked"].endswith("1326")
        assert VALID_IBAN not in json.dumps(data)

        raw_store = (tmp_path / "secrets.json").read_text(encoding="utf-8")
        assert VALID_IBAN not in raw_store
        assert ISHV2UltraCore(tmp_path / "secrets.json", "test-master-key").get(data["id"]) == VALID_IBAN

        listed = client.get("/api/payment-accounts", params={"owner_github": "solver"})
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert VALID_IBAN not in listed.text
    finally:
        clear_store_config()


def test_payment_account_duplicate_currency_rejected(tmp_path):
    reset_db()
    configure_store(tmp_path)
    try:
        body = {
            "owner_github": "solver",
            "currency": "EUR",
            "iban": VALID_IBAN,
        }
        assert client.post("/api/payment-accounts", json=body).status_code == 201
        assert client.post("/api/payment-accounts", json=body).status_code == 409
    finally:
        clear_store_config()


def test_payment_links_to_solver_account(tmp_path):
    reset_db()
    configure_store(tmp_path)
    try:
        created = client.post(
            "/api/bounties",
            json={
                "repository": "owner/payments",
                "issue_number": 901,
                "title": "Payment test",
                "description": "",
                "amount": 100,
                "currency": "TRY",
                "sponsor_github": "sponsor",
            },
        ).json()
        bid = created["id"]
        assert client.post(f"/api/bounties/{bid}/claim", json={"solver_github": "solver"}).status_code == 200
        for state in ["PR_SUBMITTED", "CI_PASSED", "MERGED"]:
            assert client.post(f"/api/bounties/{bid}/transition", json={"status": state}).status_code == 200

        account = client.post(
            "/api/payment-accounts",
            json={"owner_github": "solver", "currency": "TRY", "iban": VALID_IBAN},
        ).json()
        payment = client.post(
            f"/api/bounties/{bid}/payment",
            json={"method": "DIRECT_BANK_TRANSFER", "payment_account_id": account["id"]},
        )
        assert payment.status_code == 201
        assert payment.json()["payment_account_id"] == account["id"]
    finally:
        clear_store_config()
