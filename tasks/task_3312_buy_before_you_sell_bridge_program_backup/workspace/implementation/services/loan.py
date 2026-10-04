"""Interim loan: origination, balances and chronological interest accrual.

PRD 3.5 states the accrual rule and it is worth restating precisely, because it
is the only place in the system where the *order* of events changes the number:

* the loan's disbursed advances are ordered by ``advanced_at`` ascending,
  breaking ties by creation time ascending, and the accrual walks that order
  carrying a running principal;
* for each event, interest is added equal to the running principal multiplied
  by ``interest_rate_bps``, multiplied by ``INTERIM_DAY_COUNT_BPS`` (3000), and
  divided by the product of ten thousand and ten thousand, flooring;
* the running principal is then increased by the event's ``amount_cents``;
* one final accrual is added after the last event using the fully accumulated
  running principal, and then all repayments applied to interest are
  subtracted;
* a negative result is raised to zero.

Only advances in ``DISBURSED`` status participate, so the accrual is recomputed
whenever an advance's status changes.  Accruals normally run through the current
logical clock; once a settlement entry of kind ``CLOSING_SALE`` has been applied,
accrual stops at that entry's creation time instead of continuing to today, which
is realised here by excluding events disbursed after that instant.
"""

from constants import INTERIM_DAY_COUNT_BPS, BPS_DENOMINATOR
from services import current_time, create, public, touch
from store import db

DISBURSED = "DISBURSED"
CLOSING_SALE = "CLOSING_SALE"


def originate(bridge_program_id, principal_cents, interest_rate_bps):
    """Create an ``ORIGINATED`` interim loan for a program."""
    loan = {
        "bridge_program_id": bridge_program_id,
        "principal_cents": principal_cents,
        "interest_rate_bps": interest_rate_bps,
        "drawn_cents": 0,
        "outstanding_principal_cents": 0,
        "accrued_interest_cents": 0,
        "status": "ORIGINATED",
        "originated_at": None,
        # internal bookkeeping (stripped from responses)
        "_repaid_principal_cents": 0,
        "_repaid_interest_cents": 0,
        "_reopened_for_repair_id": None,
    }
    create("interim_loans", loan)
    return loan


def mark_originated_at(loan, instant_text):
    """Stamp the logical-clock origination instant (already ISO-formatted)."""
    loan["originated_at"] = instant_text
    return loan


def disbursed_advances(loan):
    """All advances for this loan that participated in a draw, in walk order."""
    rows = [
        a for a in db.all("bridge_advances")
        if a.get("interim_loan_id") == loan["id"] and a.get("status") == DISBURSED
    ]
    return db.advance_by_created(rows)


def _accrual_stop_text(loan):
    """The instant accrual stops at: the first applied CLOSING_SALE entry."""
    entries = [
        d for d in db.all("disbursements")
        if d.get("bridge_program_id") == loan.get("bridge_program_id")
        and d.get("source_kind") == CLOSING_SALE
        and d.get("status") == "APPLIED"
    ]
    if not entries:
        return None
    entries.sort(key=lambda d: (d.get("created_at") or "", d.get("_seq", 0)))
    return entries[0].get("created_at")


def alone_event_after(event, stop_text):
    """True when an event falls outside the accrual window that stops at a time."""
    return (event.get("at") or "") > stop_text


def compute_accrued_interest(loan):
    """The ``interior_loan_interest_accrual`` calculation of PRD 3.5."""
    rate = int(loan.get("interest_rate_bps") or 0)
    if rate == 0:
        base = 0
    else:
        stop_text = _accrual_stop_text(loan)
        events = draw_events(loan)
        running_principal = 0
        accrued = 0
        for event in events:
            if stop_text is not None and alone_event_after(event, stop_text):
                continue
            accrued += (running_principal * rate * INTERIM_DAY_COUNT_BPS) // (BPS_DENOMINATOR * BPS_DENOMINATOR)
            running_principal += event["amount_cents"]
        accrued += (running_principal * rate * INTERIM_DAY_COUNT_BPS) // (BPS_DENOMINATOR * BPS_DENOMINATOR)
        base = accrued
    base -= int(loan.get("_repaid_interest_cents") or 0)
    return max(base, 0)


def compute_outstanding_principal(loan):
    drawn = int(loan.get("drawn_cents") or 0)
    repaid = int(loan.get("_repaid_principal_cents") or 0)
    return max(drawn - repaid, 0)


