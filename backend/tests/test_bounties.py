from fastapi.testclient import TestClient
from app.main import app
from app.db import Base, engine

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


def test_create_claim_and_lifecycle():
    reset_db()
    created = client.post('/api/bounties', json=payload()).json()
    bid = created['id']
    assert created['status'] == 'OPEN'
    claimed = client.post(f'/api/bounties/{bid}/claim', json={"solver_github": "dev"})
    assert claimed.status_code == 200
    assert claimed.json()['status'] == 'CLAIMED'
    for state in ['PR_SUBMITTED', 'CI_PASSED', 'MERGED']:
        r = client.post(f'/api/bounties/{bid}/transition', json={"status": state})
        assert r.status_code == 200
    payment = client.post(f'/api/bounties/{bid}/payment', json={"method": "DIRECT_BANK_TRANSFER"})
    assert payment.status_code == 201
    paid = client.post(
        f'/api/bounties/{bid}/payment/paid',
        json={"method": "DIRECT_BANK_TRANSFER", "transfer_reference": "TRX-1"},
    )
    assert paid.status_code == 200
    assert client.get(f'/api/bounties/{bid}').json()['status'] == 'PAID'


def test_invalid_transition_rejected():
    reset_db()
    created = client.post('/api/bounties', json=payload(issue_number=2)).json()
    r = client.post(f"/api/bounties/{created['id']}/transition", json={"status": "PAID"})
    assert r.status_code == 409


def test_duplicate_repository_issue_rejected():
    reset_db()
    first = client.post('/api/bounties', json=payload(issue_number=7))
    assert first.status_code == 201
    duplicate = client.post('/api/bounties', json=payload(issue_number=7))
    assert duplicate.status_code == 409


def test_webhook_pr_check_and_merge_lifecycle():
    reset_db()
    created = client.post('/api/bounties', json=payload(issue_number=42, repository="owner/repo")).json()
    bid = created['id']
    client.post(f'/api/bounties/{bid}/claim', json={"solver_github": "dev"})

    pr_payload = {
        "action": "opened",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"number": 99, "title": "Fix issue", "body": "Fixes #42"},
    }
    r = client.post('/api/github/webhook', headers={"X-GitHub-Event": "pull_request"}, json=pr_payload)
    assert r.status_code == 200
    assert client.get(f'/api/bounties/{bid}').json()['status'] == 'PR_SUBMITTED'

    check_payload = {
        "action": "completed",
        "repository": {"full_name": "owner/repo"},
        "check_run": {"conclusion": "success", "pull_requests": [{"number": 99}]},
    }
    r = client.post('/api/github/webhook', headers={"X-GitHub-Event": "check_run"}, json=check_payload)
    assert r.status_code == 200
    assert client.get(f'/api/bounties/{bid}').json()['status'] == 'CI_PASSED'

    merge_payload = {
        "action": "closed",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"number": 99, "title": "Fix issue", "body": "Fixes #42", "merged": True},
    }
    r = client.post('/api/github/webhook', headers={"X-GitHub-Event": "pull_request"}, json=merge_payload)
    assert r.status_code == 200
    assert client.get(f'/api/bounties/{bid}').json()['status'] == 'MERGED'


def test_webhook_invalid_signature_rejected():
    reset_db()
    import os
    os.environ['GITHUB_WEBHOOK_SECRET'] = 'test-secret'
    from app.core.config import get_settings
    get_settings.cache_clear()
    try:
        r = client.post(
            '/api/github/webhook',
            headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": "sha256=bad"},
            json={"zen": "test"},
        )
        assert r.status_code == 401
    finally:
        os.environ.pop('GITHUB_WEBHOOK_SECRET', None)
        get_settings.cache_clear()
