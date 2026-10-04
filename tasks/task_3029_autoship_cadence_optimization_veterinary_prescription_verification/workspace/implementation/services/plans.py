"""Plan/item recalibration, cascade hops and prescription support helpers."""

import clock
import db
import serializers
from errors import fail
from services.constants import CALLBACK_ATTEMPT_CAP


# ---------------------------------------------------------------------------
# plan-level recomputation
# ---------------------------------------------------------------------------

def recompute_item_projections(item):
    """Recompute the derived item projections from the pet + product."""
    plan = db.AUTOSHIP_PLANS.get(item.get("autoship_plan_id"))
    pet = db.PETS.get(plan.get("pet_id")) if plan else None
    product = db.PRODUCTS.get(item.get("product_id"))
    item["unit_lifecycle_equivalent_days"] = serializers.run_cadence_days(pet, product)
    item["cadence_prompt_state"] = serializers.cadence_prompt_state(item, pet, product)
    return item


def recompute_plan_aggregates(plan):
    """next_order_due_date, item_count and the cadence prompt ladder (SS3.2)."""
    plan["autoship_item_count"] = serializers.plan_item_count(plan["id"])
    due = serializers.plan_next_due_date(plan["id"])
    plan["next_order_due_date"] = due

    if due is None:
        plan["cadence_prompt_due_days_delta"] = 0
        return plan

    base = plan.get("cadence_prompt_due_date") or due
    gap = clock.whole_days_between(base, due)
    if gap <= -28:
        delta = 14
    elif gap <= -14:
        delta = 7
    elif gap <= 0:
        delta = 0
    elif gap < 3:
        delta = 3
    else:
        delta = min(gap - 3, 21)
    plan["cadence_prompt_due_days_delta"] = delta
    plan["cadence_prompt_due_date"] = clock.add_days(base, delta)
    return plan


def recompute_pet_plans(pet_id):
    """Every plan of the pet recomputes its prompt ladder (weight recorded)."""
    for plan in db.AUTOSHIP_PLANS.values():
        if plan.get("pet_id") == pet_id:
            recompute_plan_aggregates(plan)


def recompute_pet_items(pet_id):
    """Every item of the pet recomputes its consumption projection."""
    for item in db.AUTOSHIP_ITEMS.values():
        plan = db.AUTOSHIP_PLANS.get(item.get("autoship_plan_id"))
        if plan and plan.get("pet_id") == pet_id:
            recompute_item_projections(item)


# ---------------------------------------------------------------------------
# verification-failure cascade hops (SS2.8 / PRD SS3.3)
# ---------------------------------------------------------------------------

def apply_prescription_block(item):
    """Hop 1: item verification UNVERIFIED/VERIFIED -> BLOCKED.

    PRD SS3.3 states that each recorded callback attempt "bumps the owning item's
    `version` by one" and that the third attempt then fires the three-hop
    cascade.  The version bump belongs to the attempt; the cascade is a
    consequence of it and writes only the item's `verification_state`.  Touching
    the item again here would advance its version a second time for the same
    attempt.
    """
    if item is None:
        return
    item["verification_state"] = "BLOCKED"


def plan_suspend_on_item_block(plan):
    """Hop 2: plan ACTIVE -> SUSPENDED because a live item is blocked."""
    if plan is None or plan.get("plan_status") != "ACTIVE":
        return
    plan["plan_status"] = "SUSPENDED"
    db.touch(plan)


def revoke_discount_eligibility(plan):
    """Hop 3: autoship_discount_eligibility ELIGIBLE -> INELIGIBLE."""
    if plan is None:
        return
    plan["autoship_discount_eligibility"] = "INELIGIBLE"
    db.touch(plan)


def verification_failure_cascade(prescription):
    """Fires on the third callback attempt and on prescriber suspension."""
    item = db.AUTOSHIP_ITEMS.get(prescription.get("autoship_item_id"))
    apply_prescription_block(item)
    if item is None:
        return
    plan = db.AUTOSHIP_PLANS.get(item.get("autoship_plan_id"))
    plan_suspend_on_item_block(plan)
    revoke_discount_eligibility(plan)


# ---------------------------------------------------------------------------
# pet-passing cascade (SS1.2 Pet; PRD SS3.6)
# ---------------------------------------------------------------------------

def park_in_transit_work(plan_ids):
    """Shipment DISPATCHED -> AWAITING... first, then Order SHIPPED -> AWAITING...

    Returns the first parked shipment id (the review's affected_shipment_id).
    """
    parked_shipments = []
    for shipment in db.SHIPMENTS.values():
        order = db.ORDERS.get(shipment.get("order_id"))
        if order is None or order.get("autoship_plan_id") not in plan_ids:
            continue
        if shipment.get("shipment_status") == "DISPATCHED":
            shipment["shipment_status"] = "AWAITING_PET_PASSING_DECISION"
            db.touch(shipment)
            parked_shipments.append(shipment)

    for shipment in parked_shipments:
        order = db.ORDERS.get(shipment.get("order_id"))
        if order is not None and order.get("order_status") == "SHIPPED":
            order["order_status"] = "AWAITING_PET_PASSING_DECISION"
            db.touch(order)

    return parked_shipments[0]["id"] if parked_shipments else None


def compassionate_cancel_plans(pet_id):
    """Every plan of the pet ACTIVE/PAUSED/SUSPENDED -> COMPASSIONATE_CANCELED."""
    for plan in db.AUTOSHIP_PLANS.values():
        if plan.get("pet_id") != pet_id:
            continue
        if plan.get("plan_status") in ("ACTIVE", "PAUSED", "SUSPENDED"):
            plan["plan_status"] = "COMPASSIONATE_CANCELED"
            db.touch(plan)


