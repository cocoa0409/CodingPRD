"""The seller warranty exposure ledger (PRD §2.7 and §3.5).

exposure_floor_cents = max(0, constraint_exposure_cents + repaired_exposure_cents)

The constraint term comes only from the seller's most recent CLOSED
service-score section; the repair term is the per-cell-rounded sum of the
seller's live exposure cells.  `reserved_claim_cents` is exposed by the read
endpoint but is deliberately NOT netted out of the floor.
"""

from db import store, calendar_days_between
from errors import fail
from numeric import floor_div_int, rhu, rhu_int
from services import reservations as resv
from vocab import (
    CONSTRAINT_VIOLATION_UNIT_CENTS,
    SUSPENSION_TRIGGER_CEILING,
    SUSPENSION_TRIGGER_MINIMUM,
    UNITS_DENOMINATOR,
    VIOLATION_DOOR_UNITS,
)


# ------------------------------------------------------------- selection
def latest_closed_section(seller_id):
    """The seller's most recent CLOSED service-score section, or None."""
    rows = [
        row for row in store.service_scores.values()
        if row["seller_id"] == seller_id and row["section_state"] == "CLOSED"
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("section_closed_on") or "", r.get("_seq", 0)))
    return rows[-1]


def latest_closed_score(seller_id):
    section = latest_closed_section(seller_id)
    if section is None:
        return None
    return section.get("service_score")


def claims_routed_in_window(seller_id, opened, closed):
    """Claims routed to the seller whose created_at is in (opened, closed].

    Lower bound EXCLUSIVE, upper bound INCLUSIVE (PRD §3.7).
    """
    out = []
    for claim in store.claims.values():
        if claim.get("routed_seller_id") != seller_id:
            continue
        created = claim.get("_created_dt")
        if created is None:
            continue
        if created > opened and created <= closed:
            out.append(claim)
    return out


# ------------------------------------------------------- constraint term
def seller_constraint_exposure(seller_id):
    """Threshold rule; the divisor FLOORS and never rounds."""
    section = latest_closed_section(seller_id)
    if section is None:
        return 0
    opened = section["_opened_dt"]
    closed = section.get("_closed_dt")
    if closed is None:
        return 0
    filed = len(claims_routed_in_window(seller_id, opened, closed))
    raw_units = VIOLATION_DOOR_UNITS * filed

    # Branch structure as specified, with the top branch's quotient taken over
    # the door (100) rather than the denominator (300).  That is the only
    # reading under which all three of the spec's worked boundaries hold:
    #   4 claims -> raw 400 -> units 4 -> 38400
    #   3 claims -> raw 300 -> units 3 -> 28800   (>= is inclusive)
    #   1 claim  -> raw 100 -> floor(100/300) = 0 -> 0
    # raw_units // 100 is identically the section's routed claim count.
    if raw_units >= UNITS_DENOMINATOR:
        units = raw_units // VIOLATION_DOOR_UNITS
    elif VIOLATION_DOOR_UNITS <= raw_units < UNITS_DENOMINATOR:
        units = floor_div_int(raw_units, UNITS_DENOMINATOR)
    else:
        units = 0
    return units * CONSTRAINT_VIOLATION_UNIT_CENTS


# ---------------------------------------------------------- repair term
def repaired_exposure_cents(seller_id, clock):
    """Per-cell rounding, then the sum (the published convention)."""
    return sum(resv.cell_value_cents(cell, clock) for cell in resv.live_cells(seller_id, clock))


def traced_exposure_cents(seller_id, clock):
    """A single round_half_up over the combined total (the read-only trace)."""
    cells = resv.live_cells(seller_id, clock)
    total_raw = sum(resv.cell_value_raw(cell, clock) for cell in cells)
    return rhu_int(total_raw, 0)


def reserved_claim_cents(seller_id):
    """APPROVED-and-unresolved claim reserve held by the seller."""
    return sum(
        claim.get("claim_reserve_cents", 0)
        for claim in store.claims.values()
        if claim.get("routed_seller_id") == seller_id and claim["claim_state"] == "APPROVED"
    )


# ------------------------------------------------------------- recompute
def compute_exposure_floor(seller_id, clock):
    """(1) constraint, (2) carried repair, (3) clamp at zero."""
    constraint = seller_constraint_exposure(seller_id)
    repaired = repaired_exposure_cents(seller_id, clock)
    return max(0, constraint + repaired)


def recompute_exposure_floor(seller_id, clock):
    """Rebuild and persist the seller's exposure floor, bumping its version."""
    from db import touch
    seller = store.sellers.get(seller_id)
    if seller is None:
        return None
    seller["exposure_floor_cents"] = compute_exposure_floor(seller_id, clock)
    touch(seller, clock)
    return seller


# ------------------------------------------------------------- escalation
def service_days(seller_id, clock):
    return resv.service_days(seller_id, clock)


def ramp_steps(service_days_value, window_days=1):
    if window_days <= 0:
        return 0
    return floor_div_int(service_days_value, window_days)


def escalation_score(seller_id, clock, window_days=1, points_per_step=20.0):
    """max(0, floor(latest_score_pct - 20 * ramp_steps)).

    An un-scored seller starts from 100.00.  Both the day count and the tier
    step index are floored, so no partial window and no partial tier is
    credited.
    """
    from vocab import UNSCORED_SELLER_LATEST_SCORE_PCT
    latest = latest_closed_score(seller_id)
    latest_pct = UNSCORED_SELLER_LATEST_SCORE_PCT if latest is None else float(latest)
    steps = ramp_steps(service_days(seller_id, clock), window_days)
    raw = latest_pct - points_per_step * steps
    return float(rhu(max(0.0, floor_div_int(raw, 1)), 2))


# ------------------------------------------------------ blocklist ceilings
def check_blocklist_ceiling(seller):
    """`seller_escalation_ceiling`: inclusive >= on both comparisons."""
    count = seller.get("suspension_trigger_count", 0)
    if count >= SUSPENSION_TRIGGER_CEILING:
        raise fail("ERR_TRIGGER_CEILING_REACHED")
    if count >= SUSPENSION_TRIGGER_MINIMUM:
        raise fail("ERR_HUMAN_REVIEW_REQUIRED")