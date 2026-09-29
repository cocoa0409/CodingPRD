"""Derived ledgers and cascade reconciliation (PRD section 2.8).

Every function here is a full recompute over the current rows, never an
incremental delta, so a released encumbrance returns to exactly the value it
held before.  A recompute that actually moves a stored figure refreshes that
record's ``updated_at`` and increments its ``version`` exactly once per request.
"""

import calc
from db import db, sort_key, touch

HELD_OFFER_STATUSES = ("SENT", "COUNTERED")
HELD_BOOKING_STATUSES = ("DATE_HELD", "ANNOUNCED", "PERFORMED")
LIVE_ACTIVATION_STATUSES = ("CONFIRMED", "FULFILLED")


# ---------------------------------------------------------------------------
# navigation helpers
# ---------------------------------------------------------------------------

def offer_of_booking(booking):
    if booking is None:
        return None
    return db.offers.get(booking.get("offer_id"))


def artist_of_booking(booking):
    offer = offer_of_booking(booking)
    if offer is None:
        return None
    return db.artists.get(offer.get("artist_id"))


def edition_of_booking(booking):
    offer = offer_of_booking(booking)
    if offer is None:
        return None
    return db.editions.get(offer.get("fair_edition_id"))


def stage_of_booking(booking):
    if booking is None:
        return None
    return db.stages.get(booking.get("stage_id"))


def edition_of_stage(stage):
    if stage is None:
        return None
    return db.editions.get(stage.get("fair_edition_id"))


def scales_of_booking(booking_id):
    rows = [s for s in db.scales.values() if s.get("booking_id") == booking_id]
    rows.sort(key=lambda r: sort_key(r, "created_at"))
    return rows


def advance_of_booking(booking_id):
    rows = [a for a in db.advances.values() if a.get("booking_id") == booking_id]
    rows.sort(key=lambda r: sort_key(r, "created_at"))
    return rows[0] if rows else None


def rider_items_of_advance(advance_id):
    rows = [r for r in db.rider_items.values() if r.get("production_advance_id") == advance_id]
    rows.sort(key=lambda r: sort_key(r, "created_at"))
    return rows


def activations_of_booking(booking_id):
    rows = [a for a in db.activations.values() if a.get("booking_id") == booking_id]
    rows.sort(key=lambda r: sort_key(r, "created_at"))
    return rows


def actions_of_booking(booking_id):
    rows = [a for a in db.contingency_actions.values() if a.get("booking_id") == booking_id]
    rows.sort(key=lambda r: sort_key(r, "decided_at_utc"))
    return rows


def rounds_of_offer(offer_id):
    rows = [r for r in db.offer_rounds.values() if r.get("offer_id") == offer_id]
    rows.sort(key=lambda r: sort_key(r, "recorded_at_utc"))
    return rows


def bookings_of_edition(edition_id):
    rows = []
    for booking in db.bookings.values():
        offer = db.offers.get(booking.get("offer_id"))
        if offer is not None and offer.get("fair_edition_id") == edition_id:
            rows.append(booking)
    rows.sort(key=lambda r: sort_key(r, "created_at"))
    return rows


def _set(rec, field, value):
    """Write a derived field, reporting whether the stored figure moved."""
    if rec.get(field) != value:
        rec[field] = value
        return True
    return False


# ---------------------------------------------------------------------------
# roster
# ---------------------------------------------------------------------------

def recompute_agent_roster(agent):
    if agent is None:
        return
    count = sum(1 for a in db.artists.values() if a.get("agent_id") == agent["id"])
    if _set(agent, "roster_artist_count", count):
        touch(agent)


# ---------------------------------------------------------------------------
# edition ledgers
# ---------------------------------------------------------------------------

def recompute_edition_committed(edition):
    if edition is None:
        return
    total = 0
    for offer in db.offers.values():
        if offer.get("fair_edition_id") != edition["id"]:
            continue
        status = offer.get("status")
        if status in HELD_OFFER_STATUSES:
            total += int(offer.get("offered_guarantee_cents") or 0)
        elif status == "ACCEPTED":
            total += int(offer.get("agreed_guarantee_cents") or 0)
    if _set(edition, "committed_guarantee_total_cents", total):
        touch(edition)


def projected_edition_committed(edition, override_offer_id=None, override_amount=0):
    """The encumbrance ledger as it would read with one offer's contribution replaced."""
    total = 0
    for offer in db.offers.values():
        if offer.get("fair_edition_id") != edition["id"]:
            continue
        if override_offer_id is not None and offer["id"] == override_offer_id:
            total += int(override_amount or 0)
            continue
        status = offer.get("status")
        if status in HELD_OFFER_STATUSES:
            total += int(offer.get("offered_guarantee_cents") or 0)
        elif status == "ACCEPTED":
            total += int(offer.get("agreed_guarantee_cents") or 0)
    return total


