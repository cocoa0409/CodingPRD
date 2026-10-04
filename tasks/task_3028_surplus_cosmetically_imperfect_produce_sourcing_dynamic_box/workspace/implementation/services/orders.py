"""§3.4 / §3.5 Box order lifecycle: open, finalise, build, reroute, crash, pack."""

import clock
import rules
import store
from common import ApiError
from services import builds, centers, coldchain, lots, subscriptions


def order_of(order_id):
    order = store.BOX_ORDERS.get(order_id)
    if order is None:
        raise ApiError("ERR_BOX_ORDER_NOT_FOUND", 404,
                       "No BoxOrder exists with the given id.")
    return order


def create_order(customer, subscription, serving_cycle_index, cuisine_preference):
    """POST /box-orders."""
    center = store.FULFILLMENT_CENTERS.get(customer["home_fulfillment_center_id"])
    if center is None:
        raise ApiError("ERR_FULFILLMENT_CENTER_NOT_FOUND", 404,
                       "No FulfillmentCenter exists with the given id.")

    # Rung 9: the posture permit for order creation.
    centers.permit_check(center)

    # Rung 12: cadence eligibility.
    if subscription["status"] in ("PAUSED", "CANCELLED"):
        # §3.8 carves out a one-off order for a PAUSED subscription, which is
        # re-engaged rather than refused; a CANCELLED subscription is inert.
        if subscription["status"] == "CANCELLED":
            raise ApiError("ERR_SUBSCRIPTION_INELIGIBLE", 409,
                           "A cancelled subscription may not generate an order.")
    for existing in store.BOX_ORDERS.values():
        if existing["subscription_id"] == subscription["id"] and \
                existing["serving_cycle_index"] == serving_cycle_index and \
                existing["status"] != "ABANDONED":
            raise ApiError("ERR_SUBSCRIPTION_INELIGIBLE", 409,
                           "A box already exists for this subscription and cycle.")

    plan = rules.order_window_plan(subscription, serving_cycle_index, center,
                                   clock.now_iso())
    order = store.new_row({
        "customer_id": customer["id"],
        "subscription_id": subscription["id"],
        "serving_cycle_index": serving_cycle_index,
        "fulfillment_center_id": center["id"],
        "routing_region": center["region"],
        "cuisine_preference": cuisine_preference,
        "status": "DRAFT",
        "pricing_status": "UNPRICED",
        "lines_total_cents": 0,
        "weight_total_grams": 0,
        "conventional_total_cents": 0,
        "order_discount_cents": 0,
        "service_fee_cents": 0,
        "subtotal_cents": 0,
        "tax_cents": 0,
        "shipped_total_cents": 0,
        "ready_deadline": plan["ready_deadline"],
        "build_deadline": plan["build_deadline"],
        "cutoff_met": plan["cutoff_met"],
        "build_blocked": center.get("forward_posture") != "OPEN",
        "_forced_blocked": False,
        "cold_chain_selected": False,
        "credit_cents_issued": 0,
        "allocation_used_cents": 0,
    })
    store.BOX_ORDERS[order["id"]] = order
    subscriptions.order_created_against(subscription)
    return order


def finalize(order, customer):
    """DRAFT -> AWAITING_WINDOW with the three-way cascade."""
    center = store.FULFILLMENT_CENTERS.get(order["fulfillment_center_id"])
    subscription = store.SUBSCRIPTIONS.get(order["subscription_id"])
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The order is not in a state that admits finalisation.")
    # Rung 6: allergen exclusion.
    assert_no_allergen_present(order, customer)
    # Rung 8: the cutoff.
    if not order["cutoff_met"]:
        raise ApiError("ERR_ORDER_CUTOFF_MISSED", 422,
                       "The order was created at or after its ready_deadline.")
    # §3.4 / §3.9 rung 9: finalise is admitted unless the center is DEGRADED.
    centers.permit_check(center, allow_constrained=True)

    order["status"] = "AWAITING_WINDOW"
    store.touch(order)

    # §3.5: the DEGRADED cascade strikes "in the same instant" the counter
    # passes the cap, rerouting every in-flight order — including this one.
    # The finalisation must therefore report the reroute rather than leaving
    # the row in two competing outcomes.
    centers.advance_cycle_index(center, +1)
    store.touch(center)

    if center.get("forward_posture") == "DEGRADED":
        builds.refresh_order_derivations(order)
        return order

    if subscription is not None:
        subscription["serving_cycle_index"] += 1
        store.touch(subscription)

    builds.recompute_window(order)
    builds.reprice(order)
    builds.refresh_order_derivations(order)
    return order


