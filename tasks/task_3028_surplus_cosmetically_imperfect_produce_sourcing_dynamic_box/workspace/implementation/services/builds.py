"""§3.4 / §3.6 Box building, the allocation cascade and the pricing plan."""

from decimal import Decimal

import common
import params
import rules
import store
from common import ApiError

# Internal sort rank for the class waterfall. Lot `item_type` itself is only
# PREFERENCE, FILLER or RETAINED.
def items_of(order_id, status=None):
    rows = [i for i in store.BOX_BUILD_ITEMS.values() if i["box_order_id"] == order_id]
    if status:
        rows = [i for i in rows if i["status"] == status]
    return store.by_created(rows)


def included_items(order_id):
    return items_of(order_id, status="INCLUDED")


# --- the eligibility sieve (§3.4) -------------------------------------------

def eligible_lots(order, customer):
    """The four-clause sieve, before allergy filtering is reported."""
    pool = []
    for lot in store.SUPPLY_LOTS.values():
        if lot["fulfillment_center_id"] != order["fulfillment_center_id"]:
            continue
        if lot["quality_status"] != "PASS":
            continue
        if lot["status"] != "READY":
            continue
        if lot["quantity_available"] < common.MIN_UNITS_PER_LINE:
            continue
        pool.append(lot)
    allergies = set(customer.get("dietary_allergy_codes") or [])
    safe = [l for l in pool if not (set(l.get("allergen_codes") or []) & allergies)]
    return pool, safe


def assert_no_allergen_draw(candidate_lots, customer):
    """§3.9 rung 6: a build that would place an allergen-bearing lot in a box."""
    allergies = set(customer.get("dietary_allergy_codes") or [])
    for lot in candidate_lots:
        if set(lot.get("allergen_codes") or []) & allergies:
            raise ApiError("ERR_ALLERGEN_CONFLICT", 422,
                           "A candidate lot shares an allergen code with the customer.")
        if lot["quality_status"] != "PASS":
            raise ApiError("ERR_LOT_QUALITY_HOLD", 409,
                           "Only lots whose quality_status is PASS may be drawn.")


# --- the allocation cascade (§3.4 / §2.8) ------------------------------------

def build_from_plan(order, plan, customer):
    """Entry path (i): an explicit line_plan is honoured in the order given."""
    lines = []
    lot_refs = []
    for entry in plan:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Each line_plan entry must be an object.")
        supply_lot_id = entry.get("supply_lot_id")
        units = params.as_int("units", entry.get("units"))
        if supply_lot_id is None or units is None:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Each line_plan entry needs supply_lot_id and units.")
        lot = store.SUPPLY_LOTS.get(supply_lot_id)
        if lot is None:
            raise ApiError("ERR_SUPPLY_LOT_NOT_FOUND", 404,
                           "No SupplyLot exists with the given id.")
        if lot["fulfillment_center_id"] != order["fulfillment_center_id"]:
            raise ApiError("ERR_LOT_QUALITY_HOLD", 409,
                           "The lot is not in the order's lane.")
        lot_refs.append(lot)
    assert_no_allergen_draw(lot_refs, customer)

    foreseen = 0
    for lot, entry in zip(lot_refs, plan):
        units = params.as_int("units", entry.get("units"))
        if units < common.MIN_UNITS_PER_LINE:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "A planned line needs at least %d units."
                           % common.MIN_UNITS_PER_LINE)
        if units > lot["quantity_available"]:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "A planned line exceeds the lot's available units.")
        line = make_line(order, lot, units, item_type="PREFERENCE")
        foreseen += units
        lines.append(line)
        if len(lines) >= common.MAX_LINES_PER_BOX:
            break
    return lines, foreseen


