"""Logical clock service and the automatic sweeps (PRD §2.11, §3.9).

Setting the clock to an absolute instant moves it without running the sweeps
for the interval skipped. Advancing it to a later instant additionally runs
every automatic sweep that has come due:

  1. ACCEPTED assignments past accepted_at + time_limit_minutes  -> EXPIRED
  2. SUBMITTED assignments past review_expires_at               -> APPROVED
  3. HELD_FOR_VETTING payouts past hold_until_at, verified       -> PAID
  4. HITs whose completion gate now holds                        -> COMPLETED
"""

from apptime import now_dt, parse
from config import clock
from db import db
from errors import fail
from services import hit_service
from services.assignment_service import auto_approve_due, sweep_assignments_due
from services.payout_service import settle_due_payouts


def set_current_utc(value: str) -> None:
    """Move the clock to an absolute instant; no sweeps are run."""
    clock.set(value)


def advance_to(target: str) -> None:
    """Advance the clock and run every sweep due at or before the target."""
    if parse(target) < now_dt():
        fail("ERR_INVALID_REQUEST", "target_utc must not precede the current logical instant.")
    clock.set(target)
    run_sweeps()


def run_sweeps() -> None:
    sweep_assignments_due()
    auto_approve_due()
    settle_due_payouts()
    bubble_up_hits()


def bubble_up_hits() -> None:
    """Complete every HIT whose gate now holds.

    Run to a fixed point: completing one HIT re-derives its requester's ledger,
    which is independent per HIT, so a single pass suffices - but a second pass
    is cheap and guards against any ordering surprise.
    """
    for _ in range(2):
        changed = False
        for hire in list(db.hits.values()):
            if hire["status"] in {"COMPLETED", "CANCELLED"}:
                continue
            if hit_service.complete_hit(hire):
                changed = True
        if not changed:
            break