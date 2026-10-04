"""Every calculation rule from the spec, plus the aggregate recomputations."""

import math
from decimal import Decimal, ROUND_HALF_UP

from db import parse_iso, trunc_minutes

PROVISIONAL_CUSTODY = {"ACCEPTED", "SCREENING", "SORTED", "IN_MAKEUP"}
FINAL_CUSTODY = {"LOADED", "DELIVERED", "OFFLOADED"}
ACTIVE_CUSTODY = {"ACCEPTED", "SCREENING", "SORTED", "IN_MAKEUP", "LOADED", "HELD"}

ITEM_BASE_FEE_CENTS = {
    "OVERSIZE": 4500,
    "FRAGILE": 6725,
    "SPORTS_EQUIPMENT": 11250,
    "MOBILITY_DEVICE": 0,
}

ROUTING_CLASS_POINTS = {"STANDARD": 0, "BULK_HOLD": 40, "MANUAL": 80}
CONNECTION_CLASS_POINTS = {
    "NONE": 0, "PENDING": 20, "CONFIRMED": 50, "RUSH": 150,
    "REACCOMMODATED": 150, "MISSED": 0,
}
REPORT_TYPE_FRACTION = {"DELAYED": "0.00", "DAMAGED": "0.50", "LOST": "0.75", "PILFERED": "0.60"}


