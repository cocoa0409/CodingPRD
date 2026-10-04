"""§2.7 Fulfillment-Center Forward Posture and §2.6 regional pinning."""

import rules
import store
from common import ApiError

POSTURE_MESSAGES = {
    "ERR_CENTER_FORWARD_LOCKED":
        "The owning center's forward posture does not permit this operation.",
}


def posture_for(center):
    """One counter only: serving_cycle_index against max_concurrent_building_cycles."""
    index = center["serving_cycle_index"]
    cap = center["max_concurrent_building_cycles"]
    if index >= cap + 1:
        return "DEGRADED"
    if index >= cap:
        return "CONSTRAINED"
    return "OPEN"


def refresh_posture(center):
    """Recompute the derived posture and run the cascades it triggers."""
    previous = center.get("forward_posture")
    current = posture_for(center)
    center["forward_posture"] = current
    if current == previous:
        return current
    if current == "DEGRADED":
        cascade_degraded(center)
    return current


def open_claim_count_for(center):
    """Claims at this center in IN_REVIEW or UNDER_REVIEW."""
    lane_lot_ids = {l["id"] for l in store.SUPPLY_LOTS.values()
                    if l["fulfillment_center_id"] == center["id"]}
    order_ids = {o["id"] for o in store.BOX_ORDERS.values()
                 if o["fulfillment_center_id"] == center["id"]}
    total = 0
    for claim in store.QUALITY_CLAIMS.values():
        if claim["status"] in ("IN_REVIEW", "UNDER_REVIEW") and \
                (claim.get("supply_lot_id") in lane_lot_ids or
                 claim.get("box_order_id") in order_ids):
            total += 1
    return total


def refresh_claim_count(center):
    center["open_claim_count"] = open_claim_count_for(center)
    return center["open_claim_count"]


def cascade_degraded(center):
    """§3.5: degrade one lane without recursing into the posture refresh."""
    if center["forward_posture"] != "DEGRADED":
        center["forward_posture"] = "DEGRADED"
    for order in list(store.BOX_ORDERS.values()):
        if order["fulfillment_center_id"] != center["id"]:
            continue
        if order["status"] not in ("BUILDING", "READY_TO_BUILD", "AWAITING_WINDOW"):
            continue
        reroute(order, restore_inventory=(order["status"] == "BUILDING"))


def reroute(order, restore_inventory):
    """BoxOrder -> REROUTED with the cascade that state carries (§3.5).

    An order caught in AWAITING_WINDOW only has build_blocked set and its
    cold-chain packs recomputed. An order caught in READY_TO_BUILD or BUILDING
    additionally has every build item moved to REMOVED, which triggers a
    reprice and leaves the pricing dimension at REVISED; a BUILDING order's
    cited lots are restored by the units the removed lines had consumed.
    """
    from services import builds, coldchain
    previous_status = order["status"]
    order["status"] = "REROUTED"
    order["build_blocked"] = True
    order["_forced_blocked"] = True
    if previous_status in ("BUILDING", "READY_TO_BUILD"):
        if previous_status == "BUILDING" or restore_inventory:
            for item in builds.items_of(order["id"]):
                if item["status"] == "INCLUDED":
                    builds.restore_units(item)
        builds.remove_all_lines(order, restore_inventory=False)
        order["pricing_status"] = "REVISED"
    store.touch(order)
    builds.reprice(order)
    coldchain.recompute_for_orders([order], bump=False)


def permit_check(center, allow_constrained=False):
    """Validation rung 9: the posture permit.

    §2.7: order creation and a build start are refused at a CONSTRAINED center,
    while finalisation is admitted there ("finalising an order remains admitted
    at a CONSTRAINED center precisely so that the counter can still be advanced
    and the center worked back down toward OPEN"). Only a DEGRADED center
    refuses finalisation and reroutes the order instead.
    """
    posture = center.get("forward_posture")
    if allow_constrained:
        if posture == "DEGRADED":
            raise ApiError("ERR_CENTER_FORWARD_LOCKED", 409,
                           POSTURE_MESSAGES["ERR_CENTER_FORWARD_LOCKED"])
        return
    if posture != "OPEN":
        raise ApiError("ERR_CENTER_FORWARD_LOCKED", 409,
                       POSTURE_MESSAGES["ERR_CENTER_FORWARD_LOCKED"])


def advance_cycle_index(center, delta):
    """Move the counter and refresh the posture."""
    new_index = max(0, center["serving_cycle_index"] + delta)
    center["serving_cycle_index"] = new_index
    refresh_posture(center)


def all_centers():
    return list(store.FULFILLMENT_CENTERS.values())


def any_open_order_with_unallocated_remainder(center_id):
    """§3.4: the lane-wide serialisation condition."""
    for order in store.BOX_ORDERS.values():
        if order["fulfillment_center_id"] != center_id:
            continue
        if order["status"] in ("READY_TO_BUILD", "BUILDING", "REROUTED"):
            return True
    return False


# --- regional assignment -----------------------------------------------------

def assign_home_center(customer):
    """§2.6: rank active centers of the region by code ascending, take first."""
    winner = rules.regional_center_assignment(customer["service_region"])
    if winner is None:
        raise ApiError("ERR_NO_CENTER_AVAILABLE", 422,
                       "The service region has no active fulfillment center.")
    repin_customer(customer, winner)
    return winner


def repin_customer(customer, center):
    """Stamp the customer's home center and re-pin every subscription."""
    customer["home_fulfillment_center_id"] = center["id"]
    store.touch(customer)
    for subscription in store.SUBSCRIPTIONS.values():
        if subscription["customer_id"] == customer["id"]:
            subscription["home_fulfillment_center_id"] = center["id"]
            store.touch(subscription)


def reassign_region(region):
    """§2.6: a center mutation re-evaluates every Customer of its region.

    The rule is the same one registration uses — rank the region's active
    centers by code ascending and take the first — so every customer without
    an explicit home center re-pins to the lowest-coded active center. A
    customer holding an explicit home center keeps it: §2.6 says that value is
    never rewritten by a later re-run of the regional rule.
    """
    winner = rules.regional_center_assignment(region)
    if winner is None:
        return
    for customer in list(store.CUSTOMERS.values()):
        if customer["service_region"] != region:
            continue
        if customer.get("_home_center_explicit"):
            continue
        if customer.get("home_fulfillment_center_id") != winner["id"]:
            repin_customer(customer, winner)