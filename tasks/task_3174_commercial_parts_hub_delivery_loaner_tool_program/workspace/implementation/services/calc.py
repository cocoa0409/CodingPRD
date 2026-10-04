"""The eleven calculation rules of SCAFFOLD section 1.3.

Every monetary figure is an integer number of cents; round_half_up is applied
at exactly the points the formulas name and nowhere else; ceil() appears only
where a formula names it.  Nothing here reads the wall clock -- the logical
clock is the only time source.
"""

from datetime import timedelta

import db
from errors import ApiError
from money import round_ceil, round_half_up, to_decimal
from services import common
from timeutil import at_hour, midnight_of

TIER_BANDS = {
    "BRONZE": {"discount_rate": "0.00", "promise_multiplier": "1.00"},
    "SILVER": {"discount_rate": "0.05", "promise_multiplier": "0.80"},
    "GOLD": {"discount_rate": "0.10", "promise_multiplier": "0.60"},
    "PLATINUM": {"discount_rate": "0.15", "promise_multiplier": "0.50"},
}

BASE_FRACTION = "0.015"
GROWTH_RATE = "0.20"
SATURATION_CEILING = 1200

DELIVERY_FEE_CENTS = 795

SHOP_DELIVERY_RADIUS_MILES = 15
EXTENDED_RADIUS_MILES = 35
HUB_DELIVERY_MINUTES = 60
MEGA_HUB_DELIVERY_MINUTES = 90
CUTOFF_CUSHION = 120

REFUNDABLE_RATE = "0.20"
CORE_PORTION_RATE_A = "0.60"
CORE_PORTION_RATE_B = "0.30"
RESTOCKING_RATE = "0.15"

DEPOSIT_FRACTION = "0.20"

BASE_CENTS = 500
STANDARD_RATE_CENTS = 40
LONG_RUN_RATE_CENTS = 20
LONG_RUN_MILES = 40
OWNED_SHARE = "0.35"
MIN_OWNED_CREDIT_CENTS = 150

AGING_GRACE_DAYS = 30

PLACEMENT_RANK = {"FRONT": 1, "REAR_LEFT": 1, "REAR_RIGHT": 2, "OTHER": 3}

WEAR_BAND_TABLE = {
    "LEVEL_1": {"threshold": "0.0", "multiplier": 1.00, "forfeiture": 0.00, "grace": 48},
    "LEVEL_2": {"threshold": "25.0", "multiplier": 1.20, "forfeiture": 0.40, "grace": 36},
    "LEVEL_3": {"threshold": "45.0", "multiplier": 1.45, "forfeiture": 0.60, "grace": 24},
    "LEVEL_4": {"threshold": "65.0", "multiplier": 1.70, "forfeiture": 0.80, "grace": 18},
    "LEVEL_5": {"threshold": "85.0", "multiplier": 2.00, "forfeiture": 1.00, "grace": 12},
}

WEAR_BAND_ORDER = ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4", "LEVEL_5"]


# ---------------------------------------------------------------------------
# 1. tier_line_price
# ---------------------------------------------------------------------------

def pricing_band_for(member_sequence):
    """The band is a step function of the account's order_sequence captured at
    creation (PartOrder.member_sequence), never a marginal schedule."""
    if member_sequence is None:
        return "BRONZE"
    if member_sequence <= 2:
        return "BRONZE"
    if member_sequence <= 5:
        return "SILVER"
    if member_sequence <= 7:
        return "GOLD"
    return "PLATINUM"


def band_rate(band):
    return TIER_BANDS.get(band, TIER_BANDS["BRONZE"])["discount_rate"]


def band_multiplier(band):
    return TIER_BANDS.get(band, TIER_BANDS["BRONZE"])["promise_multiplier"]


def resolved_line_list_cents(line):
    """list_price_cents of the line's terminal current part."""
    part = db.parts.get(line.get("part_id"))
    if part is None:
        return 0
    terminal = common.resolve_current(part["id"]) or part
    return terminal.get("list_price_cents", 0)


def resolved_line_part(line):
    part = db.parts.get(line.get("part_id"))
    if part is None:
        return None
    return common.resolve_current(part["id"]) or part


