"""Money cascades: tranche schedule, eligibility walk, clawback waterfall,
excess-funds receivable, disbursement release."""

from datetime import timedelta

import calc
import clock
from domain import (bump, loan_tranches, new_common, open_receivable,
                    verified_milestone_total)
from store import put
from timeutil import add_months, days_between


def create_tranche_schedule(loan):
    """Origination schedule: T1 = min(2500000, approved); remainder split
    T2 = floor(rem/2), T3 = rem - T2; zero-amount tranches are not created."""
    approved = loan["approved_amount_cents"]
    t1 = min(calc.INITIAL_DISBURSEMENT_CAP_CENTS, approved)
    if t1 > 0:
        _new_tranche(loan, 1, t1)
    rem = approved - t1
    if rem > 0:
        t2 = rem // 2
        t3 = rem - t2
        if t2 > 0:
            _new_tranche(loan, 2, t2)
        if t3 > 0:
            _new_tranche(loan, 3, t3)


def _new_tranche(loan, stage_number, amount_cents):
    row = new_common()
    row.update({
        "loan_id": loan["id"],
        "stage_number": stage_number,
        "amount_cents": amount_cents,
        "status": "SCHEDULED",
        "released_at": None,
    })
    return put("tranches", row)


def append_tranche(loan, amount_cents):
    stages = [t["stage_number"] for t in loan_tranches(loan["id"])]
    return _new_tranche(loan, (max(stages) if stages else 0) + 1, amount_cents)


def reevaluate_eligibility(loan):
    """disbursement_waterfall_calc: stage 1 eligible iff loan ACTIVE; stage i>1
    eligible iff every earlier stage is RELEASED and cumulative VERIFIED milestone
    cost >= sum of earlier stages' amounts (equality suffices)."""
    tranches = loan_tranches(loan["id"])
    verified_total = verified_milestone_total(loan["id"])
    for t in tranches:
        if t["status"] != "SCHEDULED":
            continue
        if t["stage_number"] == 1:
            if loan["lifecycle_status"] == "ACTIVE":
                t["status"] = "ELIGIBLE"
                bump(t)
            continue
        priors = [p for p in tranches if p["stage_number"] < t["stage_number"]]
        if (all(p["status"] == "RELEASED" for p in priors)
                and verified_total >= sum(p["amount_cents"] for p in priors)):
            t["status"] = "ELIGIBLE"
            bump(t)


def clawback_waterfall(loan, target):
    """Walk un-released tranches in DESCENDING stage order: cancel whole tranches
    while sum(un-released) - tranche.amount stays >= target, else reduce the
    current tranche so the sum lands exactly on target."""
    unreleased = [t for t in loan_tranches(loan["id"]) if t["status"] in ("SCHEDULED", "ELIGIBLE")]
    unreleased.sort(key=lambda t: t["stage_number"], reverse=True)
    total = sum(t["amount_cents"] for t in unreleased)
    for t in unreleased:
        if total <= target:
            break
        if total - t["amount_cents"] >= target:
            total -= t["amount_cents"]
            t["status"] = "CANCELLED"
            bump(t)
        else:
            t["amount_cents"] -= (total - target)
            bump(t)
            break


def add_excess_receivable(loan, amount_cents):
    """Top up the loan's OPEN/PARTIALLY_PAID receivable, else create one
    (due_date = created_at + 30 days on creation)."""
    r = open_receivable(loan["id"])
    if r is not None:
        r["amount_due_cents"] += amount_cents
        bump(r)
        return r
    now = clock.get_current()
    row = new_common()
    row.update({
        "loan_id": loan["id"],
        "amount_due_cents": amount_cents,
        "amount_paid_cents": 0,
        "due_date": now + timedelta(days=calc.EXCESS_FUNDS_DUE_DAYS),
        "status": "OPEN",
    })
    return put("receivables", row)


def release_tranche(loan, tranche):
    """Release side effects (PRD 3.7): stamp, accrue, move money, re-evaluate."""
    now = clock.get_current()
    if loan["last_accrual_date"] is None:
        loan["last_accrual_date"] = now
        loan["next_due_date"] = add_months(now, loan["deferral_months"] + 1)
    else:
        days = max(0, days_between(loan["last_accrual_date"], now))
        rate = calc.rate_and_term_for_loan(loan)
        loan["accrued_interest_balance_cents"] += calc.daily_interest_cents(
            loan["outstanding_balance_cents"], rate, days)
        loan["last_accrual_date"] = now
    loan["disbursed_total_cents"] += tranche["amount_cents"]
    loan["outstanding_balance_cents"] += tranche["amount_cents"]
    bump(loan)
    tranche["released_at"] = now
    tranche["status"] = "RELEASED"
    bump(tranche)
    reevaluate_eligibility(loan)