def cancel_non_terminal_orders(plan, reason):
    """Plan cancellation cascade: orders and their shipments become CANCELED."""
    cancel_statuses = (
        "PLACED",
        "PROCESSING",
        "SHIPPED",
        "AWAITING_PET_PASSING_DECISION",
    )
    for order in db.ORDERS.values():
        if order.get("autoship_plan_id") != plan["id"]:
            continue
        if order.get("order_status") not in cancel_statuses:
            continue
        order["order_status"] = "CANCELED"
        order["cancellation_reason"] = reason
        db.touch(order)
        for shipment in db.SHIPMENTS.values():
            if shipment.get("order_id") != order["id"]:
                continue
            if shipment.get("shipment_status") in ("PENDING", "PACKED", "DISPATCHED"):
                shipment["shipment_status"] = "CANCELED"
                db.touch(shipment)
            release_shipment_reservations(shipment)


def release_shipment_reservations(shipment):
    """release step: HELD -> RELEASED and the site load excludes the units."""
    for reservation in db.COLD_PACK_RESERVATIONS.values():
        if reservation.get("shipment_id") != shipment["id"]:
            continue
        if reservation.get("reservation_status") == "HELD":
            reservation["reservation_status"] = "RELEASED"
            db.touch(reservation)


def commit_shipment_reservations(shipment):
    """The dispatched shipment's reservation stays held.

    PRD SS3.5 states the site's `cold_pack_committed_units` is "by invariant the
    sum of the `units` on its held reservations only", and that the release step
    moves a reservation from `HELD` to `RELEASED`.  A reservation moved to
    `CONSUMED` at dispatch could never take the release edge, so the site's
    committed load could not be restored when the shipped order is cancelled and
    the capacity would be stranded permanently.  The reservation therefore
    remains in its holding state while the shipment is in flight and only the
    release step takes it out of the sum.
    """
    return None


def existing_reservation_for_shipment(shipment_id):
    """The reservation row a shipment already holds, if any."""
    return next(
        (r for r in db.COLD_PACK_RESERVATIONS.values() if r.get("shipment_id") == shipment_id),
        None,
    )


# ---------------------------------------------------------------------------
# prescription helpers
# ---------------------------------------------------------------------------

def prescription_for_item(item_id):
    return next(
        (p for p in db.PRESCRIPTIONS.values() if p.get("autoship_item_id") == item_id),
        None,
    )


def recompute_item_due_after_verification(prescription):
    """Re-pull the owning item's next due date to the verification lead time."""
    item = db.AUTOSHIP_ITEMS.get(prescription.get("autoship_item_id"))
    if item is None:
        return
    item["autoship_item_next_due_date"] = clock.current()
    db.touch(item)


def verification_expiry_stamp(prescription):
    from services.constants import AUTHORIZATION_VALID_DAYS

    prescription["verification_expires_at"] = clock.add_days(
        clock.current(), AUTHORIZATION_VALID_DAYS
    )
    return prescription["verification_expires_at"]


def prescription_is_expired(prescription):
    """Half-open interval: usable strictly before verification_expires_at."""
    expires_at = prescription.get("verification_expires_at")
    if expires_at is None:
        return False
    return clock.current() >= expires_at


def expiry_sweep():
    """Automatic VERIFIED -> EXPIRED transition (PRD SS3.8)."""
    changed = []
    for prescription in db.PRESCRIPTIONS.values():
        if prescription.get("rx_status") != "VERIFIED":
            continue
        if not prescription_is_expired(prescription):
            continue
        prescription["rx_status"] = "EXPIRED"
        db.touch(prescription)
        item = db.AUTOSHIP_ITEMS.get(prescription.get("autoship_item_id"))
        if item is not None:
            item["verification_state"] = "EXPIRATION_MARKED"
            db.touch(item)
        changed.append(prescription)
    return changed


def vet_suspension_failover(vet):
    """Every VERIFIED prescription of this vet fails over to VERIFICATION_FAILED."""
    if vet.get("vet_status") not in ("SUSPENDED", "BLOCKED"):
        return
    for prescription in db.PRESCRIPTIONS.values():
        if prescription.get("prescriber_id") != vet["id"]:
            continue
        if prescription.get("rx_status") != "VERIFIED":
            continue
        prescription["rx_status"] = "VERIFICATION_FAILED"
        db.touch(prescription)
        item = db.AUTOSHIP_ITEMS.get(prescription.get("autoship_item_id"))
        if item is not None:
            apply_prescription_block(item)


def normalize_email(value):
    return (value or "").strip().lower()


def callback_attempt_cap_reached(prescription):
    return int(prescription.get("callback_attempt_count", 0)) >= CALLBACK_ATTEMPT_CAP


def complete_item_if_exhausted(prescription):
    """authorized_qty_remaining == 0 -> owning item ACTIVE -> COMPLETED."""
    if int(prescription.get("authorized_qty_remaining", 0) or 0) != 0:
        return
    item = db.AUTOSHIP_ITEMS.get(prescription.get("autoship_item_id"))
    if item is None or item.get("item_status") != "ACTIVE":
        return
    item["item_status"] = "COMPLETED"
    db.touch(item)
    plan = db.AUTOSHIP_PLANS.get(item.get("autoship_plan_id"))
    if plan is not None:
        recompute_plan_aggregates(plan)


def require(condition, error_id, message):
    if not condition:
        fail(error_id, message)