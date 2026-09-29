"""The two statutory interest measures (PRD 2.7).

Both draw on the same input set: charges of the case whose status is OPEN and
whose due_date is at or before the as-of date.  VOID and SATISFIED charges are
excluded entirely and retroactively.  Annual 6 percent becomes a monthly rate of
exactly 0.005; the grace period is zero days.
"""
from decimal import Decimal

import db
import util

MONTHLY_RATE = Decimal("0.005")


def input_set(case_id, as_of):
    rows = [c for c in db.case_charges(case_id)
            if c["status"] == "OPEN" and c["due_date"] <= as_of]
    return sorted(rows, key=lambda c: (c["due_date"], c["created_at"], c["_seq"]))


def charge_statutory_interest(charge, as_of):
    """Per-charge measure: whole calendar months since the charge's due_date."""
    months = util.whole_months_between(charge["due_date"], as_of)
    if months <= 0:
        return 0
    balance = charge["unpaid_balance_cents"]
    return util.mul_round_half_up(balance, MONTHLY_RATE * months)


def statutory_total(case_id, as_of):
    """Certification measure — the per-charge walk (PRD 2.7)."""
    total = 0
    for charge in input_set(case_id, as_of):
        total += charge_statutory_interest(charge, as_of)
    return total


def aggregate_total(case_id, as_of):
    """Settlement measure — the aggregate month-end snapshot walk (PRD 2.7)."""
    charges = input_set(case_id, as_of)
    if not charges:
        return 0
    earliest = min(c["due_date"] for c in charges)
    total = 0
    for snapshot in util.month_ends_before(as_of, earliest):
        pool = sum(c["unpaid_balance_cents"] for c in charges
                   if c["due_date"] <= snapshot)
        if pool == 0:
            continue
        total += util.mul_round_half_up(pool, MONTHLY_RATE)
    return total


def arrears_principal(case_id, as_of=None):
    """Unpaid principal on OPEN charges already due (PRD 3.1)."""
    if as_of is None:
        as_of = db.now().date()
    return sum(c["unpaid_balance_cents"] for c in db.case_charges(case_id)
               if c["status"] == "OPEN" and c["due_date"] <= as_of)


def interest_receivable(case, as_of=None):
    """Aggregate total less what was written off and what was collected."""
    if as_of is None:
        as_of = db.now().date()
    gross = aggregate_total(case["id"], as_of)
    net = gross - case["interest_written_off_cents"] - case["interest_collected_cents"]
    return max(0, net)


def certified_arrears(case, as_of=None):
    """Principal plus per-charge statutory interest (PRD 2.7 certified figures)."""
    if as_of is None:
        as_of = db.now().date()
    return arrears_principal(case["id"], as_of) + statutory_total(case["id"], as_of)


def total_arrears_certified(participant_id, as_of=None):
    """Summed over the participant's non-CLOSED cases as obligor (PRD 2.7)."""
    if as_of is None:
        as_of = db.now().date()
    total = 0
    for case in db.obligor_cases(participant_id):
        if case["case_status"] == "CLOSED":
            continue
        total += certified_arrears(case, as_of)
    return total