def price_order(order):
    """Recompute a price from the order's lines and its frozen member_sequence.

    DRAFT/CONFIRMED take the provisional reading, with each line rounded
    independently; ALLOCATED and beyond take the final reading, with the
    discount re-based on one order-level rounding of the summed list amount.
    """
    band = order.get("pricing_band") or pricing_band_for(order.get("member_sequence"))
    rate = to_decimal(band_rate(band))
    lines = order.get("line_items") or []

    provisional_subtotal = 0
    provisional_discount = 0
    total_list = 0
    core_total = 0
    for line in lines:
        list_cents = resolved_line_list_cents(line)
        quantity = line.get("quantity") or 0
        line_discount = round_half_up(to_decimal(list_cents) * rate)
        unit_price = list_cents - line_discount
        provisional_subtotal += unit_price * quantity
        provisional_discount += line_discount * quantity
        total_list += list_cents * quantity
        part = resolved_line_part(line)
        core_charge = part.get("core_charge_cents", 0) if part else 0
        core_total += core_charge * quantity

    status = order.get("status")
    if status in ("DRAFT", "CONFIRMED", None):
        # provisional reading: each line is rounded independently and the
        # per-line unit price is written back onto the line
        for line in lines:
            list_cents = resolved_line_list_cents(line)
            line_discount = round_half_up(to_decimal(list_cents) * rate)
            line["unit_price_cents"] = list_cents - line_discount
        order["parts_subtotal_cents"] = provisional_subtotal
        order["tier_discount_cents"] = provisional_discount
    else:
        # final reading: unit_price_cents is NOT rewritten, so it keeps its
        # provisional per-line value and deliberately disagrees with the
        # order-level subtotal
        final_discount = round_half_up(to_decimal(total_list) * rate)
        order["tier_discount_cents"] = final_discount
        order["parts_subtotal_cents"] = total_list - final_discount

    order["core_charge_total_cents"] = core_total
    return order


# ---------------------------------------------------------------------------
# 2. order_satisfaction
# ---------------------------------------------------------------------------

def compute_order_base(lines):
    """Computed ONCE at creation from the creation-time line basket, then stored."""
    total = 0
    for line in lines:
        list_cents = resolved_line_list_cents(line)
        total += list_cents * (line.get("quantity") or 0)
    return round_half_up(to_decimal(total) * to_decimal(BASE_FRACTION))


def compute_satisfaction(order):
    base = order.get("order_base_cents") or 0
    member_sequence = order.get("member_sequence") or 1
    factor = to_decimal(1) + to_decimal(member_sequence) * to_decimal(GROWTH_RATE)
    incremental = round_half_up(to_decimal(base) * factor)
    order["satisfaction_cents"] = min(incremental, SATURATION_CEILING)
    return order["satisfaction_cents"]


# ---------------------------------------------------------------------------
# 3. delivery_fee_schedule
# ---------------------------------------------------------------------------

def delivery_fee(route, service_level):
    """Free when the route is exactly STORE, or exactly HUB with a service
    level of exactly HUB_DAILY.  Exact-string on both sides."""
    if route == "STORE":
        return 0
    if route == "HUB" and service_level == "HUB_DAILY":
        return 0
    return DELIVERY_FEE_CENTS


# ---------------------------------------------------------------------------
# 4. source_promise
# ---------------------------------------------------------------------------

def store_chain(home_store):
    """Resolve SATELLITE -> hub -> mega_hub -> DC from the account's home store."""
    chain = {"satellite": None, "hub": None, "mega_hub": None, "dc": None}
    if home_store is None:
        return chain
    store_type = home_store.get("store_type")
    if store_type == "SATELLITE":
        chain["satellite"] = home_store
        hub = db.stores.get(home_store.get("hub_store_id"))
        chain["hub"] = hub
        if hub is not None:
            mega = db.stores.get(hub.get("hub_store_id"))
            chain["mega_hub"] = mega
            if mega is not None:
                chain["dc"] = db.stores.get(mega.get("hub_store_id"))
    elif store_type == "HUB":
        chain["hub"] = home_store
        mega = db.stores.get(home_store.get("hub_store_id"))
        chain["mega_hub"] = mega
        if mega is not None:
            chain["dc"] = db.stores.get(mega.get("hub_store_id"))
    elif store_type == "MEGA_HUB":
        chain["mega_hub"] = home_store
        chain["dc"] = db.stores.get(home_store.get("hub_store_id"))
    elif store_type == "DC":
        chain["dc"] = home_store
    return chain


