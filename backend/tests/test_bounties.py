from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def payload():
    return {"repository":"acme/project","issue_number":1,"title":"Fix hard bug","description":"Production issue","amount":1000,"currency":"TRY","sponsor_github":"acme"}

def test_create_claim_and_lifecycle():
    created = client.post('/api/bounties', json=payload()).json()
    bid = created['id']
    assert created['status'] == 'OPEN'
    claimed = client.post(f'/api/bounties/{bid}/claim', json={"solver_github":"dev"})
    assert claimed.status_code == 200
    assert claimed.json()['status'] == 'CLAIMED'
    for state in ['PR_SUBMITTED','CI_PASSED','MERGED']:
        r = client.post(f'/api/bounties/{bid}/transition', json={"status":state})
        assert r.status_code == 200
    payment = client.post(f'/api/bounties/{bid}/payment', json={"method":"DIRECT_BANK_TRANSFER"})
    assert payment.status_code == 201
    paid = client.post(f'/api/bounties/{bid}/payment/paid', json={"method":"DIRECT_BANK_TRANSFER","transfer_reference":"TRX-1"})
    assert paid.status_code == 200
    assert client.get(f'/api/bounties/{bid}').json()['status'] == 'PAID'

def test_invalid_transition_rejected():
    created = client.post('/api/bounties', json=payload()).json()
    r = client.post(f"/api/bounties/{created['id']}/transition", json={"status":"PAID"})
    assert r.status_code == 409
