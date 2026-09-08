from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from app.core.ishv2ultracore import ISHV2UltraCore


def test_round_trip_and_at_rest_protection(tmp_path: Path):
    path = tmp_path / "secrets.json"
    store = ISHV2UltraCore(path, "test-master-key")

    fingerprint = store.set("api_key", "super-secret-value")
    assert len(fingerprint) == 64
    assert store.get("api_key") == "super-secret-value"
    assert store.list() == ["api_key"]
    assert "super-secret-value" not in path.read_text(encoding="utf-8")


def test_wrong_master_key_cannot_decrypt(tmp_path: Path):
    path = tmp_path / "secrets.json"
    ISHV2UltraCore(path, "correct-master-key").set("token", "secret")

    with pytest.raises(InvalidTag):
        ISHV2UltraCore(path, "wrong-master-key").get("token")


def test_remove_is_idempotent(tmp_path: Path):
    store = ISHV2UltraCore(tmp_path / "secrets.json", "master")
    store.set("token", "secret")
    assert store.remove("token") is True
    assert store.remove("token") is False
    assert store.get("token") is None
