import json
import os

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.ishv2ultracore import ISHV2UltraCore
from app.db import Base, engine
from app.main import app
from app.payment_accounts import mask_iban, normalize_iban
from app.payment_destinations import normalize_phone, normalize_tckn

client = TestClient(app)
VALID_IBAN = "TR330006100519786457841326"
VALID_TCKN = "10000000142"
VALID_PHONE = "+905551112233"
VALID_EMAIL = "solver@example.test"


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


def test_kolay_adres_normalization():
    assert normalize_phone("0555 111 22 33") == VALID_PHONE
    assert normalize_tckn(VALID_TCKN) == VALID_TCKN


def test_three_kolay_adres_destinations_can_be_active_together(tmp_path):
    reset_db()
    configure_store(tmp_path)
    try:
        bodies = [
            {"owner_github": "solver", "currency": "TRY", "destination_type": "PHONE", "destination": "0555 111 22 33"},
            {"owner_github": "solver", "currency": "TRY", "destination_type": "EMAIL", "destination": VALID_EMAIL},
            {"owner_github": "solver", "currency": "TRY", "destination_type": "TCKN", "destination": VALID_TCKN},
        ]
        created = [client.post("/api/payment-destinations", json=body) for body in bodies]
        assert [response.status_code for response in created] == [201, 201, 201]
        payloads = [response.json() for response in created]
        assert {item["destination_type"] for item in payloads} == {"PHONE", "EMAIL", "TCKN"}
        assert VALID_PHONE not in json.dumps(payloads)
        assert VALID_EMAIL not in json.dumps(payloads)
        assert VALID_TCKN not in json.dumps(payloads)

        raw_store = (tmp_path / "secrets.json").read_text(encoding="utf-8")
        assert VALID_PHONE not in raw_store
        assert VALID_EMAIL not in raw_store
        assert VALID_TCKN not in raw_store

        listed = client.get("/api/payment-destinations", params={"owner_github": "solver"})
        assert listed.status_code == 200
        assert len(listed.json()) == 3
        assert VALID_PHONE not in listed.text
        assert VALID_EMAIL not in listed.text
        assert VALID_TCKN not in listed.text
    finally:
        clear_store_config()


def test_payment_can_use_kolay_adres_and_instruction_returns_real_destination(tmp_path):
    reset_db()
    configure_store(tmp_path)
    try:
        created = client.post(
            "/api/bounties",
            json={
                "repository": "owner/kolay-adres",
                "issue_number": 902,
                "title": "Kolay Adres payment test",
                "description": "",
                "amount": 125,
                "currency": "TRY",
                "sponsor_github": "sponsor",
            },
        ).json()
        bid = created["id"]
        assert client.post(f"/api/bounties/{bid}/claim", json={"solver_github": "solver"}).status_code == 200
        for state in ["PR_SUBMITTED", "CI_PASSED", "MERGED"]:
            assert client.post(f"/api/bounties/{bid}/transition", json={"status": state}).status_code == 200

        destination = client.post(
            "/api/payment-destinations",
            json={
                "owner_github": "solver",
                "currency": "TRY",
                "destination_type": "PHONE",
                "destination": VALID_PHONE,
                "bank_name": "Enpara",
            },
        ).json()
        payment = client.post(
            f"/api/bounties/{bid}/payment",
            json={"method": "DIRECT_BANK_TRANSFER", "payment_destination_id": destination["id"]},
        )
        assert payment.status_code == 201
        assert payment.json()["payment_destination_id"] == destination["id"]

        instruction = client.get(f"/api/bounties/{bid}/payment/instruction")
        assert instruction.status_code == 200
        data = instruction.json()
        assert data["destination_type"] == "PHONE"
        assert data["destination"] == VALID_PHONE
        assert data["bank_name"] == "Enpara"
        assert data["amount"] == "125.00"
        assert data["currency"] == "TRY"
        assert data["reference"] == payment.json()["id"]
        assert data["status"] == "PENDING"

        proof = client.post(
            f"/api/bounties/{bid}/payment/proof",
            json={"transfer_reference": "FAST-REFERENCE-123"},
        )
        assert proof.status_code == 200
        assert proof.json()["status"] == "PROOF_SUBMITTED"
        assert proof.json()["transfer_reference"] == "FAST-REFERENCE-123"
        assert client.get(f"/api/bounties/{bid}").json()["status"] == "PAYMENT_PENDING"
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
        assert instruction_data["destination"] == VALID_IBAN
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
