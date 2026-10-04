"""Domain logic: cutoffs, sweeps, pricing, allocation, cascades."""

import datetime
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError

# ---------------------------------------------------------------------------
# constants (PRD section 3)
# ---------------------------------------------------------------------------
COMPANY_MARKUP_PCT = 18
FRANCHISE_MARKUP_PCT = 12
ARTISAN_PRICE_FLOOR = Decimal("4.00")
CONVENTIONAL_PRICE_FLOOR = Decimal("3.50")
ARTISAN_UNIT_WEIGHT = 2
CONVENTIONAL_UNIT_WEIGHT = 1
DONATION_CREDIT_RATE = Decimal("0.25")
FRANCHISE_BURDEN_SHARE = Decimal("0.60")
COMPANY_BURDEN_SHARE = Decimal("0.45")

TERMINAL_STOP_STATES = ("ON_TIME", "LATE", "MISSED", "CANCELLED")
TERMINAL_ORDER_STATES = ("DELIVERED", "SHIPPED_SHORT", "CANCELLED")
ORDER_RECOMPUTE_STATES = ("DRAFT", "SUBMITTED", "LOCKED")


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def get_or_404(collection, entity_id, label="Resource"):
    row = collection.get(entity_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "%s not found." % label)
    return row


def parse_date(value):
    return datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


def hhmm_minutes(value):
    return int(value[0:2]) * 60 + int(value[3:5])


# ---------------------------------------------------------------------------
# order cutoff / auto-lock sweep
# ---------------------------------------------------------------------------
def cutoff_instant(dough_type, production_date):
    """The cafe-local cutoff instant: HH:MM on the day before production_date."""
    day = parse_date(production_date) - datetime.timedelta(days=1)
    minutes = hhmm_minutes(dough_type["order_cutoff_local"])
    return datetime.datetime(day.year, day.month, day.day) + datetime.timedelta(minutes=minutes)


def cutoff_passed(dough_type, production_date):
    return db.now_dt() >= cutoff_instant(dough_type, production_date)


def sweep_autolock():
    """Move every still-SUBMITTED order whose cutoff has arrived into LOCKED."""
    now = db.now_dt()
    for order in db.cafe_orders.values():
        if order["status"] != "SUBMITTED":
            continue
        dough_type = db.dough_types.get(order["dough_type_id"])
        if dough_type is None:
            continue
        if now >= cutoff_instant(dough_type, order["production_date"]):
            order["status"] = "LOCKED"
            db.touch(order)


# ---------------------------------------------------------------------------
# demand adjustments
# ---------------------------------------------------------------------------
def active_adjustment(cafe_id, production_date):
    for adj in db.demand_adjustments.values():
        if (adj["cafe_id"] == cafe_id and adj["production_date"] == production_date
                and adj["status"] == "ACTIVE"):
            return adj
    return None


def compute_adjusted_quantity(quantity, cafe_id, production_date):
    adj = active_adjustment(cafe_id, production_date)
    if adj is None:
        return quantity
    scaled = (quantity * (100 + adj["demand_delta_pct"])) // 100
    return max(0, scaled)


def recompute_affected_orders(cafe_id, production_date):
    for order in db.cafe_orders.values():
        if (order["cafe_id"] == cafe_id and order["production_date"] == production_date
                and order["status"] in ORDER_RECOMPUTE_STATES):
            order["adjusted_quantity"] = compute_adjusted_quantity(
                order["quantity"], cafe_id, production_date)
            db.touch(order)


# ---------------------------------------------------------------------------
# transfer pricing
# ---------------------------------------------------------------------------
def unit_price(dough_type, cafe):
    """Rounded-half-up 2dp unit price after ownership markup and category floor."""
    markup = COMPANY_MARKUP_PCT if cafe["ownership_type"] == "COMPANY" else FRANCHISE_MARKUP_PCT
    base = Decimal(str(dough_type["flat_transfer_price"]))
    price = (base * (Decimal(100 + markup) / Decimal(100))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    floor = ARTISAN_PRICE_FLOOR if dough_type["category"] == "ARTISAN" else CONVENTIONAL_PRICE_FLOOR
    if price < floor:
        price = floor
    return price


def unit_price_cents(dough_type, cafe):
    return int(unit_price(dough_type, cafe) * 100)


def provisional_invoice_cents(dough_type, cafe, quantity):
    """Submit-time projection: rounded unit price x requested quantity."""
    return unit_price_cents(dough_type, cafe) * quantity


def final_invoice_cents(dough_type, cafe, actual_quantity):
    """Close-time authoritative invoice: rounded unit price x actual quantity."""
    return unit_price_cents(dough_type, cafe) * actual_quantity


# ---------------------------------------------------------------------------
# production plans
# ---------------------------------------------------------------------------
def plan_orders(plan):
    return [o for o in db.sorted_rows(db.cafe_orders) if o.get("_plan_id") == plan["id"]]


def order_effective_units(order):
    dough_type = db.dough_types.get(order["dough_type_id"])
    weight = ARTISAN_UNIT_WEIGHT if (dough_type and dough_type["category"] == "ARTISAN") \
        else CONVENTIONAL_UNIT_WEIGHT
    return order["adjusted_quantity"] * weight


def recompute_plan_totals(plan):
    total = 0
    for order in plan_orders(plan):
        if order["status"] == "CANCELLED":
            continue
        total += order_effective_units(order)
    plan["total_effective_units"] = total
    facility = db.facilities.get(plan["facility_id"])
    plan["over_capacity"] = bool(facility) and total > facility["effective_capacity_units"]


# ---------------------------------------------------------------------------
# routes and stops
# ---------------------------------------------------------------------------
def route_stops(route):
    return [s for s in db.sorted_rows(db.route_stops) if s["route_id"] == route["id"]]


def stop_orders(stop):
    """ROUTED orders served by this stop: same cafe, same production date."""
    route = db.delivery_routes.get(stop["route_id"])
    if route is None:
        return []
    return [o for o in db.sorted_rows(db.cafe_orders)
            if o["cafe_id"] == stop["cafe_id"]
            and o["production_date"] == route["production_date"]
            and o["status"] == "ROUTED"]


def maybe_complete_route(route):
    stops = route_stops(route)
    if stops and all(s["status"] in TERMINAL_STOP_STATES for s in stops):
        if route["status"] == "IN_TRANSIT":
            route["status"] = "COMPLETED"
            db.touch(route)