ROUTE_OF_TYPE = {
    "SATELLITE": "STORE",
    "HUB": "HUB",
    "MEGA_HUB": "MEGA_HUB",
    "DC": "DC",
}


def source_promise(account, lines, request_at, provisional=False):
    """Evaluate the eight routing bands in order; the first match wins.

    Returns (route, source_store_id, source_store, promised_at, source_days).
    """
    home_store = db.stores.get(account.get("home_store_id"))
    chain = store_chain(home_store)
    band = account.get("pricing_band") or pricing_band_for(1)
    line = lines[0] if lines else {}
    quantity = line.get("quantity") or 0
    part_id = None
    resolved = resolved_line_part(line) if line else None
    if resolved is not None:
        part_id = resolved["id"]

    radius = None
    if home_store is not None:
        radius = home_store.get("delivery_radius_miles")
    if radius is None:
        radius = 0

    cutoff_at = None
    if home_store is not None:
        hour = home_store.get("cutoff_hour_local")
        if hour is None:
            hour = 15
        cutoff_at = at_hour(request_at, int(hour))
    buffer_minutes = 30
    if home_store is not None and home_store.get("cutoff_buffer_minutes") is not None:
        buffer_minutes = int(home_store["cutoff_buffer_minutes"])

    def stock_ok(store):
        if store is None or part_id is None:
            return False
        return common.available_units(store["id"], part_id) >= quantity

    def capacity_ok(store):
        if store is None:
            return False
        committed = store.get("committed_units_today", 0) or 0
        limit = store.get("daily_capacity_units")
        if limit is None:
            return True
        return committed + quantity <= limit

    satellite = chain["satellite"]
    hub = chain["hub"]
    mega_hub = chain["mega_hub"]
    dc = chain["dc"]

    within_shop = radius <= SHOP_DELIVERY_RADIUS_MILES
    within_extended = radius <= EXTENDED_RADIUS_MILES

    if within_shop:
        # band 1 -- the shop's own satellite store.  PRD 3.4: the provisional
        # reading "is evaluated when the order is created, against the home
        # store's live availability, and may route to the home store while
        # stock is still unpromised"; the ceiling itself is re-checked after
        # reservation at confirmation (PRD 3.3), so the draft reading does not
        # consult the committed counter.
        if (satellite is not None and cutoff_at is not None
                and request_at <= cutoff_at - timedelta(minutes=buffer_minutes)
                and stock_ok(satellite)
                and (provisional or capacity_ok(satellite))):
            return _promise_result("STORE", satellite, band, request_at, 0)
        # band 2 -- the hub
        if (hub is not None and cutoff_at is not None and stock_ok(hub)
                and cutoff_at >= request_at
                and cutoff_at + timedelta(minutes=CUTOFF_CUSHION)
                >= request_at + timedelta(minutes=HUB_DELIVERY_MINUTES)):
            return _promise_result("HUB", hub, band, request_at, 0)
        # band 3 -- the mega-hub
        if (mega_hub is not None and cutoff_at is not None and stock_ok(mega_hub)
                and cutoff_at >= request_at
                and cutoff_at + timedelta(minutes=CUTOFF_CUSHION)
                >= request_at + timedelta(minutes=MEGA_HUB_DELIVERY_MINUTES)):
            return _promise_result("MEGA_HUB", mega_hub, band, request_at, 0)
        # band 4 -- the distribution center
        if (dc is not None and cutoff_at is not None and stock_ok(dc)
                and cutoff_at >= request_at):
            return _promise_result("DC", dc, band, request_at, 1)
    if within_extended:
        # band 5
        if hub is not None and stock_ok(hub):
            return _promise_result("HUB", hub, band, request_at, 1)
        # band 6
        if mega_hub is not None and stock_ok(mega_hub):
            return _promise_result("MEGA_HUB", mega_hub, band, request_at, 1)
        # band 7
        if dc is not None and stock_ok(dc):
            return _promise_result("DC", dc, band, request_at, 2)
    # band 8 -- nothing routes
    return "UNROUTABLE", None, None, None, None


