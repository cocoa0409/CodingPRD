"""HIT lifecycle service: the pinned funds calculation, completion bubble-up and
requester-side ledger helpers.

Calculation `hit_funds_required` (SCAFFOLD §1.3) — evaluation order is PINNED,
left to right: the gross pool selects the commission rate; the commission is
rounded half-up; the resulting INTERMEDIATE pre-fee sum (not the gross pool)
selects the per-assignment fee tier.
"""

from decimal import Decimal

from config import (
    COMMISSION_RATE_HIGH,
    COMMISSION_RATE_LOW,
    COMMISSION_RATE_MID,
    COMMISSION_TIER_HIGH_CENTS,
    COMMISSION_TIER_MID_CENTS,
    FEE_PER_ASSIGNMENT_HIGH_CENTS,
    FEE_PER_ASSIGNMENT_LOW_CENTS,
    FEE_TIER_CENTS,
)
from db import db, touch
from rounding import round_half_up, sort_key_approved


def commission_rate_for(gross_pool_cents: int) -> Decimal:
    if gross_pool_cents < COMMISSION_TIER_MID_CENTS:
        return Decimal(COMMISSION_RATE_LOW)
    if gross_pool_cents < COMMISSION_TIER_HIGH_CENTS:
        return Decimal(COMMISSION_RATE_MID)
    return Decimal(COMMISSION_RATE_HIGH)


def funds_required(max_assignments: int, reward_cents: int, bonus_budget_cents: int) -> int:
    gross_pool = max_assignments * reward_cents + bonus_budget_cents
    commission = round_half_up(Decimal(gross_pool) * commission_rate_for(gross_pool))
    pre_fee = gross_pool + commission
    if pre_fee < FEE_TIER_CENTS:
        fee_per_assignment = FEE_PER_ASSIGNMENT_LOW_CENTS
    else:
        fee_per_assignment = FEE_PER_ASSIGNMENT_HIGH_CENTS
    return pre_fee + max_assignments * fee_per_assignment


def recompute_funds(hire: dict) -> None:
    hire["funds_required_cents"] = funds_required(
        hire["max_assignments"], hire["reward_cents"], hire["bonus_budget_cents"]
    )


def snapshot_escrow(hire: dict) -> None:
    """A published or dispatched HIT holds its whole funds_required_cents.

    A DRAFT holds nothing: PRD §3.1 mints a task with escrowed_cents at zero,
    and cancelling from DRAFT releases nothing because no funds were held.
    """
    if hire["status"] in {"PUBLISHED", "DISPATCHED"}:
        hire["escrowed_cents"] = hire["funds_required_cents"]
    elif hire["status"] in {"COMPLETED", "CANCELLED"}:
        hire["escrowed_cents"] = 0


# --- requester ledger ------------------------------------------------------
def total_escrowed_holds(requester_id: str) -> int:
    """Sum of escrowed_cents over the requester's non-terminal HITs."""
    return sum(
        h["escrowed_cents"]
        for h in db.hits.values()
        if h["requester_id"] == requester_id
        and h["status"] in {"DRAFT", "PUBLISHED", "DISPATCHED"}
    )


def sync_requester_escrow(requester_row: dict) -> None:
    requester_row["escrowed_cents"] = total_escrowed_holds(requester_row["id"])


def spent_totals(requester_id: str) -> int:
    """Sum over all the requester's HITs of spent_rewards + spent_bonus."""
    total = 0
    for h in db.hits.values():
        if h["requester_id"] == requester_id:
            total += h["spent_rewards_cents"] + h["spent_bonus_cents"]
    return total


def sync_requester_lifetime_spend(requester_row: dict) -> None:
    requester_row["lifetime_spent_cents"] = spent_totals(requester_row["id"])


def succeeded_deposit_total(requester_id: str) -> int:
    return sum(
        d["amount_cents"]
        for d in db.deposits.values()
        if d["requester_id"] == requester_id and d["status"] == "SUCCEEDED"
    )


def sync_requester_prepaid(requester_row: dict) -> None:
    """Spendable remainder = succeeded deposits - escrowed - lifetime spent."""
    requester_row["prepaid_balance_cents"] = (
        succeeded_deposit_total(requester_row["id"])
        - requester_row["escrowed_cents"]
        - requester_row["lifetime_spent_cents"]
    )