def recompute_edition_open_stages(edition):
    if edition is None:
        return
    count = 0
    for stage in db.stages.values():
        if stage.get("fair_edition_id") == edition["id"] and stage.get("booking_posture") == "OPEN":
            count += 1
    if _set(edition, "open_stage_count", count):
        touch(edition)


def recompute_edition_refund_committed(edition):
    if edition is None:
        return
    total = 0
    for action in db.contingency_actions.values():
        booking = db.bookings.get(action.get("booking_id"))
        if booking is None:
            continue
        if edition_of_booking(booking) is not edition:
            continue
        total += int(action.get("refund_liability_cents") or 0)
    if _set(edition, "refund_liability_committed_cents", total):
        touch(edition)


# ---------------------------------------------------------------------------
# stage slot ledger
# ---------------------------------------------------------------------------

def stage_held_count(stage_id):
    count = 0
    for offer in db.offers.values():
        if offer.get("target_stage_id") == stage_id and offer.get("status") in HELD_OFFER_STATUSES:
            count += 1
    for booking in db.bookings.values():
        if booking.get("stage_id") == stage_id and booking.get("booking_status") in HELD_BOOKING_STATUSES:
            count += 1
    return count


def recompute_stage_ledger(stage):
    """Recompute held_show_count and booking_posture, cascading to open_stage_count."""
    if stage is None:
        return
    count = stage_held_count(stage["id"])
    posture = "SATURATED" if count >= int(stage.get("slot_soft_cap", 1)) else "OPEN"
    moved = _set(stage, "held_show_count", count)
    moved = _set(stage, "booking_posture", posture) or moved
    if moved:
        touch(stage)
    recompute_edition_open_stages(edition_of_stage(stage))


# ---------------------------------------------------------------------------
# offer ledger
# ---------------------------------------------------------------------------

def recompute_offer_round_count(offer):
    if offer is None:
        return
    offer["round_count"] = len(rounds_of_offer(offer["id"]))


# ---------------------------------------------------------------------------
# advance ledgers
# ---------------------------------------------------------------------------

def recompute_advance_ledgers(advance):
    """Reconcile the three advance ledgers, then mirror onto the booking."""
    if advance is None:
        return
    approved = 0
    recoupable = 0
    denied = 0
    for item in rider_items_of_advance(advance["id"]):
        status = item.get("status")
        if status in ("APPROVED", "SUBSTITUTED"):
            cost = int(item.get("approved_cost_cents") or 0)
            approved += cost
            if item.get("artist_recoupable"):
                recoupable += cost
        elif status == "DENIED":
            denied += 1
    advance["approved_rider_cost_cents"] = approved
    advance["recoupable_rider_cost_cents"] = recoupable
    advance["denied_item_count"] = denied
    booking = db.bookings.get(advance.get("booking_id"))
    recompute_booking_recoupable(booking)


def recompute_booking_recoupable(booking):
    if booking is None:
        return
    advance = advance_of_booking(booking["id"])
    if advance is None or advance.get("status") == "ADVANCE_CANCELLED":
        value = 0
    else:
        value = int(advance.get("recoupable_rider_cost_cents") or 0)
    if _set(booking, "recoupable_production_cost_cents", value):
        touch(booking)


# ---------------------------------------------------------------------------
# box-office ledgers
# ---------------------------------------------------------------------------

def recompute_scale_units(scale):
    if scale is None:
        return
    sold = calc.net_units_all(scale["id"])
    scale["sold_seats"] = sold
    scale["available_seats"] = int(scale.get("allotment_seats", 0)) - sold


def recompute_booking_paid_attendance(booking):
    if booking is None:
        return
    total = 0
    for scale in scales_of_booking(booking["id"]):
        total += calc.net_units_paid(scale["id"])
    if _set(booking, "paid_attendance", total):
        touch(booking)


def recompute_booking_gross_potential(booking):
    if booking is None:
        return
    total = sum(int(s.get("scale_gross_potential_cents") or 0) for s in scales_of_booking(booking["id"]))
    if _set(booking, "gross_potential_cents", total):
        touch(booking)


def recompute_booking_sponsorship_revenue(booking):
    if booking is None:
        return
    total = 0
    for activation in activations_of_booking(booking["id"]):
        if activation.get("status") in LIVE_ACTIVATION_STATUSES:
            total += int(activation.get("net_fee_cents") or 0)
    if _set(booking, "sponsorship_revenue_cents", total):
        touch(booking)


def recompute_booking_refund_liability(booking):
    if booking is None:
        return
    actions = actions_of_booking(booking["id"])
    value = int(actions[-1].get("refund_liability_cents") or 0) if actions else 0
    if _set(booking, "refund_liability_cents", value):
        touch(booking)
