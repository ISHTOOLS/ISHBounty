# ISHV2UltraCore secret protection

ISHBounty now uses the encryption design from `ISH-Enterprise/src/security/key-store.js` for reversible secret storage.

Compatibility parameters:

- KDF: scrypt (`N=32768`, `r=8`, `p=1`)
- Encryption: AES-256-GCM
- Salt: 16 random bytes
- IV: 12 random bytes
- Store format: version 2 JSON with per-secret ciphertext, authentication tag and SHA-256 fingerprint

The Python implementation is in `backend/app/core/ishv2ultracore.py` and is intentionally compatible with the key-store format used by ISH-Enterprise.

## Runtime configuration

Set these environment variables in the deployment secret store:

```text
ISHV2_ULTRACORE_STORE_PATH=./data/ishv2ultracore/secrets.json
ISHV2_ULTRACORE_MASTER_KEY=<runtime-only-secret>
```

When both are configured, `api_key` and `github_webhook_secret` are read from the ISHV2UltraCore store first. The existing environment variables remain a development/fallback path.

Never commit the master key, the generated secret store, API keys, webhook secrets, bank credentials, or user credentials.

## Important password distinction

This component is authenticated encryption for secrets that must later be recovered. It is **not** a password hashing scheme. End-user login passwords must be stored using a one-way password KDF such as Argon2id and must never be reversibly encrypted.