def build_from_waterfall(order, customer):
    """Entry path (ii): the class waterfall, capped per §2.8.

    The four classes are drawn in the fixed order preference-set,
    preference-any, filler, specialty. Each class takes no more than its own
    cap plus whatever quota earlier classes left unspent, and a shortfall a
    class cannot fill carries forward to the class after it.
    """
    pool, safe = eligible_lots(order, customer)
    assert_no_allergen_draw(pool, customer)
    ranked = rules.rank_lots(safe)
    cap_preference, cap_filler, cap_specialty = rules.class_caps()

    preference_pool = [l for l in ranked if l["preference_eligible"]]
    other_pool = [l for l in ranked if not l["preference_eligible"]]

    remaining = {lot["id"]: lot["quantity_available"] for lot in ranked}
    used = set()
    lines = []
    unspent = 0
    total_units = 0

    classes = (
        ("PREFERENCE", preference_pool, cap_preference, "PREFERENCE"),
        ("PREFERENCE", preference_pool, 0, "PREFERENCE"),
        (None, other_pool, cap_filler, "FILLER"),
        (None, other_pool, cap_specialty, "FILLER"),
    )
    for _, candidates, own_cap, item_type in classes:
        quota = own_cap + unspent
        chosen = None
        for lot in candidates:
            if lot["id"] in used:
                continue
            if remaining[lot["id"]] < common.MIN_UNITS_PER_LINE:
                continue
            chosen = lot
            break
        if chosen is None or quota < common.MIN_UNITS_PER_LINE:
            unspent = max(0, quota)
            continue
        units = min(quota, remaining[chosen["id"]])
        if units < common.MIN_UNITS_PER_LINE:
            unspent = max(0, quota)
            continue
        line = make_line(order, chosen, units, item_type=item_type)
        lines.append(line)
        remaining[chosen["id"]] -= units
        used.add(chosen["id"])
        total_units += units
        unspent = quota - units
        if len(lines) >= common.MAX_LINES_PER_BOX:
            break
    return lines, total_units


def make_line(order, lot, units, item_type, status="INCLUDED"):
    """Create one BoxBuildItem and freeze its billing weight at build time."""
    billed = rules.billing_weight_grams(lot)
    price = rules.line_price_cents(billed, lot["display_price_cents"])
    line = store.new_row({
        "box_order_id": order["id"],
        "supply_lot_id": lot["id"],
        "category": lot["category"],
        "units": units,
        "billed_unit_weight_grams": billed,
        "line_price_cents": price,
        "item_type": item_type,
        "status": status,
        "allocation_credited_cents": 0,
    })
    store.BOX_BUILD_ITEMS[line["id"]] = line
    return line


def retire_over_target(lines):
    """§3.4: a planned line past the box unit target is retired immediately.

    Lines are walked in plan order and a running unit count accumulates; the
    first line that would take that count past BOX_UNIT_TARGET is retired and
    does not contribute to the count. This retiral is the only path by which a
    planned line leaves a box.
    """
    retired = []
    running = 0
    for line in lines:
        if line["status"] != "INCLUDED":
            continue
        if running + line["units"] > common.BOX_UNIT_TARGET:
            line["status"] = "REMOVED"
            store.touch(line)
            retired.append(line)
        else:
            running += line["units"]
    return retired


def remove_all_lines(order, restore_inventory):
    """§3.5: every build item of the order moves to REMOVED."""
    removed = []
    for line in items_of(order["id"]):
        if line["status"] == "INCLUDED":
            if restore_inventory:
                restore_units(line)
            line["status"] = "REMOVED"
            store.touch(line)
            removed.append(line)
    return removed


def restore_units(line):
    """Return the units a removed line consumed to its source lot."""
    lot = store.SUPPLY_LOTS.get(line["supply_lot_id"])
    if lot is not None:
        lot["quantity_available"] += line["units"]
        store.touch(lot)


def decrement_units(line):
    lot = store.SUPPLY_LOTS.get(line["supply_lot_id"])
    if lot is not None:
        lot["quantity_available"] -= line["units"]
        store.touch(lot)


