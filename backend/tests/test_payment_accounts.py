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
        assert data["destination_type"] == "IBAN"
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

        instruction = client.get(f"/api/bounties/{bid}/payment/instruction")
        assert instruction.status_code == 200
        instruction_data = instruction.json()
        assert instruction_data["destination_type"] == "IBAN"
        assert instruction_data["iban"] == VALID_IBAN
        assert instruction_data["amount"] == "100.00"
        assert instruction_data["currency"] == "TRY"
        assert instruction_data["reference"] == payment.json()["id"]
        assert instruction_data["status"] == "PENDING"

        proof = client.post(
            f"/api/bounties/{bid}/payment/proof",
            json={"transfer_reference": "BANK-REFERENCE-123"},
        )
        assert proof.status_code == 200
        assert proof.json()["status"] == "PROOF_SUBMITTED"
        assert proof.json()["transfer_reference"] == "BANK-REFERENCE-123"

        bounty = client.get(f"/api/bounties/{bid}").json()
        assert bounty["status"] == "PAYMENT_PENDING"
    finally:
        clear_store_config()


def test_kolas_payment_destinations_are_encrypted_and_usable(tmp_path):
    reset_db()
    configure_store(tmp_path)
    try:
        destinations = [
            ("PHONE", "+905551112233", "+905551112233"),
            ("EMAIL", "Solver@Example.Test", "solver@example.test"),
            ("TCKN", "10000000146", "10000000146"),
        ]
        for index, (destination_type, raw_value, normalized) in enumerate(destinations, start=1):
            response = client.post(
                "/api/payment-accounts",
                json={
                    "owner_github": f"solver-{index}",
                    "currency": "TRY",
                    "destination_type": destination_type,
                    "destination_value": raw_value,
                    "bank_name": "Enpara Test",
                },
            )
            assert response.status_code == 201, response.text
            data = response.json()
            assert data["destination_type"] == destination_type
            assert normalized not in response.text
            assert data["destination_fingerprint"]
            assert data["destination_masked"]

            stored = ISHV2UltraCore(tmp_path / "secrets.json", "test-master-key").get(data["id"])
            assert stored == normalized

        raw_store = (tmp_path / "secrets.json").read_text(encoding="utf-8")
        assert "+905551112233" not in raw_store
        assert "solver@example.test" not in raw_store
        assert "10000000146" not in raw_store
    finally:
        clear_store_config()
