# Payment model

ISHBounty keeps `DIRECT_BANK_TRANSFER` as the API-less live settlement path. In addition to IBAN, the beneficiary can use Enpara/BKM-style Kolay Adres destinations: phone number, e-mail address or T.C. identity number. QR is not required.

## Enpara-style Kolay Adres

Enpara documents Kolay Adres as a way to receive FAST transfers without sharing an IBAN, using a mapped phone number, e-mail address or T.C. identity number. The same account can have multiple different Kolay Adres mappings at the same time.

ISHBounty mirrors that user experience at the beneficiary-settings layer:

- `PHONE` — Turkish mobile number
- `EMAIL` — e-mail address
- `TCKN` — T.C. identity number
- `IBAN` — traditional bank destination

Full destination values are stored only in ISHV2UltraCore. The SQL database keeps only the destination type, masked value and fingerprint. The frontend never stores the API key or destination secrets.

## API-less live flow

1. A bounty reaches `MERGED`.
2. ISHBounty creates a `PAYMENT_PENDING` payment for the accepted solver.
3. The solver can maintain one active destination of each type, so phone + e-mail + TCKN can be enabled together, matching the Enpara settings pattern.
4. The authenticated payment-instruction endpoint resolves the selected destination and returns the exact value only to the authorized payment actor, together with amount, currency and payment reference.
5. The sponsor performs the real FAST/Havale transfer in their bank application using the displayed IBAN or Kolay Adres value.
6. The sponsor submits the bank's real transaction/reference number to `/api/bounties/{bounty_id}/payment/proof`. This produces `PROOF_SUBMITTED`; it never fabricates a transfer and never automatically marks the bounty paid.
7. An authorized verifier reconciles the real bank transaction and then calls the authenticated `/payment/paid` operation. Only then does the payment and bounty become `PAID`.

## Ödeme İste / Request-to-Pay boundary

Enpara's `Ödeme İste` is a BKM FAST-layer request-to-pay service. Enpara states that requests can be sent to IBAN, Kolay Adres or QR and then reach the payer through SMS or push notification. BKM states that e-commerce and face-to-face corporate use can be provided through a merchant-specific API, which requires the appropriate participant/merchant onboarding.

Therefore, activating Kolay Adres in the Enpara mobile app is enough for the API-less receiving flow, but it does **not** by itself give ISHBounty an API credential to create `Ödeme İste` requests. We keep that integration behind a future `PAYMENT_REQUEST_PROVIDER` adapter rather than scraping or automating the bank application.

## Security

Never put IBANs, T.C. identity numbers, phone numbers, e-mail addresses, banking credentials or transfer screenshots in GitHub issues, source code, logs or frontend bundles. The exact destination is returned only from an authenticated payment-instruction endpoint.

ISHBounty cannot execute a bank transfer without a bank-authorized payment channel. In API-less mode, the actual debit/credit occurs inside the bank's own application and ISHBounty only records and reconciles the result.

The payment layer remains an adapter boundary. If a licensed bank/payment provider is configured later, its durable transaction identifier and signed webhook can be used for automated reconciliation. Without such a provider, ISHBounty deliberately does not invent a transfer ID or claim that money moved.

Supported settlement currencies:

- TRY
- USD
- EUR

Before enabling platform-held funds, escrow, automated payouts, or platform commissions, obtain appropriate legal, tax and regulated-payment advice for the operating jurisdiction and use a properly licensed provider where required.