def rhu(value, places=0):
    """round_half_up to `places` decimals, returned as an int."""
    if value is None:
        return 0
    quant = Decimal(1).scaleb(-places)
    return int(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def whole_pounds(value):
    return rhu(value, 0)


# ------------------------------------------------------------------ lookups --
def flight_of(store, bag):
    if not bag or not bag.get("flight_id"):
        return None
    return store.flights.get(bag["flight_id"])


def airline_of_bag(store, bag):
    flight = flight_of(store, bag)
    if not flight:
        return None
    return store.airlines.get(flight.get("airline_id"))


def station_of(store, bag):
    if not bag:
        return None
    return store.stations.get(bag.get("station_id"))


def special_items_of(store, bag_id):
    return [row for row in store.special_items.values() if row["bag_id"] == bag_id]


def connection_of(store, bag_id):
    rows = [r for r in store.connections.values() if r["bag_id"] == bag_id]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    return rows[0]


def scans_of(store, bag_id):
    return [r for r in store.scans.values() if r["bag_id"] == bag_id]


def screenings_of(store, bag_id):
    return [r for r in store.screenings.values() if r["bag_id"] == bag_id]


def tasks_of_bag(store, bag_id):
    event_ids = {e["id"] for e in screenings_of(store, bag_id)}
    return [t for t in store.inspections.values() if t["screening_event_id"] in event_ids]


def reports_of(store, bag_id):
    return [r for r in store.reports.values() if r["bag_id"] == bag_id]


def delivery_of(store, bag_id):
    for row in store.deliveries.values():
        if row["bag_id"] == bag_id:
            return row
    return None


def bags_of_station(store, station_id):
    return [b for b in store.bags.values() if b.get("station_id") == station_id]


def bags_of_flight(store, flight_id):
    return [b for b in store.bags.values() if b.get("flight_id") == flight_id]


def bags_of_area(store, area_id):
    return [b for b in store.bags.values() if b.get("makeup_area_id") == area_id]


# ------------------------------------------------------------- bag formulas --
def excess_weight_fee(store, bag):
    """CURRENT variant normally; pinned to zero while the station's outage is active."""
    station = station_of(store, bag)
    if station and station.get("outage_active"):
        return 0
    airline = airline_of_bag(store, bag)
    if airline is None or bag.get("scale_weight_lb") is None:
        return 0
    weight = whole_pounds(bag["scale_weight_lb"])
    threshold = airline["max_excess_weight_lb"]
    if weight <= threshold:
        return 0
    groups = int(math.ceil((Decimal(str(weight)) - Decimal(str(threshold))) / Decimal("5")))
    return groups * 7500


def handling_charge(store, bag, variant=None):
    if variant is None:
        variant = "PROVISIONAL" if bag["custody_status"] in PROVISIONAL_CUSTODY else "FINAL"
    weight = whole_pounds(bag.get("scale_weight_lb") or 0)
    base = Decimal(700) + Decimal(25) * Decimal(weight)
    special = Decimal(2600) * Decimal(len(special_items_of(store, bag["id"])))
    intl = Decimal(1800) if bag.get("itinerary_type") == "INTERNATIONAL" else Decimal(0)
    subtotal = rhu(base + special + intl, 0)
    params = 0
    if variant == "FINAL" and bag.get("_was_held"):
        params = 3700
    return subtotal + params


def item_scale(linear_in):
    if linear_in <= 62:
        return 1
    if linear_in <= 115:
        return 2
    return 3


def single_item_fee(linear_in, item_type):
    """Round half-up per item: the pinned order is per-item, never sum-then-round."""
    raw = Decimal(ITEM_BASE_FEE_CENTS[item_type])
    if linear_in >= 115:
        raw = raw * Decimal("1.25")
    raw = raw * Decimal(item_scale(linear_in))
    return rhu(raw, 0)


def oversize_handling_fee(store, bag):
    items = special_items_of(store, bag["id"])
    if not items:
        return 0
    return sum(single_item_fee(bag["linear_in"], i["item_type"]) for i in items)


def requires_manual_screening(linear_in, item_type):
    return item_type in ("MOBILITY_DEVICE", "SPORTS_EQUIPMENT") or linear_in > 115


def liability_cap(item_type, declared_value_cents):
    if item_type == "MOBILITY_DEVICE":
        base = 200000
    elif item_type == "FRAGILE":
        base = 50000
    else:
        base = 100000
    return min(declared_value_cents, base)


def routing_class(store, bag):
    airline = airline_of_bag(store, bag)
    itinerary = bag.get("itinerary_type")
    if itinerary == "INTERLINE":
        if airline is None or not airline.get("interline_agreement_active"):
            return "MANUAL"
        if whole_pounds(bag.get("scale_weight_lb") or 0) > airline["max_excess_weight_lb"]:
            return "MANUAL"
        return "STANDARD"
    if itinerary == "INTERNATIONAL":
        return "BULK_HOLD"
    return "STANDARD"


def duplicate_flag(store, bag):
    if not bag.get("flight_id"):
        return False
    mine = (bag["created_at"], bag.get("_seq", 0))
    for other in store.bags.values():
        if other["id"] == bag["id"]:
            continue
        if other.get("passenger_ref") != bag.get("passenger_ref"):
            continue
        if other.get("flight_id") != bag.get("flight_id"):
            continue
        if (other["created_at"], other.get("_seq", 0)) < mine:
            return True
    return False


def rush_declared(store, bag):
    conn = connection_of(store, bag["id"])
    return bool(conn and conn["status"] in ("RUSH", "REACCOMMODATED"))


def priority_score(store, bag):
    score = ROUTING_CLASS_POINTS.get(bag.get("routing_class"), 0)
    conn = connection_of(store, bag["id"])
    status = conn["status"] if conn else "NONE"
    score += CONNECTION_CLASS_POINTS.get(status, 0)
    if conn is None:
        score += 120
    elif (conn.get("connect_slack_minutes") or 0) >= 0:
        score += 20
    else:
        score -= 60
    variance = bag.get("weight_variance_lb")
    if variance is not None and abs(variance) >= 10:
        score -= 40
    if bag.get("screening_status") == "CLEARED":
        score += 30
    flight = flight_of(store, bag)
    if flight:
        close = parse_iso(flight.get("sortation_close_utc"))
        if close and store.now() >= close:
            score -= 100
    if conn is not None and conn["status"] == "MISSED":
        score += 200
    return score


def manual_sortation_delay(store, bag):
    station = station_of(store, bag)
    if station is None or not station.get("outage_active"):
        return 0
    started = parse_iso(station.get("outage_started_utc"))
    dwell = 0
    if started:
        dwell = trunc_minutes(store.now() - started)
    if dwell < 0:
        dwell = 0
    capped = min(dwell, 45)
    manual_scans = sum(1 for s in scans_of(store, bag["id"]) if s.get("_outage_manual"))
    return capped + 15 * manual_scans


def screen_alarm_resolution_time(store, bag):
    events = screenings_of(store, bag["id"])
    if not events:
        return 0
    first = min(parse_iso(e["created_at"]) for e in events)
    last = max(parse_iso(e["updated_at"]) for e in events)
    return trunc_minutes(last - first)


# ------------------------------------------------------------- connection ---
def connection_slack(store, connection):
    inbound = store.flights.get(connection.get("inbound_flight_id"))
    onward = store.flights.get(connection.get("onward_flight_id"))
    if inbound is None or onward is None:
        return 0
    diff = parse_iso(onward["scheduled_departure_utc"]) - parse_iso(inbound["scheduled_departure_utc"])
    return trunc_minutes(diff) - connection["required_mct_minutes"]


# -------------------------------------------------------- station aggregates -
def active_bag_count(store, station_id):
    return sum(1 for b in bags_of_station(store, station_id) if b["custody_status"] in ACTIVE_CUSTODY)


def manual_queue_depth(store, station_id):
    return sum(1 for t in store.inspections.values()
               if t["station_id"] == station_id and t["status"] in ("QUEUED", "IN_PROGRESS"))


def _active_areas(store, station_id):
    return [a for a in store.makeup_areas.values()
            if a["station_id"] == station_id and a["status"] == "ACTIVE"]


def station_posture(store, station):
    if station.get("outage_active"):
        return "SUSPENDED"
    if station["active_bag_count"] >= station["sorter_capacity_bags"]:
        return "SUSPENDED"
    areas = _active_areas(store, station["id"])
    total = sum(a["capacity_slots"] for a in areas)
    free = sum(a["free_slots"] for a in areas)
    if total == 0:
        return "OPEN"
    threshold = int(math.ceil(Decimal("0.15") * Decimal(total)))
    if free <= threshold:
        return "CONGESTED"
    return "OPEN"


def liability_ledger(store, station_id):
    open_statuses = {"REPORTED", "INVESTIGATING", "DELIVERY_ARRANGED", "REOPENED"}
    settled_statuses = {"DELIVERED", "COMPENSATED", "CLOSED"}
    open_sum = 0
    settled_sum = 0
    for report in store.reports.values():
        if report["station_id"] != station_id:
            continue
        value = report.get("final_liability_cents") or 0
        if report["status"] in open_statuses:
            open_sum += value
        elif report["status"] in settled_statuses:
            settled_sum += value
    return open_sum, settled_sum


def area_occupancy(store, area):
    rows = bags_of_area(store, area["id"])
    occupied = sum(1 for b in rows if b["custody_status"] in ("SORTED", "IN_MAKEUP"))
    released = sum(1 for b in rows
                   if b["custody_status"] in ("LOADED", "OFFLOADED", "DELIVERED", "HELD"))
    return occupied, released, area["capacity_slots"] - occupied


def flight_loaded_bag_count(store, flight_id):
    return sum(1 for b in bags_of_flight(store, flight_id) if b["custody_status"] == "LOADED")


def flight_makeup_ready(store, flight_id):
    for bag in bags_of_flight(store, flight_id):
        if bag["custody_status"] == "HELD":
            return False
        for task in tasks_of_bag(store, bag["id"]):
            if task["status"] in ("QUEUED", "IN_PROGRESS"):
                return False
    return True


# ---------------------------------------------------------- report formulas -
def compensation_offer(store, report):
    bag = store.bags.get(report["bag_id"])
    fraction = Decimal(REPORT_TYPE_FRACTION[report["report_type"]])
    if report["status"] in ("DELIVERED", "COMPENSATED"):
        fraction = fraction * Decimal("1.25")
    items = special_items_of(store, bag["id"]) if bag else []
    raw = max((i["declared_value_cents"] for i in items), default=0)
    offer = rhu(Decimal(raw) * fraction, 0)
    caps = []
    airline = airline_of_bag(store, bag) if bag else None
    if airline is not None:
        caps.append(airline["compensation_cap_cents"])
    if items:
        caps.append(min(i["liability_cap_cents"] for i in items))
    for cap in caps:
        offer = min(offer, cap)
    return offer


def final_liability(store, report):
    if report["status"] in ("REPORTED", "INVESTIGATING", "DELIVERY_ARRANGED", "REOPENED", "DELIVERED"):
        base = Decimal(report.get("compensation_offer_cents") or 0) * Decimal("0.75")
    else:
        base = Decimal(report.get("compensation_settled_cents") or 0)
    return rhu(base, 0)


def settlement(store, report, claim, pre_liability):
    """Two-step waterfall; every term is already an integral number of cents."""
    bag = store.bags.get(report["bag_id"])
    airline = airline_of_bag(store, bag) if bag else None
    requested = claim["requested_amount_cents"] if claim else report.get("claim_amount_cents") or 0
    approved = min(requested, report.get("compensation_offer_cents") or 0)
    if airline is not None:
        approved = min(approved, airline["compensation_cap_cents"])
    applied = min(approved, pre_liability)
    return approved, applied


def request_over_cap(store, report, requested):
    bag = store.bags.get(report["bag_id"])
    airline = airline_of_bag(store, bag) if bag else None
    if airline is None:
        return False
    return requested > airline["compensation_cap_cents"]


def manual_rate_limited(store, station, bag):
    if not station.get("outage_active") or bag.get("routing_class") != "MANUAL":
        return False
    if rush_declared(store, bag):
        return False
    started = parse_iso(station.get("outage_started_utc"))
    count = 0
    for other in bags_of_station(store, station["id"]):
        if other.get("routing_class") != "MANUAL" or not other.get("loaded_utc"):
            continue
        loaded = parse_iso(other["loaded_utc"])
        if started is None or loaded >= started:
            count += 1
    # PRD §3.9: the allowance is exhausted "once that count has reached five" and
    # "the boundary is inclusive: the fifth manual-class bag is refused while the
    # fourth is admitted" — so the count is taken over the load being attempted
    # as well, and it is the fifth manual load that is refused.
    return count + 1 >= 5