"""Derived-field helpers: compliance, availability, occupancy, rollup lookups."""

from constants import (AUDITED_EXTRA_DOC_TYPES, EQUITY_SHARE_UNIT_CENTS,
                       MAX_VOTING_SHARES, REQUIRED_DOC_TYPES)
from store import ceil_div, db, now, sorted_records

# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------


def producer_documents(producer_id):
    return sorted_records([d for d in db.documents.values() if d["producer_id"] == producer_id])


def producer_products(producer_id):
    return sorted_records([p for p in db.products.values() if p["producer_id"] == producer_id])


def order_lines(order_id):
    return sorted_records([l for l in db.lines.values() if l["order_id"] == order_id])


def line_allocations(line_id):
    return sorted_records([a for a in db.allocations.values() if a["order_line_id"] == line_id])


def order_allocations(order_id):
    line_ids = set(l["id"] for l in db.lines.values() if l["order_id"] == order_id)
    return sorted_records([a for a in db.allocations.values() if a["order_line_id"] in line_ids])


def product_allocations(product_id):
    return sorted_records([a for a in db.allocations.values() if a["product_id"] == product_id])


def slot_appointments(slot_id):
    return sorted_records([a for a in db.appointments.values() if a["dock_slot_id"] == slot_id])


def route_orders(route_id):
    return sorted_records([o for o in db.orders.values() if o.get("route_id") == route_id])


def allocation_product(allocation):
    return db.products.get(allocation["product_id"])


def allocation_producer(allocation):
    product = allocation_product(allocation)
    if product is None:
        return None
    return db.producers.get(product["producer_id"])


def allocation_order(allocation):
    line = db.lines.get(allocation["order_line_id"])
    if line is None:
        return None
    return db.orders.get(line["order_id"])


# ---------------------------------------------------------------------------
# compliance (calculations.producer_compliance_evaluation)
# ---------------------------------------------------------------------------

def _counting_doc_types(producer_id):
    instant = now()
    types = set()
    for doc in db.documents.values():
        if doc["producer_id"] != producer_id:
            continue
        if doc["status"] != "VERIFIED":
            continue
        # strict: expires_on == now is already expired
        if doc["expires_on"] > instant:
            types.add(doc["doc_type"])
    return types


def evaluate_compliance(producer):
    """Recompute compliance_ok and food_safety_tier in place (no version bump)."""
    counting = _counting_doc_types(producer["id"])
    compliance_ok = all(t in counting for t in REQUIRED_DOC_TYPES)
    if compliance_ok and all(t in counting for t in AUDITED_EXTRA_DOC_TYPES):
        tier = "TIER_AUDITED"
    elif compliance_ok:
        tier = "TIER_BASIC"
    else:
        tier = "TIER_NONE"
    producer["compliance_ok"] = compliance_ok
    producer["food_safety_tier"] = tier
    return compliance_ok, tier


def compliance_ok(producer):
    return evaluate_compliance(producer)[0]


def food_safety_tier(producer):
    return evaluate_compliance(producer)[1]


def voting_shares(producer):
    shares = producer["paid_in_capital_cents"] // EQUITY_SHARE_UNIT_CENTS
    return min(shares, MAX_VOTING_SHARES)


def producer_in_good_standing(producer):
    return producer["onboarding_status"] == "ACTIVE" and compliance_ok(producer)


# ---------------------------------------------------------------------------
# product availability
# ---------------------------------------------------------------------------

def product_available(product):
    return max(0, product["quantity_offered"] - product["quantity_committed"])


def recompute_product_available(product):
    product["quantity_available"] = product_available(product)
    return product["quantity_available"]


def recompute_product_committed(product):
    """quantity_committed is the summed quantity of RESERVED/STAGED/DELIVERED rows."""
    total = 0
    for alloc in db.allocations.values():
        if alloc["product_id"] != product["id"]:
            continue
        if alloc["status"] in ("RESERVED", "STAGED", "DELIVERED"):
            total += alloc["quantity"]
    product["quantity_committed"] = total
    recompute_product_available(product)
    return total


# ---------------------------------------------------------------------------
# order line rollups
# ---------------------------------------------------------------------------

def line_quantity_allocated(line):
    total = 0
    for alloc in db.allocations.values():
        if alloc["order_line_id"] != line["id"]:
            continue
        if alloc["status"] == "REVERSED":
            continue
        total += alloc["quantity"]
    return total


def line_quantity_delivered(line):
    total = 0
    for alloc in db.allocations.values():
        if alloc["order_line_id"] == line["id"]:
            total += alloc["delivered_quantity"]
    return total


def line_quantity_rejected(line):
    total = 0
    for alloc in db.allocations.values():
        if alloc["order_line_id"] == line["id"]:
            total += alloc["rejected_quantity"]
    return total


# ---------------------------------------------------------------------------
# dock occupancy (calculations.dock_slot_occupancy)
# ---------------------------------------------------------------------------

def slot_pallets_booked(slot):
    total = 0
    for appt in db.appointments.values():
        if appt["dock_slot_id"] != slot["id"]:
            continue
        if appt["status"] in ("BOOKED", "RECEIVED"):
            total += appt["pallets"]
    return total


def slot_status(slot):
    if now() >= slot["window_end"]:
        return "CLOSED"
    if slot_pallets_booked(slot) >= slot["pallet_capacity"]:
        return "FULL"
    return "OPEN"


def refresh_slot(slot):
    slot["pallets_booked"] = slot_pallets_booked(slot)
    slot["status"] = slot_status(slot)


# ---------------------------------------------------------------------------
# route rollups
# ---------------------------------------------------------------------------

def route_stop_count(route):
    return len([o for o in db.orders.values() if o.get("route_id") == route["id"]])


def route_pallets_loaded(route):
    return sum(o["order_pallets"] for o in db.orders.values() if o.get("route_id") == route["id"])


def refresh_route_counts(route):
    route["stop_count"] = route_stop_count(route)
    route["pallets_loaded"] = route_pallets_loaded(route)


# ---------------------------------------------------------------------------
# pallets
# ---------------------------------------------------------------------------

def allocation_pallets(allocation):
    product = allocation_product(allocation)
    if product is None:
        return 0
    return ceil_div(allocation["quantity"], product["units_per_pallet"])


def now_instant():
    return now()