def promised_for(account, store, request_at, source_days):
    """The published promise instant for a chosen source store (PRD 3.4)."""
    band = account.get("pricing_band") or pricing_band_for(1)
    return _promise_result(calc_route_of(store), store, band, request_at, source_days)[3]


def calc_route_of(store):
    return ROUTE_OF_TYPE.get(store.get("store_type"), "STORE")


def _promise_result(route, store, band, request_at, source_days):
    store_type = store.get("store_type")
    promise_multiplier = "1.00"
    if store_type in ("SATELLITE", "HUB"):
        promise_multiplier = band_multiplier(band)
    base_minutes = store.get("promise_time_minutes") or 0
    advance = round_half_up(to_decimal(base_minutes) * to_decimal(promise_multiplier))
    promised = midnight_of(request_at + timedelta(days=source_days)).replace(hour=8)
    promised = promised + timedelta(minutes=advance)
    return route, store["id"], store, promised, source_days


def source_store_of(order):
    """The store the order reserved against, recovered from its source id."""
    return db.stores.get(order.get("source_store_id"))


# ---------------------------------------------------------------------------
# 5. core_credit
# ---------------------------------------------------------------------------

def warranty_covered_for(core_return, at_instant):
    """Pinned at inspection.  No match on claim_reference and no match on
    purchase_order_id: a credit is issued whether or not a receipt exists."""
    account_id = core_return.get("account_id")
    candidate_part_ids = set()
    for line in core_return.get("line_items") or []:
        for chain_id in common.chain_parts(line.get("part_id")):
            candidate_part_ids.add(chain_id)
    for registration in db.warranty_registrations.values():
        if registration.get("account_id") != account_id:
            continue
        if registration.get("part_id") not in candidate_part_ids:
            continue
        expires = _parse(registration.get("warranty_expires_at"))
        if expires is not None and expires >= at_instant:
            return True
    return False


def core_credit(core_return, order, at_instant):
    core_subtotal = core_return.get("core_subtotal_cents") or 0
    headroom = (order.get("refundable_deposit_cents") or 0) - \
        (order.get("refundable_deposit_consumed_cents") or 0)
    computed_refundable = round_half_up(to_decimal(core_subtotal) * to_decimal(REFUNDABLE_RATE))
    refundable_portion = min(computed_refundable, headroom)
    if refundable_portion < 0:
        refundable_portion = 0

    term_a = round_ceil(to_decimal(core_subtotal) * to_decimal(CORE_PORTION_RATE_A))
    term_b = round_ceil(to_decimal(order.get("core_charge_total_cents") or 0)
                        * to_decimal(CORE_PORTION_RATE_B))
    core_charge_portion = max(term_a, term_b)

    covered = core_return.get("warranty_covered")
    if covered:
        restocking_fee = 0
    else:
        restocking_fee = round_half_up(to_decimal(core_charge_portion)
                                       * to_decimal(RESTOCKING_RATE))
    core_charge_credit = core_charge_portion - restocking_fee
    return {
        "core_subtotal_cents": core_subtotal,
        "refundable_portion_cents": refundable_portion,
        "core_charge_portion_cents": core_charge_portion,
        "restocking_fee_cents": restocking_fee,
        "core_charge_credit_cents": core_charge_credit,
        "credit_amount_cents": refundable_portion + core_charge_credit,
    }


# ---------------------------------------------------------------------------
# 6. ordered_quantity_credit
# ---------------------------------------------------------------------------

def ordered_quantity_credit(core_return, order):
    """The entitlement as a function of what the account bought.  Not capped."""
    order_quantities = {}
    for line in order.get("line_items") or []:
        part = resolved_line_part(line)
        if part is None:
            continue
        order_quantities[part["id"]] = order_quantities.get(part["id"], 0) + \
            (line.get("quantity") or 0)
        for chain_id in common.chain_parts(part["id"]):
            order_quantities.setdefault(chain_id, 0)
            order_quantities[chain_id] += line.get("quantity") or 0

    total = 0
    for line in core_return.get("line_items") or []:
        part = common.resolve_current(line.get("part_id"))
        if part is None:
            continue
        matched = min(line.get("quantity") or 0, order_quantities.get(part["id"], 0))
        total += (part.get("core_charge_cents") or 0) * matched
    return total


