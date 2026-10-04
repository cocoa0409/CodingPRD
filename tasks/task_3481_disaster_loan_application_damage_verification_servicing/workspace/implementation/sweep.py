"""The time-driven sweep (PRD 2.4), run in full on every clock set.

Order of concern: (1) declaration rollup, (2) servicing-action activation/expiry,
(3) delinquency aging per ACTIVE loan in ascending created_at order,
(4) default cascades (inline with the DEFAULT transition).
"""

from datetime import timedelta

import calc
import clock
from domain import bump
from store import all_rows, get
from timeutil import days_between


def run_sweep():
    now = clock.get_current()
    _declaration_rollup(now)
    _servicing_action_sweep(now)
    _aging_sweep(now)


def _declaration_rollup(now):
    for d in all_rows("declarations"):
        if now > d["economic_injury_filing_deadline"]:
            new_status = "FULLY_CLOSED"
        elif now > d["physical_filing_deadline"]:
            new_status = "PHYSICAL_CLOSED"
        else:
            new_status = "OPEN"
        # A jump past both deadlines moves OPEN -> FULLY_CLOSED directly (one transition).
        if new_status != d["status"]:
            d["status"] = new_status
            bump(d)


def _activate_action(action, loan):
    """APPROVED -> ACTIVE; flips servicing_status; DEFERMENT shifts next_due_date."""
    action["status"] = "ACTIVE"
    bump(action)
    loan["servicing_status"] = "DEFERRED" if action["action_type"] == "DEFERMENT" else "HARDSHIP"
    loan["days_past_due"] = 0
    if action["action_type"] == "DEFERMENT" and loan["next_due_date"] is not None:
        shift = (action["end_date"] - action["start_date"]).days
        loan["next_due_date"] = loan["next_due_date"] + timedelta(days=shift)
    bump(loan)


def _expire_action(action, loan):
    action["status"] = "EXPIRED"
    bump(action)
    loan["servicing_status"] = "CURRENT"
    bump(loan)


def _servicing_action_sweep(now):
    # Expiry first so an adjacent follow-on window can activate in the same sweep.
    for _ in range(2):
        for a in all_rows("servicing_actions"):
            if a["status"] == "ACTIVE" and now >= a["end_date"]:
                _expire_action(a, get("loans", a["loan_id"]))
        if _ == 0:
            for a in all_rows("servicing_actions"):
                if a["status"] == "APPROVED" and now >= a["start_date"]:
                    loan = get("loans", a["loan_id"])
                    if loan["servicing_status"] == "CURRENT":
                        _activate_action(a, loan)


def _default_cascades(loan):
    for r in all_rows("receivables"):
        if r["loan_id"] == loan["id"] and r["status"] in ("OPEN", "PARTIALLY_PAID"):
            r["status"] = "ESCALATED"
            bump(r)
    for a in all_rows("servicing_actions"):
        if a["loan_id"] == loan["id"] and a["status"] == "REQUESTED":
            a["status"] = "DENIED"
            bump(a)


def _aging_sweep(now):
    for loan in all_rows("loans"):
        if loan["lifecycle_status"] != "ACTIVE":
            continue
        transitions = 0
        changed = False
        if loan["servicing_status"] in ("DEFERRED", "HARDSHIP"):
            if loan["days_past_due"] != 0:
                loan["days_past_due"] = 0
                changed = True
        else:
            nd = loan["next_due_date"]
            if nd is None or now.date() <= nd.date():
                dpd = 0
            else:
                dpd = days_between(nd, now)
            if dpd != loan["days_past_due"]:
                loan["days_past_due"] = dpd
                changed = True
            if (dpd >= calc.LATE_FEE_GRACE_DAYS
                    and loan.get("_fee_marker") != nd):
                loan["late_fee_balance_cents"] += calc.late_fee_cents(loan["monthly_payment_cents"])
                loan["_fee_marker"] = nd
                changed = True
            # A single sweep applies the full cascade: fees first, then the
            # furthest applicable status rung (passing through DEFAULT fires its cascades).
            while True:
                if loan["servicing_status"] == "CURRENT" and dpd >= calc.DELINQUENT_AFTER_DAYS:
                    loan["servicing_status"] = "DELINQUENT"
                    transitions += 1
                elif loan["servicing_status"] == "DELINQUENT" and dpd >= calc.DEFAULT_AFTER_DAYS:
                    loan["servicing_status"] = "DEFAULT"
                    transitions += 1
                    _default_cascades(loan)
                elif (loan["servicing_status"] == "DEFAULT"
                      and dpd >= calc.CHARGE_OFF_AFTER_DAYS):
                    loan["lifecycle_status"] = "CHARGED_OFF"
                    transitions += 1
                else:
                    break
        if transitions:
            loan["version"] += transitions
            loan["updated_at"] = now
        elif changed:
            bump(loan)
