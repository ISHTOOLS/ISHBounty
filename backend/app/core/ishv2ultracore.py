"""ISH-Enterprise ISHV2UltraCore-compatible secret storage.

The implementation mirrors ISH-Enterprise's src/security/key-store.js:
- scrypt KDF (N=32768, r=8, p=1)
- AES-256-GCM authenticated encryption
- 16-byte random salt and 12-byte random IV
- versioned JSON key-store format

This module is for reversible secret/key protection. User authentication
passwords must still use a one-way password KDF such as Argon2id.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

VERSION = 2
KDF = "scrypt"
ALGORITHM = "aes-256-gcm"
SALT_BYTES = 16
KEY_BYTES = 32
IV_BYTES = 12


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _derive_key(master_key: str, salt: bytes) -> bytes:
    if not master_key:
        raise ValueError("MASTER_KEY_NOT_CONFIGURED")
    return Scrypt(
        salt=salt,
        length=KEY_BYTES,
        n=32768,
        r=8,
        p=1,
    ).derive(master_key.encode("utf-8"))


def _empty_state() -> dict[str, Any]:
    return {
        "version": VERSION,
        "kdf": KDF,
        "salt": _b64e(secrets.token_bytes(SALT_BYTES)),
        "keys": {},
    }


def _encrypt_item(value: str, key: bytes) -> dict[str, str]:
    plaintext = str(value).encode("utf-8")
    iv = secrets.token_bytes(IV_BYTES)
    encrypted = AESGCM(key).encrypt(iv, plaintext, None)
    ciphertext, tag = encrypted[:-16], encrypted[-16:]
    return {
        "algorithm": ALGORITHM,
        "iv": _b64e(iv),
        "ciphertext": _b64e(ciphertext),
        "tag": _b64e(tag),
        "fingerprint": hashlib.sha256(plaintext).hexdigest(),
    }


def _decrypt_item(item: dict[str, str], key: bytes) -> str:
    if item.get("algorithm") != ALGORITHM:
        raise ValueError("KEY_STORE_ALGORITHM_INVALID")
    iv = _b64d(item["iv"])
    ciphertext = _b64d(item["ciphertext"])
    tag = _b64d(item["tag"])
    return AESGCM(key).decrypt(iv, ciphertext + tag, None).decode("utf-8")


class ISHV2UltraCore:
    """Persistent secret store compatible with ISH-Enterprise key-store.js."""

    def __init__(self, path: str | os.PathLike[str], master_key: str) -> None:
        if not master_key:
            raise ValueError("MASTER_KEY_NOT_CONFIGURED")
        self.path = Path(path)
        self.master_key = master_key

    def _load(self) -> dict[str, Any]:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _empty_state()
        if (
            state.get("version") != VERSION
            or state.get("kdf") != KDF
            or not isinstance(state.get("salt"), str)
            or not isinstance(state.get("keys"), dict)
        ):
            raise ValueError("KEY_STORE_INVALID")
        return state

    def _save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        payload = json.dumps(
            {
                "version": VERSION,
                "kdf": KDF,
                "salt": state["salt"],
                "keys": state.get("keys", {}),
            },
            separators=(",", ":"),
        )
        temporary = self.path.with_name(
            f"{self.path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        )
        temporary.write_text(payload, encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def set(self, name: str, value: str) -> str:
        state = self._load()
        key = _derive_key(self.master_key, _b64d(state["salt"]))
        item = _encrypt_item(value, key)
        state.setdefault("keys", {})[str(name)] = item
        self._save(state)
        return item["fingerprint"]

    def get(self, name: str) -> str | None:
        state = self._load()
        item = state.get("keys", {}).get(str(name))
        if item is None:
            return None
        key = _derive_key(self.master_key, _b64d(state["salt"]))
        return _decrypt_item(item, key)

    def remove(self, name: str) -> bool:
        state = self._load()
        existed = str(name) in state.get("keys", {})
        state.setdefault("keys", {}).pop(str(name), None)
        self._save(state)
        return existed

    def list(self) -> list[str]:
        return sorted(self._load().get("keys", {}))