def core_subtotal_of(lines):
    total = 0
    for line in lines:
        part = common.resolve_current(line.get("part_id"))
        if part is None:
            continue
        total += (part.get("core_charge_cents") or 0) * (line.get("quantity") or 0)
    return total


# ---------------------------------------------------------------------------
# 7. refundable_deposit_amount
# ---------------------------------------------------------------------------

def refundable_deposit_for(order, account_id):
    """The order-level core subtotal rounded ONCE, plus the deposits of every
    tool loan on the account attached to this order."""
    core_total = order.get("core_charge_total_cents") or 0
    base = round_half_up(to_decimal(core_total) * to_decimal(DEPOSIT_FRACTION))
    attached = 0
    for loan in db.tool_loans.values():
        if loan.get("account_id") != account_id:
            continue
        if loan.get("loaned_order_id") != order["id"]:
            continue
        attached += loan.get("deposit_amount_cents") or 0
    return base + attached


# ---------------------------------------------------------------------------
# 8. route_run_credit
# ---------------------------------------------------------------------------

def route_run_credit(route):
    total_miles = route.get("total_miles") or 0
    if route.get("driver_type") == "AFFILIATE":
        if float(total_miles) >= LONG_RUN_MILES:
            rate = LONG_RUN_RATE_CENTS
        else:
            rate = STANDARD_RATE_CENTS
        return BASE_CENTS + rate * round_half_up(to_decimal(total_miles))
    attributed = 0
    for stop in common.stops_of(route["id"]):
        if stop.get("status") != "DELIVERED":
            continue
        for order_id in stop.get("order_ids") or []:
            order = db.part_orders.get(order_id)
            if order is None:
                continue
            attributed += order.get("delivery_fee_cents") or 0
    share = round_half_up(to_decimal(attributed) * to_decimal(OWNED_SHARE))
    return max(share, MIN_OWNED_CREDIT_CENTS)


def compute_total_miles(route):
    """Route mileage: the travel legs plus a fixed hop per drop."""
    stops = [stop for stop in common.stops_of(route["id"])
             if stop.get("status") != "REJECTED"]
    stops = sorted(stops, key=lambda s: (s.get("stop_sequence") or 0))
    miles = 0.0
    for stop in stops:
        miles += float(stop.get("travel_minutes_from_previous") or 0) / 5.0
        miles += float(stop.get("drop_minutes") or 0) / 10.0
    return miles


# ---------------------------------------------------------------------------
# 9. replacement_selection
# ---------------------------------------------------------------------------

def _placement_rank(fitment):
    return PLACEMENT_RANK.get(fitment.get("placement"), 3)


def select_replacement(tool_catalog_id, home_store_id, fallback_part_id):
    """The two candidate-set levels are NOT interchangeable.

    level == 2 -> catalogue level (2a, 2b, 2c)
    level == 1 -> loan level (1a, 1b, 1c)
    """
    return _select(tool_catalog_id, home_store_id, fallback_part_id)


def _candidates_with_stock(tool_catalog_id, home_store_id):
    return _candidates(tool_catalog_id, home_store_id, require_stock=True)


def _candidates_without_stock(tool_catalog_id, home_store_id):
    return _candidates(tool_catalog_id, home_store_id, require_stock=False)


def _candidates(tool_catalog_id, home_store_id, require_stock):
    out = []
    for fitment in db.tool_fitments.values():
        if fitment.get("tool_catalog_id") != tool_catalog_id:
            continue
        part = db.parts.get(fitment.get("part_id"))
        if part is None or part.get("catalog_state") != "ACTIVE":
            continue
        if require_stock:
            if home_store_id is None:
                continue
            if common.available_units(home_store_id, part["id"]) <= 0:
                continue
        out.append((fitment, part))
    return out


def _select(tool_catalog_id, home_store_id, fallback_part_id):
    for candidates in (
        _candidates_with_stock(tool_catalog_id, home_store_id),
        _candidates_without_stock(tool_catalog_id, home_store_id),
    ):
        if candidates:
            candidates.sort(key=lambda pair: (
                _placement_rank(pair[0]),
                pair[0].get("depth_index") if pair[0].get("depth_index") is not None else 0,
                pair[1].get("list_price_cents") or 0,
                pair[1].get("created_at") or "",
            ))
            return candidates[0][1]["id"]
    if fallback_part_id and db.parts.get(fallback_part_id) is not None:
        return fallback_part_id
    return None


