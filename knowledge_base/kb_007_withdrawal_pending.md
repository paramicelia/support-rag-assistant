---
id: kb_007
title: Why is my withdrawal still pending
category: withdrawals
keywords: [withdrawal, pending, processing, delayed, how long, stuck]
updated: 2026-03-18
---

# Why is my withdrawal still pending

A `pending` status means we have received your withdrawal request but it has
not yet been released to the payment provider. This is normal for the first
few hours.

## Normal timelines by method

- **E-wallets (Skrill, Neteller, crypto)** — released within 24h, often
  within 1–2 hours
- **Cards (Visa / Mastercard)** — released within 24h, then 1–3 business days
  at the issuing bank
- **SEPA bank transfer** — released within 24h, then 1–2 business days at the
  receiving bank

## When to worry

Contact support **only** if:

- E-wallet withdrawal has been `pending` for **more than 48 hours**
- Card or SEPA withdrawal has been `pending` for **more than 72 hours**
  (this excludes the time the money is in transit at your bank)
- The status changed to `on_hold` — this always means we need something from
  you and an email was sent

## Common reasons a withdrawal gets held

1. **KYC not complete** — we ask for verification at this step, not before
2. **Active bonus** — wagering not met; you either complete it or forfeit
3. **Deposit not fully settled** — cards have a chargeback window; we wait
   until the deposit is settled before releasing a matching withdrawal
4. **Triggered AML check** — for large amounts, first withdrawals, or after a
   suspicious activity flag. EDD may kick in — see `kb_003`
5. **Mismatch between deposit and withdrawal method** — see `kb_005`

## How to check the detailed reason

The withdrawal page shows the current step (`queued`, `compliance_review`,
`processing`, `sent`). If you see `compliance_review` for more than 24h you
will receive an email with the specific action required.

## Can you cancel a pending withdrawal?

Yes, until the status is `processing`. Go to Cashier → Transactions and click
**Cancel**. Be aware: cancelling a withdrawal returns the money to your
playable balance, which some players regret later.
