"""Creditor remittance ledger (PRD §2.9).

Pinned evaluation order for every collection event (offset application,
garnishment/agency collect, reverse-offset confirmation):
  1. Lazy calendar-year reset against the logical clock.
  2. Read the pre-event gross YTD figure.
  3. Fee tier: 3% below REMIT_TIER_THRESHOLD_CENTS, 2% at or above; the current
     event never counts toward its own tier.
  4. fee = round_half_up(gross * pct); net = gross - fee.
  5. Only then are the counters credited.

Unwinding: payment reversal decrements both counters by the original amounts;
refund clawbacks decrement the net ledger only.
"""
from constants import (
    REMIT_FEE_PCT_HIGH_BAND,
    REMIT_FEE_PCT_LOW_BAND,
    REMIT_TIER_THRESHOLD_CENTS,
)
from db import clock_now, touch
from util import pct_of_cents


def assess_remittance(creditor, gross_cents):
    """Assess the remittance fee for a collection event and credit the ledger.
    Returns (fee_cents, net_cents)."""
    now = clock_now()
    # Step 1: lazy year reset.
    if creditor["remitted_ytd_year"] != now.year:
        creditor["remitted_gross_ytd_cents"] = 0
        creditor["remitted_ytd_year"] = now.year
    # Steps 2-3: pre-event gross decides the tier; this event never counts.
    pre_event_gross = creditor["remitted_gross_ytd_cents"]
    pct = (
        REMIT_FEE_PCT_LOW_BAND
        if pre_event_gross < REMIT_TIER_THRESHOLD_CENTS
        else REMIT_FEE_PCT_HIGH_BAND
    )
    # Step 4.
    fee_cents = pct_of_cents(gross_cents, pct)
    net_cents = gross_cents - fee_cents
    # Step 5: counters credited only after the fee is fixed.
    creditor["remitted_gross_ytd_cents"] += gross_cents
    creditor["remitted_net_total_cents"] += net_cents
    touch(creditor)
    return fee_cents, net_cents


def debit_reversal(creditor, gross_cents, net_cents):
    """Payment-reversal unwind: symmetric debit of both counters (PRD §2.9)."""
    creditor["remitted_gross_ytd_cents"] -= gross_cents
    creditor["remitted_net_total_cents"] -= net_cents
    touch(creditor)


def debit_clawback(creditor, clawback_cents):
    """Refund clawback: net ledger only; the gross YTD figure is untouched."""
    creditor["remitted_net_total_cents"] -= clawback_cents
    touch(creditor)