def build(order, customer, line_plan, expected_version=None):
    """READY_TO_BUILD (or REROUTED) -> BUILDING."""
    center = store.FULFILLMENT_CENTERS.get(order["fulfillment_center_id"])
    original = order["status"]
    order["_requested_plan"] = line_plan or []

    # §3.9's ladder. Rung 6's allergen exclusion is checked before the version
    # comparison, and the version comparison before the from-state test, so a
    # request that is both stale and allergen-bearing reports the allergen
    # conflict (the earlier rung) while a request that is stale alone reports
    # the stale version. Both are settled before the window and lane rules of
    # the later business rungs.
    assert_build_allergens(order, customer)

    if expected_version is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_box_order_version is required for this operation.")
    try:
        supplied = int(expected_version)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected_box_order_version must be an integer.")
    if supplied != order.get("version"):
        raise ApiError("ERR_STALE_VERSION", 412,
                       "The supplied expected_box_order_version does not match the "
                       "BoxOrder's current version.")

    assert_state_gate_and_permit(order)

    if original == "READY_TO_BUILD":
        if not rules.within_build_window(order):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "The build deadline is behind the logical clock.")
        if not order["cutoff_met"]:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "cutoff_met is false; the order cannot build.")
    else:
        if not order["cutoff_met"]:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "cutoff_met is false; the rerouted order cannot build.")

    if line_plan is not None:
        lines, foreseen = builds.build_from_plan(order, line_plan, customer)
    else:
        lines, foreseen = builds.build_from_waterfall(order, customer)

    # The first pricing pass prices every planned line; any line that would
    # take the running unit count past the box unit target is then retired.
    retired = builds.retire_over_target(lines)

    for line in lines:
        if line["status"] == "INCLUDED":
            builds.decrement_units(line)

    order["status"] = "BUILDING"
    order["build_blocked"] = False
    order["_forced_blocked"] = False
    store.touch(order)

    if retired:
        order["pricing_status"] = "REVISED"
    else:
        order["pricing_status"] = "PRICED"
    builds.reprice(order)
    builds.refresh_order_derivations(order)
    return order


def assert_no_allergen_present(order, customer):
    """§3.9 rung 6 on finalisation: no allergen-bearing lot may remain inside."""
    allergies = set(customer.get("dietary_allergy_codes") or [])
    if not allergies:
        return
    for line in builds.items_of(order["id"]):
        if line["status"] != "INCLUDED":
            continue
        lot = store.SUPPLY_LOTS.get(line["supply_lot_id"])
        if lot is None:
            continue
        if set(lot.get("allergen_codes") or []) & allergies:
            raise ApiError("ERR_ALLERGEN_CONFLICT", 422,
                           "An allergen-bearing lot is present in the box.")


def assert_build_allergens(order, customer):
    """§3.9 rung 6 on the build, ahead of the version comparison.

    No allergen-bearing lot may be drawn into, or left inside, the box —
    whether it is named in the plan or merely a candidate — so the requested
    lots are declared first and the conflict is reported before the state rung
    that would otherwise answer a stale-version request.
    """
    allergies = set(customer.get("dietary_allergy_codes") or [])
    if not allergies:
        return
    for entry in (order.get("_requested_plan") or []):
        lot = store.SUPPLY_LOTS.get(entry.get("supply_lot_id"))
        if lot is None:
            raise ApiError("ERR_SUPPLY_LOT_NOT_FOUND", 404,
                           "No SupplyLot exists with the given id.")
        if set(lot.get("allergen_codes") or []) & allergies:
            raise ApiError("ERR_ALLERGEN_CONFLICT", 422,
                           "A candidate lot shares an allergen code with the customer.")


def assert_state_gate_and_permit(order):
    """The from-state half of rung 5, then rung 9's lane permit."""
    state = order["status"]
    if state == "REROUTED":
        center = store.FULFILLMENT_CENTERS.get(order["fulfillment_center_id"])
        if center is not None and center.get("forward_posture") == "DEGRADED":
            raise ApiError("ERR_CENTER_FORWARD_LOCKED", 409,
                           "The owning center is DEGRADED.")
    elif state == "READY_TO_BUILD":
        center = store.FULFILLMENT_CENTERS.get(order["fulfillment_center_id"])
        if center is not None:
            centers.permit_check(center)
    else:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The order is not in a state that admits a build.")


