---
id: kb_011
title: Duplicate or missing deposit
category: deposits
keywords: [deposit, duplicate, double, missing, not showing, charged twice]
updated: 2026-02-28
---

# Duplicate or missing deposit

## My deposit is missing from my balance

A deposit usually credits within seconds. If it is missing after 10 minutes,
check in this order:

1. **Card / e-wallet** — check your bank or wallet app. If the money left
   your account, the transaction has a reference ID. Open our
   Cashier → Transactions to see if it is marked `failed` (money returned)
   or `pending` (we are still processing).
2. **Crypto** — check the blockchain explorer for the transaction hash. A
   BTC deposit requires 1 confirmation (around 10 minutes average). USDT
   TRC-20 usually lands in under a minute. If the transaction is confirmed
   on-chain but not yet credited after 1 hour, contact support.
3. **Bank transfer** — up to 2 business days.

## My card was charged twice

True duplicates are extremely rare. What looks like a duplicate is usually
one of:

- **Pre-authorisation + capture** — a single deposit appears as two lines on
  your statement for a short time, then the pending line is removed within
  24–48 hours. Not a real charge.
- **Retried after timeout** — if the first attempt timed out but the second
  succeeded, and the first was later also captured, you were charged twice
  for the same session. This **is** a real duplicate and we refund it.

## What to do for a real duplicate

1. Wait 48 hours to rule out pre-auth.
2. If both charges are still present, contact support with:
   - Both transaction IDs from your bank statement
   - Screenshot of your statement showing both lines
3. We will refund the duplicate to the same card within 3 business days.

## Crypto deposit to the wrong network

If you sent USDT on ERC-20 to a TRC-20 address (or vice-versa), funds are
usually unrecoverable. We will open a support case but cannot guarantee
recovery — the right-network address is very important. Future: we plan to
add a network-aware QR that rejects wrong-network sends, but this is not yet
in production.

## Chargeback policy

Never initiate a chargeback for a deposit. Contact us first — we resolve
legitimate duplicates directly. Chargebacks lead to account closure and are
reported to ChargebackLink / Ethoca.