# --- the pricing plan (§3.6) -------------------------------------------------

def reprice(order):
    """Recompute the order's derived figures from its INCLUDED lines."""
    lines = included_items(order["id"])
    customer = store.CUSTOMERS.get(order["customer_id"])

    lines_total = sum(l["line_price_cents"] for l in lines)
    weight_total = sum(l["billed_unit_weight_grams"] for l in lines)
    order["lines_total_cents"] = lines_total
    order["weight_total_grams"] = weight_total

    gate = common.ORDER_DISCOUNT_GATE_CENTS
    if lines_total >= gate:
        order["order_discount_cents"] = rules.round_half_up(
            rules.d(lines_total) * rules.d(common.ORDER_DISCOUNT_RATE))
    else:
        order["order_discount_cents"] = 0
    order["subtotal_cents"] = lines_total - order["order_discount_cents"]

    if customer is None or not customer.get("grandfathered_service_fee"):
        order["service_fee_cents"] = common.SERVICE_FEE_CENTS
    else:
        order["service_fee_cents"] = 0

    order["tax_cents"] = rules.round_half_up(
        rules.d(order["subtotal_cents"]) * rules.d(common.TAX_RATE))
    order["shipped_total_cents"] = (order["subtotal_cents"] + order["tax_cents"]
                                    + order["service_fee_cents"])
    order["conventional_total_cents"] = conventional_total(order, lines)
    store.touch(order)
    return order


def conventional_total(order, lines):
    """§3.6: the merchandise total scaled by the weight-apportioned quotient."""
    display_sum = Decimal("0")
    quote_sum = Decimal("0")
    for line in lines:
        lot = store.SUPPLY_LOTS.get(line["supply_lot_id"])
        if lot is None:
            continue
        weight = rules.d(line["billed_unit_weight_grams"])
        display_sum += weight * rules.d(lot["display_price_cents"])
        quote = rules.primary_quote(lot["id"])
        if quote is None:
            quote_sum += weight * rules.d(lot["display_price_cents"])
        else:
            quote_sum += weight * rules.d(quote["conventional_unit_price_cents"])
    if display_sum == 0:
        return 0
    quotient = quote_sum / display_sum
    return rules.round_half_up(rules.d(order["lines_total_cents"]) * quotient)


# --- the derived order readings ---------------------------------------------

def refresh_order_derivations(order):
    center = store.FULFILLMENT_CENTERS.get(order["fulfillment_center_id"])
    if center is not None:
        # §3.4: build_blocked reports whether the owning center's posture is
        # anything other than OPEN. §3.5 additionally pins it true on an order
        # struck down by a DEGRADED cascade or declared crashed, and that
        # setting survives the center returning to OPEN until the order is
        # deliberately walked back.
        order["build_blocked"] = (center.get("forward_posture") != "OPEN"
                                  or bool(order.get("_forced_blocked")))
        order["routing_region"] = center["region"]
    order["cold_chain_selected"] = any(
        p["box_order_id"] == order["id"] for p in store.COLD_CHAIN_PACKS.values())
    order["credit_cents_issued"] = sum(
        c["credited_cents"] for c in store.QUALITY_CLAIMS.values()
        if c["box_order_id"] == order["id"])
    order["allocation_used_cents"] = sum(
        l["allocation_credited_cents"] for l in store.BOX_BUILD_ITEMS.values()
        if l["box_order_id"] == order["id"])
    return order


def recompute_window(order):
    subscription = store.SUBSCRIPTIONS.get(order["subscription_id"])
    center = store.FULFILLMENT_CENTERS.get(order["fulfillment_center_id"])
    if subscription is None or center is None:
        return
    plan = rules.order_window_plan(subscription, order["serving_cycle_index"],
                                   center, order["created_at"])
    order["ready_deadline"] = plan["ready_deadline"]
    order["build_deadline"] = plan["build_deadline"]
    order["cutoff_met"] = plan["cutoff_met"]