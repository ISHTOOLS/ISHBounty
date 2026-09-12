# Payment model

ISHBounty uses `DIRECT_BANK_TRANSFER` as the API-less settlement path. The QR flow is not required.

## Enpara KOLAS / API-less live flow

Enpara's KOLAS (Kolay Adres) can receive TRY transfers without exposing an IBAN. Enpara documents phone number, e-mail address and T.C. identity number as supported Kolay Adres values, and says these values can be linked to a Vadesiz TL account. Enpara also provides `Ödeme İste`, a BKM messaging and transfer flow for requesting FAST/havale payments from participating institutions.

ISHBounty integrates the part that can be performed without a bank API:

1. A bounty reaches `MERGED`.
2. ISHBounty creates a `PAYMENT_PENDING` payment for the accepted solver.
3. The beneficiary's verified payment destination is resolved from protected ISHV2UltraCore storage.
4. The authenticated payment-instruction endpoint returns the destination type (`IBAN`, `PHONE`, `EMAIL`, or `TCKN`), destination value, amount, currency and an internal payment reference.
5. For an Enpara KOLAS destination, the sponsor opens their own bank application and sends the required TRY FAST transfer to the beneficiary's registered phone, e-mail or T.C. identity number. No banking API, QR payload or fabricated transfer ID is used by ISHBounty.
6. The sponsor submits the bank's real transaction/reference number to `/api/bounties/{bounty_id}/payment/proof`. This changes the payment to `PROOF_SUBMITTED`; it does not fabricate a transfer or mark the bounty paid.
7. An authorized verifier reconciles the real bank transaction and then calls the authenticated `/payment/paid` operation, which changes the payment and bounty to `PAID`.

### Enpara `Ödeme İste`

Enpara documents `Ödeme İste` as a BKM messaging and transfer infrastructure. It can request payment using IBAN, KOLAS or QR, but the request itself is created and managed inside the Enpara banking application. This repository does not pretend to call Enpara's private mobile banking interface. If Enpara later provides an authorized merchant/API channel for payment requests, it can be added as a provider adapter without changing the bounty/payment state machine.

## Security

Full IBAN/KOLAS destination values are stored only in protected ISHV2UltraCore storage. SQL metadata contains only the destination type, fingerprint and masked value. Never place IBANs, T.C. identity numbers, phone numbers, credentials or transfer screenshots in source control, public issues, logs or frontend assets. The payment-instruction endpoint is authenticated and should only be exposed to the authorized sponsor/payment operator.

KOLAS destinations are limited to TRY because Enpara documents KOLAS as a Vadesiz TL account transfer mechanism. USD/EUR settlement continues to use an IBAN destination unless a licensed provider supplies another supported route.

The payment layer remains an adapter boundary. If a licensed payment provider is configured later, its durable transfer identifier and signed webhook can be used for automated reconciliation. Without such a provider, ISHBounty deliberately does not invent a transfer ID or claim that money moved.

Supported settlement currencies:

- TRY
- USD
- EUR

Before enabling platform-held funds, escrow, automated payouts, or platform commissions, obtain appropriate legal, tax and regulated-payment advice for the operating jurisdiction and use a properly licensed provider where required.