def reroute_back(order):
    """REROUTED -> DRAFT. The order discards its position in the window."""
    center = store.FULFILLMENT_CENTERS.get(order["fulfillment_center_id"])
    if order["status"] != "REROUTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a rerouted order can be returned to the draft pool.")
    if center is not None and center.get("forward_posture") == "DEGRADED":
        raise ApiError("ERR_CENTER_FORWARD_LOCKED", 409,
                       "The owning center is DEGRADED.")
    order["status"] = "DRAFT"
    order["build_blocked"] = False
    order["_forced_blocked"] = False
    store.touch(order)
    builds.refresh_order_derivations(order)
    return order


def crash_out(order):
    """BUILDING -> CRASHED, retaining the build lines."""
    if order["status"] != "BUILDING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an order currently BUILDING can be crashed out.")
    order["status"] = "CRASHED"
    order["build_blocked"] = True
    order["_forced_blocked"] = True
    store.touch(order)
    builds.refresh_order_derivations(order)
    return order


def pack(order):
    """BUILDING -> PACKED, selecting insulation and coolant by lane and season."""
    center = store.FULFILLMENT_CENTERS.get(order["fulfillment_center_id"])
    subscription = store.SUBSCRIPTIONS.get(order["subscription_id"])

    if order["status"] != "BUILDING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a BUILDING order can be packed.")
    if center is not None and center.get("forward_posture") == "DEGRADED":
        raise ApiError("ERR_CENTER_FORWARD_LOCKED", 409,
                       "The owning center is DEGRADED.")
    if subscription is not None and subscription["status"] not in (
            "ACTIVE", "SKIPPED", "AUTO_SKIPPED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The order's subscription cannot be packed.")
    # Rung 14: single-use eligibility.
    if order["cold_chain_selected"] or any(
            p["box_order_id"] == order["id"] for p in store.COLD_CHAIN_PACKS.values()):
        raise ApiError("ERR_ALREADY_ALLOCATED", 409,
                       "The order has already been packed for this serving cycle.")

    coldchain.pack_for(order)
    order["status"] = "PACKED"
    order["cold_chain_selected"] = True
    store.touch(order)

    if center is not None:
        centers.advance_cycle_index(center, -1)
        store.touch(center)
    if subscription is not None:
        subscription["serving_cycle_index"] -= 1
        store.touch(subscription)
    builds.refresh_order_derivations(order)
    return order


def lane_has_unallocated_remainder(center_id, excluding=None):
    """§3.4: whether the lane is serialised by another in-flight order."""
    for other in store.BOX_ORDERS.values():
        if other["id"] == (excluding["id"] if excluding else None):
            continue
        if other["fulfillment_center_id"] != center_id:
            continue
        if other["status"] in ("READY_TO_BUILD", "BUILDING", "REROUTED"):
            return True
    return False


def maybe_promote(order):
    """AWAITING_WINDOW -> READY_TO_BUILD once the clock reaches the deadline."""
    if order["status"] != "AWAITING_WINDOW":
        return order
    if clock.now() < clock.parse_instant(order["ready_deadline"]):
        return order
    if lane_has_unallocated_remainder(order["fulfillment_center_id"], excluding=order):
        return order
    order["status"] = "READY_TO_BUILD"
    store.touch(order)
    # The promotion recomputes the quality gate of every lot in the candidate
    # set. The gate is derived from each lot's own quality_status and status,
    # so re-deriving the lot figures is the whole of that recomputation.
    for lot in store.SUPPLY_LOTS.values():
        if lot["fulfillment_center_id"] == order["fulfillment_center_id"]:
            lots.derived_lot(lot)
    return order


def maybe_revert(order):
    """READY_TO_BUILD -> DRAFT when the build deadline passes with no INCLUDED line."""
    if order["status"] not in ("READY_TO_BUILD", "REROUTED"):
        return order
    if clock.now() <= clock.parse_instant(order["build_deadline"]):
        return order
    if any(i["status"] == "INCLUDED" for i in builds.items_of(order["id"])):
        return order
    center = store.FULFILLMENT_CENTERS.get(order["fulfillment_center_id"])
    subscription = store.SUBSCRIPTIONS.get(order["subscription_id"])
    previous = order["status"]
    order["status"] = "DRAFT"
    store.touch(order)
    if previous == "READY_TO_BUILD":
        if center is not None:
            centers.advance_cycle_index(center, -1)
            store.touch(center)
        if subscription is not None:
            subscription["serving_cycle_index"] -= 1
            store.touch(subscription)
    return order


def tick(order):
    """Run the scheduled deferred transitions the logical clock has reached."""
    maybe_promote(order)
    maybe_revert(order)
    builds.refresh_order_derivations(order)
    return order