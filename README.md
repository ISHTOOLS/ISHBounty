# ISHBounty

GitHub-native bounty marketplace for software development work.

## MVP

- Bounties live as GitHub Issues.
- Rewards are declared in issue metadata.
- Solutions are submitted through Pull Requests.
- GitHub Actions provides the authoritative CI result.
- A deterministic bounty state machine tracks OPEN → PR_SUBMITTED → CI_PASSED → MERGED → PAYMENT_PENDING → PAID.
- MVP settlement is direct sponsor-to-developer bank transfer. ISHBounty does **not** hold user funds.
- Payment records support TRY, USD and EUR and are designed for a future licensed payment-provider adapter.

## Repository layout

- `backend/` FastAPI API, domain services and tests.
- `frontend/` minimal production-ready web shell for the public marketplace.
- `.github/workflows/` CI and security checks.
- `docs/` architecture, bounty lifecycle and payment model.

## Security principles

No secrets, IBANs, tokens or private payment details belong in GitHub Issues, source code, logs or frontend bundles. Real account configuration belongs in server-side secret storage/environment configuration.

## Local development

Backend requires Python 3.12+.

```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -e .
pytest
uvicorn app.main:app --reload
```

The API defaults to an environment-configured database URL. No fake production data is generated.
