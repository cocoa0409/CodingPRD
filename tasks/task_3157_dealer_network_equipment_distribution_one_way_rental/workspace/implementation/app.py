"""Dealer Network One-Way Rental API — Flask implementation.

In-memory only. No seeding. Logical clock governs all business time.
"""
import os
import uuid
import random
import string
import math
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"NetworkAdmin", "DealerAgent", "Customer", "PricingManager",
         "RepositionDriver", "FinanceReviewer"}

EQUIPMENT_TYPES = {"TRUCK_10FT", "TRUCK_15FT", "TRUCK_26FT",
                   "TRAILER_4X8", "TRAILER_6X12", "TOW_DOLLY"}
GEO_ZONES = {"NORTH", "SOUTH", "EAST", "WEST", "CENTRAL"}
SEASONS = {"PEAK", "SHOULDER", "OFF_PEAK"}
HITCH_CLASSES = {"CLASS_I", "CLASS_II", "CLASS_III", "CLASS_IV", "NONE"}
RENTAL_KINDS = {"ROUND_TRIP", "ONE_WAY"}
PLAN_TIERS = {"BASIC", "STANDARD", "PREMIUM"}

TOWED_TYPES = {"TRAILER_4X8", "TRAILER_6X12", "TOW_DOLLY"}
EQUIPMENT_GVWR_LBS = {"TRAILER_4X8": 2500, "TRAILER_6X12": 4400, "TOW_DOLLY": 3450}
HITCH_MIN = {
    "TRAILER_4X8": ["CLASS_I", "CLASS_II", "CLASS_III", "CLASS_IV"],
    "TRAILER_6X12": ["CLASS_III", "CLASS_IV"],
    "TOW_DOLLY": ["CLASS_II", "CLASS_III", "CLASS_IV"],
}
TOW_SAFETY_FACTOR = Decimal("0.8")
CURB_RATIO_MIN = Decimal("0.8")

IMBALANCE_THRESHOLD = Decimal("1.0")
LONG_RENTAL_THRESHOLD = 7
LONG_RENTAL_DISCOUNT = Decimal("0.10")
IMBALANCE_WEIGHT = Decimal("0.5")

REPOSITION_BAND_COST_CENTS = {"SHORT": 9000, "MEDIUM": 24000, "LONG": 52000}
DRIVER_FEE_CENTS_PER_TASK = 6000
IDLE_PENALTY_HOURS = 48
IDLE_PENALTY_CENTS = 15000

PLAN_DAILY_CENTS = {"BASIC": 1400, "STANDARD": 2400, "PREMIUM": 3900}
PLAN_LONG_DAYS = 7
PLAN_LONG_DISCOUNT = Decimal("0.15")
PLAN_COVERAGE_CAP_CENTS = {"BASIC": 200000, "STANDARD": 750000, "PREMIUM": 2500000}

LATE_DAY_MULTIPLIER = Decimal("1.5")

CROSS_SELL_COMMISSION_RATE = Decimal("0.05")
CLAWBACK_RATE = Decimal("0.10")
PERFORMANCE_FLOOR = Decimal("60")

CATALOG_PRICE_CENTS = {"BOX_SMALL": 125, "BOX_LARGE": 245, "TAPE": 399,
                       "BLANKET": 899, "LOCK": 1299}
STORAGE_MONTH_RATE_CENTS = {"NORTH": 8900, "SOUTH": 7900, "EAST": 9500,
                            "WEST": 9900, "CENTRAL": 6900}
BUNDLE_DISCOUNT_RATE = Decimal("0.10")

W_PERF = Decimal("0.5")
W_UTIL = Decimal("0.3")
W_ZONE = Decimal("0.2")

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.locations = {}
        self.dealers = {}
        self.equipment_units = {}
        self.vehicle_profiles = {}
        self.customers = {}
        self.lane_rates = {}
        self.reservations = {}
        self.rental_agreements = {}
        self.damage_protection_plans = {}
        self.damage_claims = {}
        self.reposition_tasks = {}
        self.reservation_events = {}
        self.cross_sell_orders = {}
        self.dealer_settlements = {}
        self.clock = DEFAULT_CLOCK
        self.lock = threading.RLock()


db = Store()


# ---------------------------------------------------------------------------
# Errors / envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _now_iso(dt=None):
    dt = dt or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def ok_object(data, code=200):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _now_iso()},
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _now_iso()},
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    return handle_api_error(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return handle_api_error(ApiError("ERR_NOT_FOUND", "Method not allowed", 404))


@app.errorhandler(Exception)
def handle_exc(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    app.logger.exception(err)
    return handle_api_error(ApiError("ERR_INVALID_REQUEST", str(err), 400))


# ---------------------------------------------------------------------------
# Auth / helpers
# ---------------------------------------------------------------------------
def auth(required_roles=None):
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid X-User-Role", 401)
    uid = request.headers.get("X-User-ID")
    if uid is None or uid == "":
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or empty X-User-ID", 401)
    if required_roles is not None and role not in required_roles:
        raise ApiError("ERR_FORBIDDEN", "Role not authorized for this endpoint", 403)
    return uid, role


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object", 400)
    return data


def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", f"Missing or invalid field: {field}", 400)
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"Missing or invalid field: {field}", 400)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} below minimum", 400)
    return v