# ---------------------------------------------------------------------------
# 10. account_posture_derivation
# ---------------------------------------------------------------------------

def _parse(value):
    from timeutil import parse_iso
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return parse_iso(value)
    except ValueError:
        return None


def oldest_due_at(account_id):
    oldest = None
    for order in db.part_orders.values():
        if order.get("account_id") != account_id:
            continue
        due = _parse(order.get("delivered_payment_due_at"))
        if due is None:
            continue
        if oldest is None or due < oldest:
            oldest = due
    return oldest


def derive_account_posture(account, at_instant=None):
    """CLOSED first, then the ON_HOLD stickiness, then the aging test."""
    if at_instant is None:
        at_instant = db.clock()
    posture = account.get("account_posture")
    if posture == "CLOSED":
        return posture
    receivable = account.get("receivable_balance_cents") or 0
    terms = account.get("credit_terms_days") or 0
    attached = to_decimal(terms) + to_decimal(AGING_GRACE_DAYS)
    oldest = oldest_due_at(account["id"])
    aging = (receivable > 0 and oldest is not None
             and oldest < at_instant - timedelta(days=float(attached)))
    if posture == "ON_HOLD" and not aging:
        return posture
    if aging:
        return "CREDIT_SUSPENDED"
    return "OPEN"


def status_needed_at(account):
    oldest = oldest_due_at(account["id"])
    if oldest is None:
        return None
    terms = account.get("credit_terms_days") or 0
    return oldest + timedelta(days=terms + AGING_GRACE_DAYS)


# ---------------------------------------------------------------------------
# 11. stop_sequence_derivation
# ---------------------------------------------------------------------------

