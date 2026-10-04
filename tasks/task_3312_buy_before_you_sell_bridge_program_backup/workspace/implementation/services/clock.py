"""The logical clock (PRD 2.7, PRD 3.11).

The system never consults wall-clock time.  It reads a logical clock that starts
at exactly ``2026-09-01T00:00:00Z`` when the server boots and that only moves
when a coordinator advances it.  Every rule expressed as a date comparison is
evaluated against that clock.

Advancing the clock is itself a state-changing event: it can push a
qualification into ``EXPIRED``, an offer into ``EXPIRED`` and a loan into
``DELINQUENT`` without any client having touched those resources, so the server
re-evaluates every clock-gated expiry after the clock moves.  A clock-driven
state transition is a mutation in its own right and advances the affected
resource's ``version``, which is why each expiry below calls ``touch``.
"""

from constants import QUALIFICATION_EXPIRY_DAYS
from services import current_time, touch
from services import loan as loan_service
from store import db
from timeutil import add_days, format_iso, parse_iso

PENDING = "PENDING"
APPROVED = "APPROVED"
EXPIRED = "EXPIRED"


def advance(to_instant_text):
    """Advance the logical clock and re-evaluate every dependent rule."""
    instant = parse_iso(to_instant_text)
    db.logical_clock = instant

    expire_qualifications()
    expire_backup_offers()
    mark_delinquent_loans()
    refresh_all_accruals()

    return format_iso(instant)


def expire_qualifications():
    """Expire the two 90-day windows of PRD 3.2.

    * a qualification left ``PENDING`` for ninety days past its creation
      expires;
    * an ``APPROVED`` qualification that has sat for ninety days past its
      approval without any bridge program ever referencing it expires.
    """
    now = current_time()
    for qualification in db.all("qualifications"):
        status = qualification.get("status")
        if status == PENDING:
            created = parse_iso(qualification.get("created_at"))
            if created is not None and now >= add_days(created, QUALIFICATION_EXPIRY_DAYS):
                qualification["status"] = EXPIRED
                touch(qualification)
        elif status == APPROVED:
            approved_at = parse_iso(qualification.get("approved_at"))
            if approved_at is None:
                continue
            referencing = db.by_field("bridge_programs", "qualification_id", qualification["id"])
            if referencing:
                continue
            if now >= add_days(approved_at, QUALIFICATION_EXPIRY_DAYS):
                qualification["status"] = EXPIRED
                touch(qualification)


def expire_backup_offers():
    """Expire an offer once the clock passes its ``expires_at`` (PRD 3.6)."""
    now = current_time()
    for offer in db.all("backup_offers"):
        if offer.get("status") not in ("ISSUED", "EXTENDED"):
            continue
        expires_at = parse_iso(offer.get("expires_at"))
        if expires_at is None:
            continue
        if now > expires_at:
            offer["status"] = EXPIRED
            touch(offer)


def mark_delinquent_loans():
    """A ``DRAWN`` loan falls delinquent past its earliest unpaid cost (PRD 3.5).

    The clock must have passed the due date of the loan's earliest unpaid
    carrying cost *and* the loan must have accrued interest to date.
    """
    now = current_time()
    for interim_loan in db.all("interim_loans"):
        if interim_loan.get("status") != "DRAWN":
            continue
        program = db.get("bridge_programs", interim_loan.get("bridge_program_id"))
        if program is None:
            continue
        earliest = loan_service.earliest_unpaid_due_date(program)
        if earliest is None:
            continue
        due = parse_iso(earliest)
        if due is None or now <= due:
            continue
        if int(interim_loan.get("accrued_interest_cents") or 0) > 0:
            interim_loan["status"] = "DELINQUENT"
            touch(interim_loan)


def refresh_all_accruals():
    """Bring every loan's accrual forward to the new instant (PRD 3.11)."""
    for interim_loan in db.all("interim_loans"):
        loan_service.recompute(interim_loan)


def current_text():
    return format_iso(db.logical_clock)