def req_num(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", f"Missing or invalid field: {field}", 400)
    return v


def req_enum(data, field, allowed):
    v = req_str(data, field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", f"Unknown value for {field}: {v}", 400)
    return v


def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Invalid datetime: {field}", 400)
    s = value
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", f"Invalid datetime: {field}", 400)


def pagination_params():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid pagination parameters", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid pagination parameters", 400)
    return limit, offset


def paginate(rows):
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list(page, limit, offset, total)


def round_half_up_int(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(x):
    return float(Decimal(str(x)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def round2_dec(x):
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def new_entity(store, fields, with_version=True):
    ent = {"id": str(uuid.uuid4()), "created_at": _now_iso(), "updated_at": _now_iso()}
    if with_version:
        ent["version"] = 1
    ent.update(fields)
    store[ent["id"]] = ent
    return ent


def touch(ent):
    ent["updated_at"] = _now_iso()
    if "version" in ent:
        ent["version"] += 1


def get_or_404(store, entity_id, label="Resource"):
    ent = store.get(entity_id)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", f"{label} not found: {entity_id}", 404)
    return ent


def fk_or_ref404(store, entity_id, label="Reference"):
    ent = store.get(entity_id)
    if ent is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"{label} not found: {entity_id}", 404)
    return ent


def season_of(dt):
    m = dt.month
    if m in (6, 7, 8):
        return "PEAK"
    if m in (4, 5, 9, 10):
        return "SHOULDER"
    return "OFF_PEAK"


def rental_days(pickup, dropoff):
    delta = (dropoff - pickup).total_seconds()
    days = math.ceil(delta / 86400.0)
    return max(1, int(days))


def ceil_days_between(start, end):
    delta = (end - start).total_seconds()
    return max(1, int(math.ceil(delta / 86400.0)))


def active_lane_rate(origin_id, dest_id, etype, season):
    for r in db.lane_rates.values():
        if (r["origin_location_id"] == origin_id and r["dest_location_id"] == dest_id
                and r["equipment_type"] == etype and r["season"] == season
                and r["status"] == "ACTIVE"):
            return r
    return None


def recompute_alloc(dealer_id):
    d = db.dealers.get(dealer_id)
    if d is None:
        return
    d["allocated_unit_count"] = sum(
        1 for u in db.equipment_units.values()
        if u["current_dealer_id"] == dealer_id and u["status"] != "RETIRED")


def recompute_lane_imbalance(origin_id, dest_id, include_deficit=True):
    """Recompute imbalance_factor for every ACTIVE lane rate touching either location."""
    for rate in db.lane_rates.values():
        if rate["status"] != "ACTIVE":
            continue
        if not ({rate["origin_location_id"], rate["dest_location_id"]} &
                {origin_id, dest_id}):
            continue
        rate["imbalance_factor"] = compute_imbalance(
            rate["origin_location_id"], rate["dest_location_id"],
            rate["equipment_type"], include_deficit=True)


def compute_imbalance(o_id, d_id, etype, include_deficit=True):
    net_flow_fwd = 0
    net_flow_rev = 0
    for ag in db.rental_agreements.values():
        if ag["status"] not in ("RETURNED", "SETTLED"):
            continue
        res = db.reservations.get(ag["reservation_id"])
        if res is None or res["rental_kind"] != "ONE_WAY":
            continue
        if res["equipment_type"] != etype:
            continue
        if res["origin_location_id"] == o_id and res["dest_location_id"] == d_id:
            net_flow_fwd += 1
        elif res["origin_location_id"] == d_id and res["dest_location_id"] == o_id:
            net_flow_rev += 1
    net_flow = net_flow_fwd - net_flow_rev
    deficit = 0
    if include_deficit:
        def_fwd = 0
        def_rev = 0
        for res in db.reservations.values():
            if res["status"] not in ("CONFIRMED", "REASSIGNED"):
                continue
            if res["rental_kind"] != "ONE_WAY" or res["equipment_type"] != etype:
                continue
            if res["origin_location_id"] == o_id and res["dest_location_id"] == d_id:
                def_fwd += 1
            elif res["origin_location_id"] == d_id and res["dest_location_id"] == o_id:
                def_rev += 1
        deficit = def_fwd - def_rev
    fleet_total = sum(1 for u in db.equipment_units.values()
                      if u["equipment_type"] == etype and u["status"] != "RETIRED")
    denom = max(fleet_total, 1)
    val = Decimal("1.0") + IMBALANCE_WEIGHT * Decimal(net_flow + deficit) / Decimal(denom)
    return float(val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def quote_price(origin_location_id, dest_location_id, etype, season, days):
    rate = active_lane_rate(origin_location_id, dest_location_id, etype, season)
    if rate is None:
        raise ApiError("ERR_NO_ACTIVE_RATE",
                       "No ACTIVE lane rate for this lane/season", 422)
    daily = rate["base_rate_cents"]
    if Decimal(str(rate["imbalance_factor"])) > IMBALANCE_THRESHOLD:
        daily += rate["reposition_surcharge_cents"]
    if days >= LONG_RENTAL_THRESHOLD:
        daily = round_half_up_int(Decimal(daily) * (Decimal("1") - LONG_RENTAL_DISCOUNT))
    total = daily * days
    return {
        "quoted_rate_cents_per_day": daily,
        "applied_imbalance_factor": rate["imbalance_factor"],
        "commission_rate": rate["commission_rate"],
        "total_quoted_cents": total,
    }


def tow_check(reservation, customer):
    etype = reservation["equipment_type"]
    if etype not in TOWED_TYPES:
        return "NOT_REQUIRED"
    v = db.vehicle_profiles.get(customer["vehicle_profile_id"])
    gvwr = EQUIPMENT_GVWR_LBS[etype]
    if v["hitch_class"] not in HITCH_MIN[etype]:
        return "FAIL"
    if Decimal(v["tow_capacity_lbs"]) < Decimal(gvwr) * TOW_SAFETY_FACTOR:
        return "FAIL"
    if Decimal(v["curb_weight_lbs"]) < Decimal(gvwr) * CURB_RATIO_MIN:
        return "FAIL"
    return "PASS"


def held_unit_for(reservation_id):
    for u in db.equipment_units.values():
        if u.get("_held_for_reservation_id") == reservation_id and u["status"] == "HELD":
            return u
    return None


def unit_free_for_interval(unit, pickup, dropoff, exclude_reservation_id=None):
    """A unit is free if it has no overlapping active/held/scheduled commitments.

    In this model a unit is unavailable while HELD or OUT (regardless of dates);
    while AVAILABLE it is free. We additionally treat overlap against reservations
    holding it. Simple model: AVAILABLE units are free.
    """
    return unit["status"] == "AVAILABLE"


def distance_band(zone_a, zone_b):
    if zone_a == zone_b:
        return "SHORT"
    pair = {zone_a, zone_b}
    if pair in ({"NORTH", "SOUTH"}, {"EAST", "WEST"}):
        return "LONG"
    return "MEDIUM"


def quarter_window(period):
    """Parse 'YYYY-Qn' into (start_dt, end_dt) closed-open window."""
    try:
        year_s, q_s = period.split("-")
        year = int(year_s)
        q = int(q_s.lstrip("Qq"))
        start_month = {1: 1, 2: 4, 3: 7, 4: 10}[q]
    except (ValueError, KeyError, AttributeError):
        raise ApiError("ERR_INVALID_REQUEST", f"Invalid period: {period}", 400)
    start = datetime(year, start_month, 1, tzinfo=timezone.utc)
    if q == 4:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, start_month + 3, 1, tzinfo=timezone.utc)
    return start, end


def active_dealer_at_location(location_id):
    for d in db.dealers.values():
        if d["location_id"] == location_id and d["status"] == "ACTIVE":
            return d
    return None


def append_event(reservation_id, event_type, from_dealer_id=None, to_dealer_id=None,
                 note=None):
    ev = {
        "id": str(uuid.uuid4()),
        "created_at": _now_iso(),
        "reservation_id": reservation_id,
        "event_type": event_type,
        "from_dealer_id": from_dealer_id,
        "to_dealer_id": to_dealer_id,
        "note": note,
    }
    db.reservation_events[ev["id"]] = ev
    return ev


# ---------------------------------------------------------------------------
# Serializers (strip internal keys)
# ---------------------------------------------------------------------------
def pub(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.post("/_clock/set_current_utc")
def set_clock():
    auth(["NetworkAdmin"])
    data = body()
    to_iso = data.get("to_iso8601")
    dt = parse_dt(to_iso, "to_iso8601")
    db.clock = dt
    return ok_object({"current_utc": _iso(db.clock)})


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------
@app.post("/rental-network/locations")
def create_location():
    auth(["NetworkAdmin"])
    data = body()
    location_code = req_str(data, "location_code")
    city = req_str(data, "city")
    geo_zone = req_enum(data, "geo_zone", GEO_ZONES)
    storage_capacity = req_int(data, "storage_capacity", minimum=0)
    if any(l["location_code"] == location_code for l in db.locations.values()):
        raise ApiError("ERR_DUPLICATE_RESOURCE", "location_code already exists", 409)
    loc = new_entity(db.locations, {
        "location_code": location_code, "city": city, "geo_zone": geo_zone,
        "storage_capacity": storage_capacity, "status": "OPEN",
    })
    return ok_object(pub(loc), 201)


@app.get("/rental-network/locations")
def list_locations():
    auth(["NetworkAdmin", "PricingManager", "DealerAgent", "FinanceReviewer"])
    rows = list(db.locations.values())
    gz = request.args.get("geo_zone")
    st = request.args.get("status")
    if gz:
        rows = [r for r in rows if r["geo_zone"] == gz]
    if st:
        rows = [r for r in rows if r["status"] == st]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/locations/<lid>")
def get_location(lid):
    auth(["NetworkAdmin", "PricingManager", "DealerAgent", "FinanceReviewer"])
    return ok_object(pub(get_or_404(db.locations, lid, "Location")))


@app.post("/rental-network/locations/<lid>/close")
def close_location(lid):
    auth(["NetworkAdmin"])
    loc = get_or_404(db.locations, lid, "Location")
    if loc["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Location is not OPEN", 409)
    for u in db.equipment_units.values():
        if u["current_location_id"] == lid and u["status"] in (
                "AVAILABLE", "HELD", "OUT", "REPOSITIONING"):
            raise ApiError("ERR_INVALID_STATE",
                           "Location still holds fleet units", 409)
    for r in db.reservations.values():
        if r["origin_location_id"] == lid and r["status"] in (
                "QUOTED", "CONFIRMED", "REASSIGNED"):
            raise ApiError("ERR_INVALID_STATE",
                           "Location has live reservations", 409)
    loc["status"] = "CLOSED"
    touch(loc)
    return ok_object(pub(loc))


@app.post("/rental-network/locations/<lid>/reopen")
def reopen_location(lid):
    auth(["NetworkAdmin"])
    loc = get_or_404(db.locations, lid, "Location")
    if loc["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "Location is not CLOSED", 409)
    loc["status"] = "OPEN"
    touch(loc)
    return ok_object(pub(loc))


# ---------------------------------------------------------------------------
# Dealers
# ---------------------------------------------------------------------------
@app.post("/rental-network/dealers")
def create_dealer():
    auth(["NetworkAdmin"])
    data = body()
    dealer_code = req_str(data, "dealer_code")
    name = req_str(data, "name")
    location_id = req_str(data, "location_id")
    fk_or_ref404(db.locations, location_id, "Location")
    override = data.get("commission_rate_override", None)
    if override is not None:
        if isinstance(override, bool) or not isinstance(override, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", "Invalid commission_rate_override", 400)
        if not (0 <= override <= 1):
            raise ApiError("ERR_INVALID_REQUEST", "commission_rate_override out of range", 400)
    if any(d["dealer_code"] == dealer_code for d in db.dealers.values()):
        raise ApiError("ERR_DUPLICATE_RESOURCE", "dealer_code already exists", 409)
    dealer = new_entity(db.dealers, {
        "dealer_code": dealer_code, "name": name, "location_id": location_id,
        "commission_rate_override": override, "status": "ACTIVE",
        "allocated_unit_count": 0, "performance_score": 0,
    })
    return ok_object(pub(dealer), 201)


@app.get("/rental-network/dealers")
def list_dealers():
    auth(["NetworkAdmin", "PricingManager", "FinanceReviewer"])
    rows = list(db.dealers.values())
    st = request.args.get("status")
    lid = request.args.get("location_id")
    if st:
        rows = [r for r in rows if r["status"] == st]
    if lid:
        rows = [r for r in rows if r["location_id"] == lid]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/dealers/<did>/reservation-events")
def dealer_reservation_events(did):
    auth(["NetworkAdmin", "FinanceReviewer"])
    get_or_404(db.dealers, did, "Dealer")
    direction = request.args.get("direction")
    rows = []
    for ev in db.reservation_events.values():
        match = False
        if direction == "from":
            match = ev.get("from_dealer_id") == did
        elif direction == "to":
            match = ev.get("to_dealer_id") == did
        else:
            match = ev.get("from_dealer_id") == did or ev.get("to_dealer_id") == did
        if match:
            rows.append(ev)
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/dealers/<did>")
def get_dealer(did):
    auth(["NetworkAdmin", "DealerAgent", "FinanceReviewer"])
    return ok_object(pub(get_or_404(db.dealers, did, "Dealer")))


def _reassign_reservation_core(res, note):
    """Run the selector; return new dealer or None when pool empty."""
    origin_loc = db.locations[res["origin_location_id"]]
    zone = origin_loc["geo_zone"]
    candidates = []
    for d in db.dealers.values():
        if d["status"] != "ACTIVE":
            continue
        dl = db.locations.get(d["location_id"])
        if dl is None or dl["geo_zone"] != zone:
            continue
        if d["id"] == res["origin_dealer_id"]:
            continue
        # has an AVAILABLE unit of right type free for interval
        ok = any(u for u in db.equipment_units.values()
                 if u["current_dealer_id"] == d["id"]
                 and u["equipment_type"] == res["equipment_type"]
                 and u["status"] == "AVAILABLE")
        if ok:
            candidates.append(d)
    if not candidates:
        return None
    candidates.sort(key=lambda d: (-float(d["performance_score"]),
                                   d["allocated_unit_count"], d["created_at"]))
    new_dealer = candidates[0]
    # release HELD unit at old dealer
    old_held = held_unit_for(res["id"])
    if old_held is not None:
        old_held["status"] = "AVAILABLE"
        old_held.pop("_held_for_reservation_id", None)
        touch(old_held)
    # hold a unit at new dealer
    new_unit = None
    for u in sorted(db.equipment_units.values(), key=lambda x: x["created_at"]):
        if (u["current_dealer_id"] == new_dealer["id"]
                and u["equipment_type"] == res["equipment_type"]
                and u["status"] == "AVAILABLE"):
            new_unit = u
            break
    new_unit["status"] = "HELD"
    new_unit["_held_for_reservation_id"] = res["id"]
    touch(new_unit)
    from_dealer_id = res["origin_dealer_id"]
    origin_changed = new_dealer["location_id"] != res["origin_location_id"]
    res["origin_dealer_id"] = new_dealer["id"]
    res["origin_location_id"] = new_dealer["location_id"]
    if origin_changed:
        res["price_snapshot"] = quote_price(
            res["origin_location_id"], res["dest_location_id"],
            res["equipment_type"], res["season"], res["rental_days"])
    res["status"] = "REASSIGNED"
    touch(res)
    append_event(res["id"], "REASSIGNED", from_dealer_id=from_dealer_id,
                 to_dealer_id=new_dealer["id"], note=note)
    return new_dealer


@app.post("/rental-network/dealers/<did>/suspend")
def suspend_dealer(did):
    auth(["NetworkAdmin"])
    dealer = get_or_404(db.dealers, did, "Dealer")
    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Dealer is not ACTIVE", 409)
    dealer["status"] = "SUSPENDED"
    touch(dealer)
    # sweep confirmed/reassigned reservations
    affected = [r for r in db.reservations.values()
                if r["origin_dealer_id"] == did and r["status"] in ("CONFIRMED", "REASSIGNED")]
    affected.sort(key=lambda r: r["created_at"])
    for res in affected:
        result = _reassign_reservation_core(res, "dealer suspended")
        if result is None:
            res["status"] = "EXPIRED"
            touch(res)
            append_event(res["id"], "EXPIRED", note="dealer suspended; no reassignment candidate")
    return ok_object(pub(dealer))


@app.post("/rental-network/dealers/<did>/reactivate")
def reactivate_dealer(did):
    auth(["NetworkAdmin"])
    dealer = get_or_404(db.dealers, did, "Dealer")
    if dealer["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Dealer is not SUSPENDED", 409)
    dealer["status"] = "ACTIVE"
    touch(dealer)
    return ok_object(pub(dealer))


@app.post("/rental-network/dealers/<did>/deactivate")
def deactivate_dealer(did):
    auth(["NetworkAdmin"])
    dealer = get_or_404(db.dealers, did, "Dealer")
    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Dealer is not ACTIVE", 409)
    for r in db.reservations.values():
        if r["origin_dealer_id"] == did and r["status"] in ("QUOTED", "CONFIRMED", "REASSIGNED"):
            raise ApiError("ERR_DEALER_HAS_ACTIVE_HOLDINGS",
                           "Dealer has live reservations", 409)
    for u in db.equipment_units.values():
        if u["current_dealer_id"] == did and u["status"] in ("AVAILABLE", "HELD", "OUT"):
            raise ApiError("ERR_DEALER_HAS_ACTIVE_HOLDINGS",
                           "Dealer has fleet holdings", 409)
    dealer["status"] = "DEACTIVATED"
    touch(dealer)
    return ok_object(pub(dealer))


@app.post("/rental-network/dealers/allocate")
def allocate_units():
    auth(["NetworkAdmin"])
    data = body()
    unit_codes = data.get("unit_codes")
    if not isinstance(unit_codes, list):
        raise ApiError("ERR_INVALID_REQUEST", "unit_codes must be an array", 400)

    def score(dealer):
        util_count = sum(1 for u in db.equipment_units.values()
                         if u["current_dealer_id"] == dealer["id"]
                         and u["status"] in ("OUT", "HELD"))
        util_pct = Decimal(100) * Decimal(util_count) / Decimal(max(dealer["allocated_unit_count"], 1))
        loc = db.locations.get(dealer["location_id"])
        zone = loc["geo_zone"] if loc else None
        # zone_deficit_bonus: 10 if zone has negative net flow on imbalance signal
        zone_bonus = Decimal(0)
        if zone:
            neg = False
            for rate in db.lane_rates.values():
                if rate["status"] != "ACTIVE":
                    continue
                o_loc = db.locations.get(rate["origin_location_id"])
                if o_loc and o_loc["geo_zone"] == zone:
                    factor = compute_imbalance(rate["origin_location_id"],
                                               rate["dest_location_id"],
                                               rate["equipment_type"],
                                               include_deficit=True)
                    if factor < 1.0:
                        neg = True
                        break
            if neg:
                zone_bonus = Decimal(10)
        s = W_PERF * Decimal(str(dealer["performance_score"])) + W_UTIL * util_pct + W_ZONE * zone_bonus
        return round2_dec(s)

    active_dealers = [d for d in db.dealers.values() if d["status"] == "ACTIVE"]
    ranked = sorted(active_dealers, key=lambda d: (-score(d), d["created_at"]))

    allocated = []
    skipped = []
    code_to_unit = {u["unit_code"]: u for u in db.equipment_units.values()}
    for code in unit_codes:
        unit = code_to_unit.get(code)
        if unit is None or unit["status"] == "RETIRED":
            skipped.append(code)
            continue
        placed = False
        for dealer in ranked:
            # give the unit to the top-ranked dealer that isn't already holding it;
            # simple round: each unit goes to the highest-ranked dealer without a
            # pending unit of the same type this round
            old_dealer_id = unit["current_dealer_id"]
            unit["current_dealer_id"] = dealer["id"]
            unit["current_location_id"] = dealer["location_id"]
            touch(unit)
            recompute_alloc(dealer["id"])
            if old_dealer_id != dealer["id"]:
                recompute_alloc(old_dealer_id)
            allocated.append({"unit_code": code, "dealer_id": dealer["id"]})
            ranked.append(ranked.pop(0))  # rotate for distribution
            placed = True
            break
        if not placed:
            skipped.append(code)
    return ok_object({"allocated": allocated, "skipped_unit_codes": skipped})


@app.post("/rental-network/performance-reviews")
def performance_reviews():
    auth(["NetworkAdmin"])
    data = body()
    period = req_str(data, "period")
    scores = data.get("scores")
    if not isinstance(scores, list):
        raise ApiError("ERR_INVALID_REQUEST", "scores must be an array", 400)
    updated = []
    for entry in scores:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Invalid score entry", 400)
        dealer_id = entry.get("dealer_id")
        dealer = db.dealers.get(dealer_id)
        if dealer is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Dealer not found: {dealer_id}", 404)
        score = entry.get("performance_score", entry.get("score"))
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", "Invalid score", 400)
        dealer["performance_score"] = score
        touch(dealer)
        updated.append(dealer_id)
    return ok_object({"updated_dealer_ids": updated})


# ---------------------------------------------------------------------------
# Equipment units
# ---------------------------------------------------------------------------
@app.post("/rental-network/equipment-units")
def create_unit():
    auth(["NetworkAdmin"])
    data = body()
    unit_code = req_str(data, "unit_code")
    etype = req_enum(data, "equipment_type", EQUIPMENT_TYPES)
    dealer_id = req_str(data, "dealer_id")
    dealer = fk_or_ref404(db.dealers, dealer_id, "Dealer")
    if any(u["unit_code"] == unit_code for u in db.equipment_units.values()):
        raise ApiError("ERR_DUPLICATE_RESOURCE", "unit_code already exists", 409)
    unit = new_entity(db.equipment_units, {
        "unit_code": unit_code, "equipment_type": etype,
        "current_dealer_id": dealer_id,
        "current_location_id": dealer["location_id"],
        "status": "AVAILABLE", "status_note": None,
    })
    recompute_alloc(dealer_id)
    return ok_object(pub(unit), 201)


@app.get("/rental-network/equipment-units")
def list_units():
    auth(["NetworkAdmin", "DealerAgent", "PricingManager"])
    rows = list(db.equipment_units.values())
    for f in ("current_dealer_id", "current_location_id", "equipment_type", "status"):
        v = request.args.get(f)
        if v:
            rows = [r for r in rows if r[f] == v]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/equipment-units/<uid>")
def get_unit(uid):
    auth(["NetworkAdmin", "DealerAgent"])
    return ok_object(pub(get_or_404(db.equipment_units, uid, "EquipmentUnit")))


@app.post("/rental-network/equipment-units/<uid>/status")
def unit_status(uid):
    user_id, _ = auth(["DealerAgent"])
    unit = get_or_404(db.equipment_units, uid, "EquipmentUnit")
    data = body()
    to_status = req_enum(data, "to_status", {"MAINTENANCE", "AVAILABLE"})
    note = data.get("status_note")
    if unit["current_dealer_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "Unit is not held by your dealer", 403)
    if to_status == "MAINTENANCE":
        if unit["status"] != "AVAILABLE":
            raise ApiError("ERR_INVALID_STATE", "Unit is not AVAILABLE", 409)
        unit["status"] = "MAINTENANCE"
        unit["status_note"] = note
    else:
        if unit["status"] != "MAINTENANCE":
            raise ApiError("ERR_INVALID_STATE", "Unit is not MAINTENANCE", 409)
        unit["status"] = "AVAILABLE"
        unit["status_note"] = note if note is not None else None
    touch(unit)
    return ok_object(pub(unit))


@app.post("/rental-network/equipment-units/<uid>/retire")
def retire_unit(uid):
    auth(["NetworkAdmin"])
    unit = get_or_404(db.equipment_units, uid, "EquipmentUnit")
    if unit["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", "Unit is not AVAILABLE", 409)
    unit["status"] = "RETIRED"
    touch(unit)
    recompute_alloc(unit["current_dealer_id"])
    return ok_object(pub(unit))


# ---------------------------------------------------------------------------
# Vehicle profiles / customers
# ---------------------------------------------------------------------------
@app.post("/rental-network/vehicle-profiles")
def create_vehicle_profile():
    auth(["Customer"])
    data = body()
    label = req_str(data, "label")
    make = req_str(data, "make")
    model = req_str(data, "model")
    year = req_int(data, "year", minimum=1980)
    curb = req_int(data, "curb_weight_lbs", minimum=1000)
    tow = req_int(data, "tow_capacity_lbs", minimum=0)
    hitch = req_enum(data, "hitch_class", HITCH_CLASSES)
    vp = new_entity(db.vehicle_profiles, {
        "label": label, "make": make, "model": model, "year": year,
        "curb_weight_lbs": curb, "tow_capacity_lbs": tow, "hitch_class": hitch,
    })
    return ok_object(pub(vp), 201)


@app.get("/rental-network/vehicle-profiles/<vid>")
def get_vehicle_profile(vid):
    auth(["Customer", "DealerAgent", "NetworkAdmin"])
    return ok_object(pub(get_or_404(db.vehicle_profiles, vid, "VehicleProfile")))


@app.post("/rental-network/customers")
def create_customer():
    auth(["Customer"])
    data = body()
    email = req_str(data, "email")
    full_name = req_str(data, "full_name")
    vpid = req_str(data, "vehicle_profile_id")
    fk_or_ref404(db.vehicle_profiles, vpid, "VehicleProfile")
    if any(c["email"] == email for c in db.customers.values()):
        raise ApiError("ERR_DUPLICATE_RESOURCE", "email already exists", 409)
    cust = new_entity(db.customers, {
        "email": email, "full_name": full_name, "vehicle_profile_id": vpid,
        "driver_license_verified": False,
    })
    return ok_object(pub(cust), 201)


@app.get("/rental-network/customers")
def list_customers():
    auth(["NetworkAdmin", "DealerAgent"])
    rows = list(db.customers.values())
    vpid = request.args.get("vehicle_profile_id")
    if vpid:
        rows = [r for r in rows if r["vehicle_profile_id"] == vpid]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/customers/<cid>")
def get_customer(cid):
    auth(["Customer", "DealerAgent", "NetworkAdmin"])
    return ok_object(pub(get_or_404(db.customers, cid, "Customer")))


@app.post("/rental-network/customers/<cid>/verify-license")
def verify_license(cid):
    auth(["DealerAgent"])
    cust = get_or_404(db.customers, cid, "Customer")
    cust["driver_license_verified"] = True
    touch(cust)
    return ok_object(pub(cust))


# ---------------------------------------------------------------------------
# Lane rates
# ---------------------------------------------------------------------------
@app.post("/rental-network/lane-rates")
def create_lane_rate():
    auth(["PricingManager"])
    data = body()
    origin_id = req_str(data, "origin_location_id")
    dest_id = req_str(data, "dest_location_id")
    fk_or_ref404(db.locations, origin_id, "Origin location")
    fk_or_ref404(db.locations, dest_id, "Dest location")
    etype = req_enum(data, "equipment_type", EQUIPMENT_TYPES)
    season = req_enum(data, "season", SEASONS)
    base = req_int(data, "base_rate_cents", minimum=0)
    surcharge = req_int(data, "reposition_surcharge_cents", minimum=0)
    commission = req_num(data, "commission_rate")
    if not (0 <= commission <= 1):
        raise ApiError("ERR_INVALID_REQUEST", "commission_rate out of range", 400)
    rate = new_entity(db.lane_rates, {
        "origin_location_id": origin_id, "dest_location_id": dest_id,
        "equipment_type": etype, "season": season,
        "base_rate_cents": base, "reposition_surcharge_cents": surcharge,
        "imbalance_factor": 1.0, "commission_rate": commission,
        "status": "DRAFT",
    })
    return ok_object(pub(rate), 201)


@app.get("/rental-network/lane-rates")
def list_lane_rates():
    auth(["PricingManager", "NetworkAdmin", "FinanceReviewer", "DealerAgent"])
    rows = list(db.lane_rates.values())
    for f in ("origin_location_id", "dest_location_id", "equipment_type",
              "season", "status"):
        v = request.args.get(f)
        if v:
            rows = [r for r in rows if r[f] == v]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/lane-rates/<rid>")
def get_lane_rate(rid):
    auth(["PricingManager", "NetworkAdmin", "DealerAgent"])
    return ok_object(pub(get_or_404(db.lane_rates, rid, "LaneRate")))


@app.post("/rental-network/lane-rates/<rid>/activate")
def activate_lane_rate(rid):
    auth(["PricingManager"])
    rate = get_or_404(db.lane_rates, rid, "LaneRate")
    if rate["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "LaneRate is not DRAFT", 409)
    for other in db.lane_rates.values():
        if (other["id"] != rid and other["status"] == "ACTIVE"
                and other["origin_location_id"] == rate["origin_location_id"]
                and other["dest_location_id"] == rate["dest_location_id"]
                and other["equipment_type"] == rate["equipment_type"]
                and other["season"] == rate["season"]):
            other["status"] = "SUPERSEDED"
            touch(other)
    rate["status"] = "ACTIVE"
    touch(rate)
    return ok_object(pub(rate))


@app.post("/rental-network/lane-rates/<rid>/supersede")
def supersede_lane_rate(rid):
    auth(["PricingManager"])
    rate = get_or_404(db.lane_rates, rid, "LaneRate")
    if rate["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "LaneRate is not ACTIVE", 409)
    rate["status"] = "SUPERSEDED"
    touch(rate)
    return ok_object(pub(rate))


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------
@app.post("/rental-network/reservations")
def create_reservation():
    auth(["Customer"])
    data = body()
    customer_id = req_str(data, "customer_id")
    origin_dealer_id = req_str(data, "origin_dealer_id")
    dest_location_id = req_str(data, "dest_location_id")
    etype = req_enum(data, "equipment_type", EQUIPMENT_TYPES)
    rental_kind = req_enum(data, "rental_kind", RENTAL_KINDS)
    pickup = parse_dt(data.get("pickup_date"), "pickup_date")
    dropoff = parse_dt(data.get("dropoff_date"), "dropoff_date")
    fk_or_ref404(db.customers, customer_id, "Customer")
    dealer = fk_or_ref404(db.dealers, origin_dealer_id, "Dealer")
    fk_or_ref404(db.locations, dest_location_id, "Location")
    # date-range checks
    if dropoff <= pickup:
        raise ApiError("ERR_INVALID_DATE_RANGE", "dropoff_date must be after pickup_date", 400)
    if pickup < db.clock:
        raise ApiError("ERR_INVALID_DATE_RANGE", "pickup_date is in the past", 400)
    origin_location_id = dealer["location_id"]
    season = season_of(pickup)
    days = rental_days(pickup, dropoff)
    snapshot = quote_price(origin_location_id, dest_location_id, etype, season, days)
    res = new_entity(db.reservations, {
        "customer_id": customer_id, "origin_dealer_id": origin_dealer_id,
        "origin_location_id": origin_location_id,
        "dest_location_id": dest_location_id, "equipment_type": etype,
        "rental_kind": rental_kind,
        "pickup_date": _iso(pickup), "dropoff_date": _iso(dropoff),
        "season": season, "rental_days": days,
        "status": "QUOTED", "price_snapshot": snapshot,
        "tow_check_result": "NOT_REQUIRED",
    })
    append_event(res["id"], "CREATED")
    return ok_object(pub(res), 201)


@app.get("/rental-network/reservations")
def list_reservations():
    auth(["Customer", "DealerAgent", "NetworkAdmin", "FinanceReviewer"])
    rows = list(db.reservations.values())
    for f in ("customer_id", "origin_dealer_id", "origin_location_id",
              "dest_location_id", "status"):
        v = request.args.get(f)
        if v:
            rows = [r for r in rows if r[f] == v]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/reservations/<rid>")
def get_reservation(rid):
    user_id, role = auth(["Customer", "DealerAgent", "NetworkAdmin", "FinanceReviewer"])
    res = get_or_404(db.reservations, rid, "Reservation")
    if role == "Customer" and res["customer_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "Not your reservation", 403)
    return ok_object(pub(res))


@app.patch("/rental-network/reservations/<rid>")
def patch_reservation(rid):
    user_id, _ = auth(["Customer"])
    res = get_or_404(db.reservations, rid, "Reservation")
    data = body()
    if res["customer_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "Not your reservation", 403)
    if res["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Reservation is not QUOTED", 409)
    pickup = parse_dt(res["pickup_date"], "pickup_date")
    dropoff = parse_dt(res["dropoff_date"], "dropoff_date")
    if "pickup_date" in data:
        pickup = parse_dt(data["pickup_date"], "pickup_date")
    if "dropoff_date" in data:
        dropoff = parse_dt(data["dropoff_date"], "dropoff_date")
    if dropoff <= pickup:
        raise ApiError("ERR_INVALID_DATE_RANGE", "dropoff_date must be after pickup_date", 400)
    if pickup < db.clock:
        raise ApiError("ERR_INVALID_DATE_RANGE", "pickup_date is in the past", 400)
    season = season_of(pickup)
    days = rental_days(pickup, dropoff)
    snapshot = quote_price(res["origin_location_id"], res["dest_location_id"],
                           res["equipment_type"], season, days)
    res["pickup_date"] = _iso(pickup)
    res["dropoff_date"] = _iso(dropoff)
    res["season"] = season
    res["rental_days"] = days
    res["price_snapshot"] = snapshot
    touch(res)
    return ok_object(pub(res))


@app.get("/rental-network/reservation-events")
def list_reservation_events():
    auth(["NetworkAdmin", "FinanceReviewer"])
    rows = list(db.reservation_events.values())
    for f in ("from_dealer_id", "to_dealer_id", "reservation_id"):
        v = request.args.get(f)
        if v:
            rows = [r for r in rows if r.get(f) == v]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/reservations/<rid>/events")
def reservation_events(rid):
    auth(["Customer", "DealerAgent", "NetworkAdmin", "FinanceReviewer"])
    get_or_404(db.reservations, rid, "Reservation")
    rows = [ev for ev in db.reservation_events.values()
            if ev["reservation_id"] == rid]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.post("/rental-network/reservations/<rid>/confirm")
def confirm_reservation(rid):
    user_id, _ = auth(["Customer"])
    res = get_or_404(db.reservations, rid, "Reservation")
    data = body()
    if res["customer_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "Not your reservation", 403)
    if res["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Reservation is not QUOTED", 409)
    expected = data.get("expected_reservation_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_reservation_version required", 400)
    if expected != res["version"]:
        raise ApiError("ERR_STALE_VERSION", "Reservation version mismatch", 412)
    customer = db.customers[res["customer_id"]]
    # priority 10: tow check
    tow_result = tow_check(res, customer)
    if tow_result == "FAIL":
        res["tow_check_result"] = "FAIL"
        raise ApiError("ERR_TOW_INCOMPATIBLE", "Towing compatibility check failed", 422)
    # priority 11: license
    if not customer["driver_license_verified"]:
        raise ApiError("ERR_LICENSE_NOT_VERIFIED", "Driver license not verified", 422)
    # priority 12: dealer posture
    dealer = db.dealers[res["origin_dealer_id"]]
    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_SUSPENDED", "Origin dealer is not ACTIVE", 409)
    # priority 16: active rate
    pickup = parse_dt(res["pickup_date"], "pickup_date")
    dropoff = parse_dt(res["dropoff_date"], "dropoff_date")
    season = season_of(pickup)
    days = rental_days(pickup, dropoff)
    snapshot = quote_price(res["origin_location_id"], res["dest_location_id"],
                           res["equipment_type"], season, days)
    # priority 15: availability
    chosen = None
    for u in sorted(db.equipment_units.values(), key=lambda x: x["created_at"]):
        if (u["current_dealer_id"] == res["origin_dealer_id"]
                and u["equipment_type"] == res["equipment_type"]
                and u["status"] == "AVAILABLE"):
            chosen = u
            break
    if chosen is None:
        raise ApiError("ERR_NO_UNIT_AVAILABLE",
                       "No AVAILABLE unit at origin dealer", 409)
    chosen["status"] = "HELD"
    chosen["_held_for_reservation_id"] = res["id"]
    touch(chosen)
    res["season"] = season
    res["rental_days"] = days
    res["price_snapshot"] = snapshot
    res["tow_check_result"] = tow_result
    res["status"] = "CONFIRMED"
    touch(res)
    append_event(res["id"], "CONFIRMED")
    return ok_object(pub(res))


@app.post("/rental-network/reservations/<rid>/reassign")
def reassign_reservation(rid):
    auth(["NetworkAdmin"])
    res = get_or_404(db.reservations, rid, "Reservation")
    if res["status"] not in ("CONFIRMED", "REASSIGNED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Reservation is not CONFIRMED or REASSIGNED", 409)
    result = _reassign_reservation_core(res, "manual reassignment")
    if result is None:
        raise ApiError("ERR_NO_REASSIGNMENT_CANDIDATE",
                       "No reassignment candidate available", 409)
    return ok_object(pub(res))


@app.post("/rental-network/reservations/<rid>/cancel")
def cancel_reservation(rid):
    user_id, _ = auth(["Customer"])
    res = get_or_404(db.reservations, rid, "Reservation")
    if res["status"] not in ("QUOTED", "CONFIRMED", "REASSIGNED"):
        raise ApiError("ERR_INVALID_STATE", "Reservation cannot be cancelled", 409)
    if res["customer_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "Not your reservation", 403)
    held = held_unit_for(res["id"])
    if held is not None:
        held["status"] = "AVAILABLE"
        held.pop("_held_for_reservation_id", None)
        touch(held)
    res["status"] = "CANCELLED"
    touch(res)
    append_event(res["id"], "CANCELLED")
    return ok_object(pub(res))


@app.post("/rental-network/reservations/<rid>/expire")
def expire_reservation(rid):
    auth(["NetworkAdmin"])
    res = get_or_404(db.reservations, rid, "Reservation")
    if res["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Reservation is not QUOTED", 409)
    res["status"] = "EXPIRED"
    touch(res)
    append_event(res["id"], "EXPIRED")
    return ok_object(pub(res))


@app.post("/rental-network/reservations/<rid>/mark-no-show")
def mark_no_show(rid):
    auth(["NetworkAdmin"])
    res = get_or_404(db.reservations, rid, "Reservation")
    if res["status"] not in ("CONFIRMED", "REASSIGNED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Reservation is not CONFIRMED or REASSIGNED", 409)
    pickup = parse_dt(res["pickup_date"], "pickup_date")
    if db.clock <= pickup:
        raise ApiError("ERR_INVALID_DATE_RANGE", "pickup_date has not passed", 400)
    held = held_unit_for(res["id"])
    if held is not None:
        held["status"] = "AVAILABLE"
        held.pop("_held_for_reservation_id", None)
        touch(held)
    res["status"] = "NO_SHOW"
    touch(res)
    append_event(res["id"], "NO_SHOW")
    return ok_object(pub(res))


# ---------------------------------------------------------------------------
# Rental agreements
# ---------------------------------------------------------------------------
@app.post("/rental-network/rental-agreements")
def create_agreement():
    auth(["DealerAgent"])
    data = body()
    reservation_id = req_str(data, "reservation_id")
    equipment_unit_id = req_str(data, "equipment_unit_id")
    return_location_id = req_str(data, "return_location_id")
    res = fk_or_ref404(db.reservations, reservation_id, "Reservation")
    unit = fk_or_ref404(db.equipment_units, equipment_unit_id, "EquipmentUnit")
    fk_or_ref404(db.locations, return_location_id, "Location")
    # uniqueness: one agreement per reservation
    if any(a["reservation_id"] == reservation_id for a in db.rental_agreements.values()):
        raise ApiError("ERR_DUPLICATE_RESOURCE",
                       "An agreement already exists for this reservation", 409)
    # state
    if res["status"] not in ("CONFIRMED", "REASSIGNED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Reservation is not CONFIRMED or REASSIGNED", 409)
    # priority 12: dealer posture + unit holding match
    dealer = db.dealers[res["origin_dealer_id"]]
    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_SUSPENDED", "Origin dealer is not ACTIVE", 409)
    held = held_unit_for(reservation_id)
    if unit["status"] != "HELD" or held is None or held["id"] != unit["id"]:
        raise ApiError("ERR_INVALID_STATE",
                       "Presented unit is not the HELD unit for this reservation", 409)
    if unit["current_dealer_id"] != res["origin_dealer_id"]:
        raise ApiError("ERR_DEALER_SUSPENDED",
                       "Unit's holding dealer does not match reservation origin dealer", 409)
    # priority 13: pickup dealer's location OPEN
    pickup_loc = db.locations[dealer["location_id"]]
    if pickup_loc["status"] != "OPEN":
        raise ApiError("ERR_LOCATION_CLOSED", "Pickup location is CLOSED", 409)
    ret_loc = db.locations[return_location_id]
    if ret_loc["status"] != "OPEN":
        raise ApiError("ERR_LOCATION_CLOSED", "Return location is CLOSED", 409)
    ag = new_entity(db.rental_agreements, {
        "reservation_id": reservation_id,
        "equipment_unit_id": equipment_unit_id,
        "checkout_dealer_id": res["origin_dealer_id"],
        "status": "ACTIVE",
        "checkout_at": _iso(db.clock),
        "returned_at": None,
        "actual_days": None,
        "return_location_id": return_location_id,
        "late_fee_cents": 0,
        "damage_charge_cents": 0,
        "total_settled_cents": None,
    })
    unit["status"] = "OUT"
    unit.pop("_held_for_reservation_id", None)
    touch(unit)
    res["status"] = "FULFILLED"
    touch(res)
    return ok_object(pub(ag), 201)


@app.get("/rental-network/rental-agreements")
def list_agreements():
    auth(["DealerAgent", "NetworkAdmin", "FinanceReviewer"])
    rows = list(db.rental_agreements.values())
    for f in ("checkout_dealer_id", "reservation_id", "equipment_unit_id",
              "return_location_id", "status"):
        v = request.args.get(f)
        if v:
            rows = [r for r in rows if r[f] == v]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/rental-agreements/<aid>")
def get_agreement(aid):
    auth(["DealerAgent", "NetworkAdmin", "FinanceReviewer"])
    return ok_object(pub(get_or_404(db.rental_agreements, aid, "RentalAgreement")))


@app.get("/rental-network/rental-agreements/<aid>/settlement-preview")
def settlement_preview(aid):
    auth(["DealerAgent", "NetworkAdmin"])
    ag = get_or_404(db.rental_agreements, aid, "RentalAgreement")
    if ag["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Agreement is not ACTIVE", 409)
    res = db.reservations[ag["reservation_id"]]
    checkout = parse_dt(ag["checkout_at"], "checkout_at")
    projected_days = ceil_days_between(checkout, db.clock)
    billable = max(projected_days, res["rental_days"])
    daily = res["price_snapshot"]["quoted_rate_cents_per_day"]
    base_cents = daily * billable
    late_days = max(0, projected_days - res["rental_days"])
    late_rate = round_half_up_int(Decimal(daily) * LATE_DAY_MULTIPLIER)
    late_fee = late_days * late_rate
    preview = dict(pub(ag))
    preview["actual_days"] = projected_days
    preview["late_fee_cents"] = late_fee
    preview["total_settled_cents"] = base_cents + late_fee
    return ok_object(preview)


def reconcile_damage_charges(ag):
    total = sum(c["approved_amount_cents"] or 0
                for c in db.damage_claims.values()
                if c["agreement_id"] == ag["id"] and c["status"] in ("APPROVED", "PAID"))
    ag["damage_charge_cents"] = total


@app.post("/rental-network/rental-agreements/<aid>/return")
def return_agreement(aid):
    auth(["DealerAgent"])
    ag = get_or_404(db.rental_agreements, aid, "RentalAgreement")
    if ag["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Agreement is not ACTIVE", 409)
    ret_loc = db.locations[ag["return_location_id"]]
    if ret_loc["status"] != "OPEN":
        raise ApiError("ERR_LOCATION_CLOSED", "Return location is CLOSED", 409)
    # active dealer at return location
    target_dealer = active_dealer_at_location(ag["return_location_id"])
    if target_dealer is None:
        raise ApiError("ERR_NO_ACTIVE_DEALER_AT_LOCATION",
                       "No ACTIVE dealer at return location", 409)
    unit = db.equipment_units[ag["equipment_unit_id"]]
    if unit["status"] != "OUT":
        raise ApiError("ERR_INVALID_STATE", "Unit is not OUT", 409)
    returned_at = db.clock
    checkout = parse_dt(ag["checkout_at"], "checkout_at")
    actual_days = ceil_days_between(checkout, returned_at)
    ag["returned_at"] = _iso(returned_at)
    ag["actual_days"] = actual_days
    res = db.reservations[ag["reservation_id"]]
    daily = res["price_snapshot"]["quoted_rate_cents_per_day"]
    late_days = max(0, actual_days - res["rental_days"])
    late_rate = round_half_up_int(Decimal(daily) * LATE_DAY_MULTIPLIER)
    ag["late_fee_cents"] = late_days * late_rate
    old_dealer_id = unit["current_dealer_id"]
    unit["status"] = "AVAILABLE"
    unit["current_location_id"] = ag["return_location_id"]
    unit["current_dealer_id"] = target_dealer["id"]
    touch(unit)
    recompute_alloc(old_dealer_id)
    recompute_alloc(target_dealer["id"])
    # expire active plan
    for plan in db.damage_protection_plans.values():
        if plan["agreement_id"] == ag["id"] and plan["status"] == "ACTIVE":
            plan["status"] = "EXPIRED"
            touch(plan)
    ag["status"] = "RETURNED"
    touch(ag)
    # lane imbalance recompute for one-way returns
    if res["rental_kind"] == "ONE_WAY":
        recompute_lane_imbalance(res["origin_location_id"], res["dest_location_id"])
    return ok_object(pub(ag))


@app.post("/rental-network/rental-agreements/<aid>/settle")
def settle_agreement(aid):
    auth(["DealerAgent"])
    ag = get_or_404(db.rental_agreements, aid, "RentalAgreement")
    data = body()
    if ag["status"] != "RETURNED":
        raise ApiError("ERR_INVALID_STATE", "Agreement is not RETURNED", 409)
    expected = data.get("expected_agreement_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_agreement_version required", 400)
    if expected != ag["version"]:
        raise ApiError("ERR_STALE_VERSION", "Agreement version mismatch", 412)
    for c in db.damage_claims.values():
        if c["agreement_id"] == ag["id"] and c["status"] == "FILED":
            raise ApiError("ERR_OPEN_CLAIMS", "Agreement has open damage claims", 409)
    res = db.reservations[ag["reservation_id"]]
    billable = max(ag["actual_days"], res["rental_days"])
    daily = res["price_snapshot"]["quoted_rate_cents_per_day"]
    base_cents = daily * billable
    late_days = max(0, ag["actual_days"] - res["rental_days"])
    late_rate = round_half_up_int(Decimal(daily) * LATE_DAY_MULTIPLIER)
    ag["late_fee_cents"] = late_days * late_rate
    reconcile_damage_charges(ag)
    ag["total_settled_cents"] = base_cents + ag["late_fee_cents"] + ag["damage_charge_cents"]
    ag["status"] = "SETTLED"
    touch(ag)
    return ok_object(pub(ag))


# ---------------------------------------------------------------------------
# Damage protection plans
# ---------------------------------------------------------------------------
@app.post("/rental-network/damage-protection-plans")
def create_plan():
    auth(["DealerAgent"])
    data = body()
    agreement_id = req_str(data, "agreement_id")
    tier = req_enum(data, "tier", PLAN_TIERS)
    ag = fk_or_ref404(db.rental_agreements, agreement_id, "RentalAgreement")
    if any(p["agreement_id"] == agreement_id for p in db.damage_protection_plans.values()):
        raise ApiError("ERR_DUPLICATE_RESOURCE",
                       "A plan already exists for this agreement", 409)
    if ag["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Agreement is not ACTIVE", 409)
    res = db.reservations[ag["reservation_id"]]
    days = res["rental_days"]
    premium = PLAN_DAILY_CENTS[tier] * days
    if days >= PLAN_LONG_DAYS:
        premium = round_half_up_int(Decimal(premium) * (Decimal("1") - PLAN_LONG_DISCOUNT))
    plan = new_entity(db.damage_protection_plans, {
        "agreement_id": agreement_id, "tier": tier,
        "premium_cents": premium, "status": "ACTIVE",
    })
    return ok_object(pub(plan), 201)


@app.get("/rental-network/damage-protection-plans")
def list_plans():
    auth(["DealerAgent", "NetworkAdmin", "FinanceReviewer"])
    rows = list(db.damage_protection_plans.values())
    for f in ("agreement_id", "status"):
        v = request.args.get(f)
        if v:
            rows = [r for r in rows if r[f] == v]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/damage-protection-plans/<pid>")
def get_plan(pid):
    auth(["DealerAgent", "NetworkAdmin", "FinanceReviewer"])
    return ok_object(pub(get_or_404(db.damage_protection_plans, pid, "DamageProtectionPlan")))


@app.post("/rental-network/damage-protection-plans/<pid>/cancel")
def cancel_plan(pid):
    auth(["DealerAgent"])
    plan = get_or_404(db.damage_protection_plans, pid, "DamageProtectionPlan")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Plan is not ACTIVE", 409)
    ag = db.rental_agreements[plan["agreement_id"]]
    if ag["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Agreement is not ACTIVE", 409)
    plan["status"] = "CANCELLED"
    touch(plan)
    for c in db.damage_claims.values():
        if c["agreement_id"] == ag["id"] and c["status"] == "FILED":
            c["status"] = "DENIED"
            touch(c)
    return ok_object(pub(plan))


# ---------------------------------------------------------------------------
# Damage claims
# ---------------------------------------------------------------------------
@app.post("/rental-network/damage-claims")
def create_claim():
    user_id, _ = auth(["DealerAgent"])
    data = body()
    agreement_id = req_str(data, "agreement_id")
    claimed = data.get("claimed_amount_cents")
    fk_or_ref404(db.rental_agreements, agreement_id, "RentalAgreement")
    if isinstance(claimed, bool) or not isinstance(claimed, int):
        raise ApiError("ERR_INVALID_REQUEST", "claimed_amount_cents must be an integer", 400)
    if claimed <= 0:
        raise ApiError("ERR_INVALID_CLAIM_AMOUNT", "claimed_amount_cents must be > 0", 422)
    claim = new_entity(db.damage_claims, {
        "agreement_id": agreement_id, "claimed_amount_cents": claimed,
        "status": "FILED", "approved_amount_cents": None,
        "resolution_note": None, "filer_user_id": user_id,
    })
    return ok_object(pub(claim), 201)


@app.get("/rental-network/damage-claims")
def list_claims():
    auth(["DealerAgent", "NetworkAdmin", "FinanceReviewer"])
    rows = list(db.damage_claims.values())
    for f in ("agreement_id", "status"):
        v = request.args.get(f)
        if v:
            rows = [r for r in rows if r[f] == v]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/damage-claims/<cid>")
def get_claim(cid):
    auth(["DealerAgent", "NetworkAdmin", "FinanceReviewer"])
    return ok_object(pub(get_or_404(db.damage_claims, cid, "DamageClaim")))


@app.post("/rental-network/damage-claims/<cid>/approve")
def approve_claim(cid):
    user_id, _ = auth(["DealerAgent"])
    claim = get_or_404(db.damage_claims, cid, "DamageClaim")
    data = body()
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not FILED", 409)
    if user_id == claim["filer_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Approver must differ from filer", 403)
    ag = db.rental_agreements[claim["agreement_id"]]
    if ag["status"] not in ("ACTIVE", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE", "Agreement is SETTLED", 409)
    # coverage cap from active plan; 0 when none
    cap = 0
    for p in db.damage_protection_plans.values():
        if p["agreement_id"] == ag["id"] and p["status"] == "ACTIVE":
            cap = PLAN_COVERAGE_CAP_CENTS[p["tier"]]
            break
    claim["approved_amount_cents"] = min(claim["claimed_amount_cents"], cap)
    note = data.get("resolution_note")
    if note is not None:
        claim["resolution_note"] = note
    claim["status"] = "APPROVED"
    touch(claim)
    reconcile_damage_charges(ag)
    touch(ag)
    return ok_object(pub(claim))


@app.post("/rental-network/damage-claims/<cid>/deny")
def deny_claim(cid):
    user_id, _ = auth(["DealerAgent"])
    claim = get_or_404(db.damage_claims, cid, "DamageClaim")
    data = body()
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not FILED", 409)
    if user_id == claim["filer_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Denier must differ from filer", 403)
    note = data.get("resolution_note")
    if note is not None:
        claim["resolution_note"] = note
    claim["status"] = "DENIED"
    touch(claim)
    return ok_object(pub(claim))


@app.post("/rental-network/damage-claims/<cid>/reopen")
def reopen_claim(cid):
    auth(["DealerAgent"])
    claim = get_or_404(db.damage_claims, cid, "DamageClaim")
    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not DENIED", 409)
    ag = db.rental_agreements[claim["agreement_id"]]
    if ag["status"] == "SETTLED":
        raise ApiError("ERR_INVALID_STATE", "Agreement is SETTLED", 409)
    claim["status"] = "FILED"
    touch(claim)
    return ok_object(pub(claim))


@app.post("/rental-network/damage-claims/<cid>/pay")
def pay_claim(cid):
    auth(["DealerAgent"])
    claim = get_or_404(db.damage_claims, cid, "DamageClaim")
    if claim["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not APPROVED", 409)
    ag = db.rental_agreements[claim["agreement_id"]]
    if ag["status"] != "SETTLED":
        raise ApiError("ERR_INVALID_STATE", "Agreement is not SETTLED", 409)
    claim["status"] = "PAID"
    touch(claim)
    return ok_object(pub(claim))


# ---------------------------------------------------------------------------
# Reposition tasks
# ---------------------------------------------------------------------------
@app.post("/rental-network/reposition-tasks")
def create_reposition_task():
    auth(["NetworkAdmin"])
    data = body()
    from_id = req_str(data, "from_location_id")
    to_id = req_str(data, "to_location_id")
    etype = req_enum(data, "equipment_type", EQUIPMENT_TYPES)
    from_loc = fk_or_ref404(db.locations, from_id, "From location")
    to_loc = fk_or_ref404(db.locations, to_id, "To location")
    # selector: earliest-created AVAILABLE unit of type at from_location
    chosen = None
    for u in sorted(db.equipment_units.values(), key=lambda x: x["created_at"]):
        if (u["current_location_id"] == from_id and u["equipment_type"] == etype
                and u["status"] == "AVAILABLE"):
            chosen = u
            break
    if chosen is None:
        raise ApiError("ERR_NO_UNIT_AVAILABLE",
                       "No AVAILABLE unit of the type at from_location", 409)
    band = distance_band(from_loc["geo_zone"], to_loc["geo_zone"])
    task = new_entity(db.reposition_tasks, {
        "equipment_unit_id": chosen["id"],
        "from_location_id": from_id, "to_location_id": to_id,
        "equipment_type": etype,
        "status": "OPEN", "assigned_driver_id": None,
        "estimated_reposition_cost_cents": REPOSITION_BAND_COST_CENTS[band],
        "executed_reposition_cost_cents": None,
        "scheduled_after": _iso(db.clock),
        "_repositioning_since": _iso(db.clock),
        "_distance_band": band,
    })
    chosen["status"] = "REPOSITIONING"
    touch(chosen)
    return ok_object(pub(task), 201)


@app.get("/rental-network/reposition-tasks/imbalance-report")
def imbalance_report():
    auth(["NetworkAdmin", "PricingManager"])
    etype = request.args.get("equipment_type")
    lanes = []
    for rate in db.lane_rates.values():
        if rate["status"] != "ACTIVE":
            continue
        if etype and rate["equipment_type"] != etype:
            continue
        factor = compute_imbalance(rate["origin_location_id"], rate["dest_location_id"],
                                   rate["equipment_type"], include_deficit=False)
        lanes.append({
            "origin_location_id": rate["origin_location_id"],
            "dest_location_id": rate["dest_location_id"],
            "equipment_type": rate["equipment_type"],
            "season": rate["season"],
            "imbalance_factor": factor,
        })
    return ok_object({"lanes": lanes})


@app.get("/rental-network/reposition-tasks")
def list_reposition_tasks():
    auth(["NetworkAdmin", "RepositionDriver", "FinanceReviewer"])
    rows = list(db.reposition_tasks.values())
    for f in ("from_location_id", "to_location_id", "equipment_unit_id", "status"):
        v = request.args.get(f)
        if v:
            rows = [r for r in rows if r[f] == v]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/reposition-tasks/<tid>")
def get_reposition_task(tid):
    auth(["NetworkAdmin", "RepositionDriver"])
    return ok_object(pub(get_or_404(db.reposition_tasks, tid, "RepositionTask")))


@app.post("/rental-network/reposition-tasks/<tid>/assign")
def assign_reposition_task(tid):
    auth(["NetworkAdmin"])
    task = get_or_404(db.reposition_tasks, tid, "RepositionTask")
    data = body()
    driver = req_str(data, "assigned_driver_id")
    if task["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Task is not OPEN", 409)
    unit = db.equipment_units[task["equipment_unit_id"]]
    if unit["status"] != "REPOSITIONING":
        raise ApiError("ERR_INVALID_STATE", "Unit is not REPOSITIONING", 409)
    task["assigned_driver_id"] = driver
    task["status"] = "ASSIGNED"
    touch(task)
    return ok_object(pub(task))


@app.post("/rental-network/reposition-tasks/<tid>/complete")
def complete_reposition_task(tid):
    user_id, _ = auth(["RepositionDriver"])
    task = get_or_404(db.reposition_tasks, tid, "RepositionTask")
    if task["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", "Task is not ASSIGNED", 409)
    if user_id != task["assigned_driver_id"]:
        raise ApiError("ERR_DRIVER_MISMATCH", "Driver identity mismatch", 403)
    # active dealer at destination
    target_dealer = active_dealer_at_location(task["to_location_id"])
    if target_dealer is None:
        raise ApiError("ERR_NO_ACTIVE_DEALER_AT_LOCATION",
                       "No ACTIVE dealer at destination location", 409)
    unit = db.equipment_units[task["equipment_unit_id"]]
    if unit["status"] != "REPOSITIONING":
        raise ApiError("ERR_INVALID_STATE", "Unit is not REPOSITIONING", 409)
    band = task.get("_distance_band") or distance_band(
        db.locations[task["from_location_id"]]["geo_zone"],
        db.locations[task["to_location_id"]]["geo_zone"])
    cost = REPOSITION_BAND_COST_CENTS[band] + DRIVER_FEE_CENTS_PER_TASK
    since = parse_dt(task["_repositioning_since"], "_repositioning_since")
    idle_seconds = (db.clock - since).total_seconds()
    if idle_seconds > IDLE_PENALTY_HOURS * 3600:
        cost += IDLE_PENALTY_CENTS
    task["executed_reposition_cost_cents"] = cost
    task["status"] = "COMPLETED"
    touch(task)
    old_dealer_id = unit["current_dealer_id"]
    unit["status"] = "AVAILABLE"
    unit["current_location_id"] = task["to_location_id"]
    unit["current_dealer_id"] = target_dealer["id"]
    touch(unit)
    recompute_alloc(old_dealer_id)
    recompute_alloc(target_dealer["id"])
    recompute_lane_imbalance(task["from_location_id"], task["to_location_id"])
    return ok_object(pub(task))


@app.post("/rental-network/reposition-tasks/<tid>/cancel")
def cancel_reposition_task(tid):
    auth(["NetworkAdmin"])
    task = get_or_404(db.reposition_tasks, tid, "RepositionTask")
    if task["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Task is not OPEN", 409)
    unit = db.equipment_units[task["equipment_unit_id"]]
    unit["status"] = "AVAILABLE"
    touch(unit)
    task["status"] = "CANCELLED"
    touch(task)
    recompute_lane_imbalance(task["from_location_id"], task["to_location_id"])
    return ok_object(pub(task))


# ---------------------------------------------------------------------------
# Cross-sell orders
# ---------------------------------------------------------------------------
@app.post("/rental-network/cross-sell-orders")
def create_cross_sell_order():
    auth(["DealerAgent"])
    data = body()
    dealer_id = req_str(data, "dealer_id")
    dealer = fk_or_ref404(db.dealers, dealer_id, "Dealer")
    agreement_id = data.get("agreement_id")
    if agreement_id is not None:
        fk_or_ref404(db.rental_agreements, agreement_id, "RentalAgreement")
    line_items = data.get("line_items")
    if not isinstance(line_items, list):
        raise ApiError("ERR_INVALID_REQUEST", "line_items must be an array", 400)
    storage_months = data.get("storage_months", 0)
    if isinstance(storage_months, bool) or not isinstance(storage_months, int) or storage_months < 0:
        raise ApiError("ERR_INVALID_REQUEST", "storage_months must be a non-negative integer", 400)
    supplies_subtotal = 0
    for item in line_items:
        if not isinstance(item, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Invalid line item", 400)
        sku = item.get("sku")
        qty = item.get("qty")
        if sku not in CATALOG_PRICE_CENTS:
            raise ApiError("ERR_INVALID_REQUEST", f"Unknown sku: {sku}", 400)
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "qty must be a positive integer", 400)
        supplies_subtotal += round_half_up_int(Decimal(CATALOG_PRICE_CENTS[sku]) * qty)
    dealer_loc = db.locations[dealer["location_id"]]
    zone = dealer_loc["geo_zone"]
    storage_charge = storage_months * STORAGE_MONTH_RATE_CENTS[zone]
    if storage_months > 0 and supplies_subtotal > 0:
        bundle_discount = round_half_up_int(Decimal(supplies_subtotal) * BUNDLE_DISCOUNT_RATE)
    else:
        bundle_discount = 0
    total = supplies_subtotal + storage_charge - bundle_discount
    # zone capacity check
    if storage_months > 0:
        zone_location_ids = {l["id"] for l in db.locations.values()
                             if l["geo_zone"] == zone}
        occupied = 0
        for o in db.cross_sell_orders.values():
            o_dealer = db.dealers.get(o["dealer_id"])
            if o_dealer and o_dealer["location_id"] in zone_location_ids:
                occupied += o["storage_months"]
        capacity = sum(l["storage_capacity"] for l in db.locations.values()
                       if l["geo_zone"] == zone and l["status"] == "OPEN")
        if occupied + storage_months > capacity:
            raise ApiError("ERR_STORAGE_CAPACITY_EXCEEDED",
                           "Zone storage capacity exceeded", 409)
    order = new_entity(db.cross_sell_orders, {
        "dealer_id": dealer_id, "agreement_id": agreement_id,
        "line_items": line_items, "storage_months": storage_months,
        "supplies_subtotal_cents": supplies_subtotal,
        "storage_charge_cents": storage_charge,
        "bundle_discount_cents": bundle_discount,
        "total_cents": total,
    })
    return ok_object(pub(order), 201)


@app.get("/rental-network/cross-sell-orders")
def list_cross_sell_orders():
    auth(["DealerAgent", "NetworkAdmin", "FinanceReviewer"])
    rows = list(db.cross_sell_orders.values())
    for f in ("dealer_id", "agreement_id"):
        v = request.args.get(f)
        if v:
            rows = [r for r in rows if r[f] == v]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/cross-sell-orders/<oid>")
def get_cross_sell_order(oid):
    auth(["DealerAgent", "NetworkAdmin", "FinanceReviewer"])
    return ok_object(pub(get_or_404(db.cross_sell_orders, oid, "CrossSellOrder")))


# ---------------------------------------------------------------------------
# Dealer settlements
# ---------------------------------------------------------------------------
def compute_settlement(dealer, period):
    start, end = quarter_window(period)
    scope = []
    for ag in db.rental_agreements.values():
        if ag["checkout_dealer_id"] != dealer["id"] or ag["status"] != "SETTLED":
            continue
        if ag["returned_at"] is None:
            continue
        ret = parse_dt(ag["returned_at"], "returned_at")
        if start <= ret < end:
            scope.append(ag)
    gross = sum(ag["total_settled_cents"] or 0 for ag in scope)
    commission = 0
    for ag in scope:
        res = db.reservations[ag["reservation_id"]]
        if dealer["commission_rate_override"] is not None:
            pinned = dealer["commission_rate_override"]
        else:
            checkout = parse_dt(ag["checkout_at"], "checkout_at")
            season = season_of(checkout)
            rate = active_lane_rate(res["origin_location_id"],
                                    res["dest_location_id"],
                                    res["equipment_type"], season)
            pinned = rate["commission_rate"] if rate else res["price_snapshot"]["commission_rate"]
        commission += round_half_up_int(
            Decimal(ag["total_settled_cents"]) * Decimal(str(pinned)))
    cross = 0
    for o in db.cross_sell_orders.values():
        if o["dealer_id"] != dealer["id"]:
            continue
        created = parse_dt(o["created_at"], "created_at")
        if start <= created < end:
            cross += round_half_up_int(
                Decimal(o["total_cents"]) * CROSS_SELL_COMMISSION_RATE)
    perf = Decimal(str(dealer["performance_score"]))
    if perf < PERFORMANCE_FLOOR:
        clawback = round_half_up_int(
            Decimal(commission + cross) * CLAWBACK_RATE)
    else:
        clawback = 0
    net = commission + cross - clawback
    return {
        "gross_rental_cents": gross,
        "commission_cents": commission,
        "cross_sell_commission_cents": cross,
        "clawback_cents": clawback,
        "net_cents": net,
    }


@app.post("/rental-network/dealer-settlements")
def create_settlement():
    auth(["FinanceReviewer"])
    data = body()
    dealer_id = req_str(data, "dealer_id")
    period = req_str(data, "period")
    dealer = fk_or_ref404(db.dealers, dealer_id, "Dealer")
    figures = compute_settlement(dealer, period)
    st = new_entity(db.dealer_settlements, {
        "dealer_id": dealer_id, "period": period, "status": "DRAFT",
        "_approved_by": None,
        **figures,
    })
    return ok_object(pub(st), 201)


@app.get("/rental-network/dealer-settlements")
def list_settlements():
    auth(["FinanceReviewer", "NetworkAdmin", "DealerAgent"])
    rows = list(db.dealer_settlements.values())
    for f in ("dealer_id", "period", "status"):
        v = request.args.get(f)
        if v:
            rows = [r for r in rows if r[f] == v]
    rows.sort(key=lambda r: r["created_at"])
    return paginate([pub(r) for r in rows])


@app.get("/rental-network/dealer-settlements/<sid>")
def get_settlement(sid):
    auth(["FinanceReviewer", "NetworkAdmin", "DealerAgent"])
    return ok_object(pub(get_or_404(db.dealer_settlements, sid, "DealerSettlement")))


@app.post("/rental-network/dealer-settlements/<sid>/approve")
def approve_settlement(sid):
    user_id, _ = auth(["FinanceReviewer"])
    st = get_or_404(db.dealer_settlements, sid, "DealerSettlement")
    if st["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE", "Settlement is not DRAFT or DISPUTED", 409)
    dealer = db.dealers[st["dealer_id"]]
    # Scope is defined as SETTLED agreements only (calculation input_set), so the
    # "all agreements in scope are SETTLED" precondition holds by construction.
    figures = compute_settlement(dealer, st["period"])
    st.update(figures)
    st["status"] = "APPROVED"
    st["_approved_by"] = user_id
    touch(st)
    return ok_object(pub(st))


@app.post("/rental-network/dealer-settlements/<sid>/dispute")
def dispute_settlement(sid):
    user_id, _ = auth(["DealerAgent"])
    st = get_or_404(db.dealer_settlements, sid, "DealerSettlement")
    if st["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Settlement is not DRAFT", 409)
    if st["dealer_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "Not your settlement", 403)
    st["status"] = "DISPUTED"
    touch(st)
    return ok_object(pub(st))


@app.post("/rental-network/dealer-settlements/<sid>/pay")
def pay_settlement(sid):
    user_id, _ = auth(["FinanceReviewer"])
    st = get_or_404(db.dealer_settlements, sid, "DealerSettlement")
    if st["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Settlement is not APPROVED", 409)
    if st.get("_approved_by") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Payer must differ from approver", 403)
    st["status"] = "PAID"
    touch(st)
    return ok_object(pub(st))


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