def recompute(loan):
    """Re-derive drawn, outstanding principal and accrued interest.

    ``drawn_cents`` counts every advance that has ever participated in a draw,
    not merely the ones still outstanding: PRD 3.4 raises it when an advance is
    disbursed, and a later settlement retiring that advance to ``REPAID``
    (PRD 3.9) repays the money rather than undrawing it -- the repayment is
    recorded in ``_repaid_principal_cents``, which is what reduces the
    outstanding balance.  The accrual walk is stricter and still sees only
    ``DISBURSED`` advances (PRD 3.5).

    This is a derivation, not a client-visible mutation, so it does not bump the
    loan's version; callers that change the loan's state call ``touch``.
    """
    drawn = sum(event["amount_cents"] for event in drawn_events(loan))
    loan["drawn_cents"] = drawn
    loan["outstanding_principal_cents"] = compute_outstanding_principal(loan)
    loan["accrued_interest_cents"] = compute_accrued_interest(loan)
    return loan


def recompute_and_touch(loan):
    recompute(loan)
    touch(loan)
    return loan


def combined_balance(loan):
    return int(loan.get("outstanding_principal_cents") or 0) + int(
        loan.get("accrued_interest_cents") or 0
    )


def apply_principal_payment(loan, amount_cents):
    """Apply a partial payment: it reduces principal (PRD 3.5)."""
    loan["_repaid_principal_cents"] = int(loan.get("_repaid_principal_cents") or 0) + amount_cents
    return loan


def apply_final_payment(loan):
    """Zero both principal and interest, as a final repayment does."""
    loan["_repaid_principal_cents"] = int(loan.get("drawn_cents") or 0)
    loan["_repaid_interest_cents"] = max(
        int(loan.get("_repaid_interest_cents") or 0) + int(loan.get("accrued_interest_cents") or 0),
        int(loan.get("_repaid_interest_cents") or 0),
    )
    return loan


def earliest_unpaid_due_date(program):
    """The due date of the program's earliest unpaid carrying cost."""
    due_dates = [
        c.get("due_date") for c in db.all("carrying_costs")
        if c.get("bridge_program_id") == program["id"] and c.get("repayment_status") == "UNPAID"
    ]
    due_dates = [d for d in due_dates if d]
    if not due_dates:
        return None
    return min(due_dates)


def draw_events(loan):
    """Every event that raises the loan's drawn balance, in walk order.

    A bridge advance draws when it is ``DISBURSED``.  A repair advance is a
    separate resource with its own lifecycle, and PRD 3.4 states plainly that
    disbursing approved repair funds "raises the loan's ``drawn_cents`` and
    ``outstanding_principal_cents``" -- so it participates in the same accrual
    walk.  PENDING and REJECTED advances are excluded entirely.
    """
    events = []
    for advance in db.all("bridge_advances"):
        if advance.get("interim_loan_id") == loan["id"] and advance.get("status") == DISBURSED:
            events.append({"amount_cents": int(advance.get("amount_cents") or 0),
                           "at": advance.get("advanced_at") or "",
                           "created_at": advance.get("created_at") or "",
                           "_seq": advance.get("_seq", 0)})
    program_id = loan.get("bridge_program_id")
    for repair in db.all("repair_advances"):
        if repair.get("bridge_program_id") == program_id and repair.get("status") == "DISBURSED":
            events.append({"amount_cents": int(repair.get("approved_amount_cents") or 0),
                           "at": repair.get("disbursed_at") or "",
                           "created_at": repair.get("created_at") or "",
                           "_seq": repair.get("_seq", 0)})
    events.sort(key=lambda e: (e["at"], e["created_at"], e["_seq"]))
    return events


def drawn_events(loan):
    """Every advance that has ever participated in a draw (PRD 3.4).

    This is the accumulation the PRD describes for ``drawn_cents``: disbursing
    raises it, and a settlement retiring the advance to ``REPAID`` repays rather
    than undraws it.  An advance the client rejected, or one still ``PENDING``,
    never drew and contributes nothing -- so an unmatched draw is directly
    observable on ``drawn_cents``.
    """
    events = []
    for advance in db.all("bridge_advances"):
        if advance.get("interim_loan_id") != loan["id"]:
            continue
        if advance.get("status") not in (DISBURSED, "REPAID"):
            continue
        events.append({"amount_cents": int(advance.get("amount_cents") or 0),
                       "at": advance.get("advanced_at") or "",
                       "created_at": advance.get("created_at") or "",
                       "_seq": advance.get("_seq", 0)})
    program_id = loan.get("bridge_program_id")
    for repair in db.all("repair_advances"):
        if repair.get("bridge_program_id") != program_id:
            continue
        if repair.get("status") not in ("DISBURSED", "SETTLED"):
            continue
        events.append({"amount_cents": int(repair.get("approved_amount_cents") or 0),
                       "at": repair.get("disbursed_at") or "",
                       "created_at": repair.get("created_at") or "",
                       "_seq": repair.get("_seq", 0)})
    events.sort(key=lambda e: (e["at"], e["created_at"], e["_seq"]))
    return events


def serialize(loan):
    return public(loan)