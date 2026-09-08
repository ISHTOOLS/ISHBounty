# Bounty lifecycle

```text
OPEN
  ↓
CLAIMED
  ↓
PR_SUBMITTED
  ↓
CI_PASSED
  ↓
MERGED
  ↓
PAYMENT_PENDING
  ↓
PAID
```

Exceptional states are `CANCELLED` and `DISPUTED`.

The backend rejects transitions not explicitly allowed by the state machine. A merge is a prerequisite for payment creation. Payment completion records a transfer reference and moves the bounty to `PAID`.

GitHub remains the source of truth for repository, issue and pull-request activity. The ISHBounty database is the system of record for bounty metadata, lifecycle state and payment records.