def derive_route_geometry(route):
    """Order the non-REJECTED stops, assign stop_sequence and walk the
    projection chain.  The stop identifier is never a key."""
    stops = [stop for stop in common.stops_of(route["id"])
             if stop.get("status") != "REJECTED"]
    stops.sort(key=lambda stop: (stop.get("delivery_window_start") or "",
                                 stop.get("created_at") or ""))
    departure = _parse(route.get("departure_at"))

    effective = departure
    return_desks = [stop for stop in stops if stop.get("stop_kind") == "RETURN_DESK"]
    if return_desks:
        latest = None
        for stop in return_desks:
            window_start = _parse(stop.get("delivery_window_start"))
            if window_start is None:
                continue
            if latest is None or window_start > latest:
                latest = window_start
        if latest is not None and departure is not None and latest > departure:
            effective = latest
    route["effective_departure_at"] = _fmt(effective)

    previous_departure = effective
    last_departure = None
    for index, stop in enumerate(stops):
        stop["stop_sequence"] = index + 1
        travel = stop.get("travel_minutes_from_previous") or 0
        arrival = _add_minutes(previous_departure, travel)
        drop = stop.get("drop_minutes") or 0
        projected_departure = _add_minutes(arrival, drop)
        window_end = _parse(stop.get("delivery_window_end"))
        lateness = 0
        if window_end is not None and projected_departure is not None:
            delta = (projected_departure - window_end).total_seconds()
            lateness = max(0, int(delta // 60))
        stop["projected_arrival_at"] = _fmt(arrival)
        stop["projected_departure_at"] = _fmt(projected_departure)
        stop["lateness_minutes"] = lateness
        previous_departure = projected_departure
        last_departure = projected_departure
        common.record_audit(stop)

    for stop in common.stops_of(route["id"]):
        if stop.get("status") == "REJECTED":
            stop["stop_sequence"] = None
            stop["projected_arrival_at"] = None
            stop["projected_departure_at"] = None
            stop["lateness_minutes"] = 0

    route["return_at"] = _fmt(last_departure if last_departure is not None else departure)
    return route


def _add_minutes(dt, minutes):
    if dt is None:
        return None
    return dt + timedelta(minutes=minutes)


def _fmt(dt):
    from timeutil import format_iso
    return format_iso(dt)


def literal_wear_band(wear_accumulated):
    """The band the accumulated wear has reached (a non-decreasing reading)."""
    wear = float(wear_accumulated or 0)
    band = "LEVEL_1"
    for name in WEAR_BAND_ORDER:
        if wear >= float(WEAR_BAND_TABLE[name]["threshold"]):
            band = name
    return band


def band_index(name):
    try:
        return WEAR_BAND_ORDER.index(name)
    except ValueError:
        return 0


def wear_values(band):
    entry = WEAR_BAND_TABLE.get(band, WEAR_BAND_TABLE["LEVEL_1"])
    return entry["multiplier"], entry["forfeiture"], entry["grace"]


def wear_intensity(wear_accumulated):
    """A read-only integer 0-100 derived from the tool's accumulated wear."""
    value = int(round(float(wear_accumulated or 0) * 100))
    if value < 0:
        value = 0
    if value > 100:
        value = 100
    return value


# ---------------------------------------------------------------------------
# loan inspection severity
# ---------------------------------------------------------------------------

CONDITION_BASE_FORFEITURE = {
    "GOOD": 0.00,
    "WORN": 0.40,
    "BROKEN": 0.80,
    "LOST": 1.00,
}

CONDITION_DAMAGE_MULTIPLIER = {
    "GOOD": 1.00,
    "WORN": 1.00,
    "BROKEN": 1.50,
    "LOST": 1.00,
}


def condition_readings(tool, condition):
    """wear_intensity, damage_multiplier and the severity-band forfeiture rate.

    The severity band is the return condition: a GOOD return retains nothing,
    WORN retains 0.40, BROKEN 0.80 and LOST the whole deposit.  A worn or
    broken return also retains at least the tool's own wear-band retention, so
    a heavily worn tool never refunds more than its band allows."""
    wear = tool.get("wear_accumulated") or 0
    intensity = wear_intensity(wear)
    multiplier = CONDITION_DAMAGE_MULTIPLIER.get(condition, 1.00)
    rate = to_decimal(CONDITION_BASE_FORFEITURE.get(condition, 0.00))
    if condition == "LOST":
        # PRD 3.6: "If every candidate set at every level is empty, the loan's
        # `replacement_part_id` stays null, no replacement is offered, and the
        # tool's deposit is retained in full, with the loan's `forfeiture_rate`
        # pinned to 1.00."  A lost tool is never offered a replacement, so its
        # deposit is likewise retained in full even when the selector could have
        # named one.
        rate = to_decimal(1.00)
    elif condition != "GOOD":
        wear_rate = to_decimal(wear_values(tool.get("wear_band"))[1])
        if wear_rate > rate:
            rate = wear_rate
    return intensity, multiplier, rate


def pin_wear_band(tool):
    """Advance the band only when a threshold has actually been crossed."""
    band = tool.get("wear_band") or "LEVEL_1"
    reached = literal_wear_band(tool.get("wear_accumulated"))
    if band_index(reached) > band_index(band):
        tool["wear_band"] = reached
        multiplier, forfeiture, grace = wear_values(reached)
        tool["wear_multiplier_rate"] = multiplier
        tool["wear_forfeiture_rate"] = forfeiture
        tool["wear_grace_period_hours"] = grace
        return True
    multiplier, forfeiture, grace = wear_values(band)
    tool["wear_multiplier_rate"] = multiplier
    tool["wear_forfeiture_rate"] = forfeiture
    tool["wear_grace_period_hours"] = grace
    return False


def apply_wear_band_side_effects(tool, account_id):
    """Re-select the catalogue replacement part and refresh every open loan."""
    previous = tool.get("replacement_part_id")
    selected = select_replacement(tool["id"], account_id, previous)
    tool["replacement_part_id"] = selected
    for loan in db.tool_loans.values():
        if loan.get("tool_catalog_id") != tool["id"]:
            continue
        if loan.get("status") in ("CHECKED_OUT", "IN_USE", "DUE", "OVERDUE"):
            loan["replacement_part_id"] = selected
            common.record_audit(loan)
    if tool.get("wear_band") == "LEVEL_5":
        for loan in db.tool_loans.values():
            if loan.get("tool_catalog_id") != tool["id"]:
                continue
            if loan.get("status") in ("REQUESTED", "CHECKED_OUT", "IN_USE", "DUE", "OVERDUE"):
                loan["status"] = "CHECKED_OUT"
                loan["due_at"] = db.clock_iso()
                common.record_audit(loan)
    return selected