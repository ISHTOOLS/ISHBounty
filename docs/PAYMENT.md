# Payment model

ISHBounty uses `DIRECT_BANK_TRANSFER` as the API-less IBAN payment path. The QR flow is not used.

## API-less live flow

1. A bounty reaches `MERGED`.
2. ISHBounty creates a `PAYMENT_PENDING` payment for the accepted solver.
3. The beneficiary's verified payment account is resolved from protected ISHV2UltraCore storage.
4. The authenticated payment-instruction endpoint returns the bank name, destination IBAN, amount, currency and an internal payment reference for the sponsor to enter in their banking application.
5. The sponsor performs the real bank transfer manually through their bank (for example, their normal mobile/internet banking channel). No banking API or QR integration is required.
6. The sponsor submits the bank's real transaction/reference number to `/api/bounties/{bounty_id}/payment/proof`. This changes the payment to `PROOF_SUBMITTED`; it does not fabricate a transfer or mark the bounty paid.
7. An authorized verifier reconciles the real bank transaction and then calls the authenticated `/payment/paid` operation, which changes the payment and bounty to `PAID`.

ISHBounty cannot execute a transfer from a bank account without a bank-authorized payment channel. In API-less mode, the actual debit/credit occurs in the bank's own application and the platform only records and reconciles the result.

## Security

Full bank account details are stored only in protected server-side secret storage. Never place IBANs, credentials or transfer screenshots in source control, public issues, logs or frontend assets. The payment-instruction endpoint is authenticated and should only be exposed to the authorized sponsor/payment operator.

The payment layer remains an adapter boundary. If a licensed payment provider is configured later, its durable transfer identifier and signed webhook can be used for automated reconciliation. Without such a provider, ISHBounty deliberately does not invent a transfer ID or claim that money moved.

Supported settlement currencies:

- TRY
- USD
- EUR

Before enabling platform-held funds, escrow, automated payouts, or platform commissions, obtain appropriate legal, tax and regulated-payment advice for the operating jurisdiction and use a properly licensed provider where required.