def resync_requester(requester_row: dict) -> None:
    """Re-derive the requester's three balances from their own rows.

    prepaid_balance_cents is a pure function (PRD §2.8): succeeded deposits,
    less currently escrowed funds, less lifetime spend. Escrow and lifetime
    spend are themselves pure functions of the requester's HIT rows, so the
    whole ledger is recomputed rather than adjusted in place.
    """
    sync_requester_escrow(requester_row)
    sync_requester_lifetime_spend(requester_row)
    sync_requester_prepaid(requester_row)


def recompute_hit_spent_rewards(hire: dict) -> None:
    """Chronological replay over APPROVED assignments (approved_at ASC, seq ASC)."""
    rows = [
        a
        for a in db.assignments.values()
        if a["hit_id"] == hire["id"] and a["status"] == "APPROVED"
    ]
    rows.sort(key=sort_key_approved)
    hire["spent_rewards_cents"] = sum(hire["reward_cents"] for _ in rows)


def recompute_hit_spent_bonus(hire: dict) -> None:
    hire["spent_bonus_cents"] = sum(
        a["bonus_cents"]
        for a in db.assignments.values()
        if a["hit_id"] == hire["id"] and a["bonus_cents"]
    )


def recompute_hit_counts(hire: dict) -> None:
    """Re-derive the HIT's three assignment counters from its assignment rows.

    Deriving beats incremental adjustment here: the same counters are touched
    by acceptance, return, expiry, rejection, approval, auto-approval and the
    suspension cascade, and every one of those paths leaves a different-looking
    trail of side effects in the spec.

      accepted_count        - assignments formerly or currently ACCEPTED; since
                              every assignment is minted ACCEPTED this is the
                              row count, and it never decreases
      assignment_count      - currently live work: ACCEPTED or SUBMITTED
                              (return / expiry / rejection all decrement it)
      committed_assignments - assignments whose committed flag is still TRUE
    """
    rows = [a for a in db.assignments.values() if a["hit_id"] == hire["id"]]
    hire["accepted_count"] = len(rows)
    hire["assignment_count"] = sum(
        1 for a in rows if a["status"] in {"ACCEPTED", "SUBMITTED"}
    )
    hire["committed_assignments"] = sum(1 for a in rows if a.get("committed"))


def is_hit_complete(hire: dict) -> bool:
    """Completion gate (calculation: hit_completion_release).

    The counts are the PERSISTED figures, not a fresh re-derivation: PRD §2.8
    defines ``escrowed_cents`` as the sum over the requester's "still
    non-terminal" tasks, and §3.8 closes the ledger out by moving them to
    COMPLETED, so the gate has to agree with whichever counter the last write
    path published. Re-deriving here would let a task jump to COMPLETED while
    its persisted counters still describe a live pool.
    """
    if hire["accepted_count"] != hire["max_assignments"]:
        return False
    if hire["committed_assignments"] != 0:
        return False
    return all(
        a["status"] in {"APPROVED", "REJECTED", "RETURNED", "EXPIRED"}
        for a in db.assignments.values()
        if a["hit_id"] == hire["id"]
    )


def complete_hit(hire: dict) -> bool:
    """Bubble a fully-terminal HIT up to COMPLETED and release its residual escrow.

    balance_released_cents = escrowed_cents - spent_rewards_cents - spent_bonus_cents;
    the release is expressed by zeroing the HIT's escrow, which the requester's
    derived ledger picks up immediately.
    """
    if hire["status"] in {"COMPLETED", "CANCELLED"}:
        return False
    if not is_hit_complete(hire):
        return False
    requester_row = db.requesters[hire["requester_id"]]
    recompute_hit_spent_rewards(hire)
    recompute_hit_spent_bonus(hire)
    hire["escrowed_cents"] = 0
    hire["status"] = "COMPLETED"
    touch(hire)
    resync_requester(requester_row)
    touch(requester_row)
    return True


def recompute_requester_counts(requester_row: dict) -> None:
    approved = 0
    rejected = 0
    for r in db.reviews.values():
        if r.get("actor_requester_id") != requester_row["id"]:
            continue
        assignment = db.assignments.get(r["assignment_id"])
        if assignment is None:
            continue
        hire = db.hits.get(assignment["hit_id"])
        if hire is None or hire["requester_id"] != requester_row["id"]:
            continue
        if r["kind"] == "APPROVAL":
            approved += 1
        elif r["kind"] == "REJECTION":
            rejected += 1
    requester_row["approved_count"] = approved
    requester_row["rejected_count"] = rejected