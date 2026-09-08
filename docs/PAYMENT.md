# Payment model

ISHBounty MVP uses `DIRECT_BANK_TRANSFER`.

The sponsor pays the accepted developer directly. ISHBounty records the payment state and transfer reference but does not receive, pool, escrow, or forward bounty funds.

Supported settlement currencies in the domain model:

- TRY
- USD
- EUR

Real bank account details must be stored only in protected server-side configuration/secret storage. Never place IBANs, credentials or transfer screenshots in source control, public issues, logs or frontend assets.

The payment layer is intentionally an adapter boundary so a licensed payment provider can be added later without changing the bounty state machine.

Before enabling platform-held funds, automated payouts, or platform commissions, obtain appropriate legal, tax and regulated-payment advice for the operating jurisdiction and use a properly licensed provider where required.
