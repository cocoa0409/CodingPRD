"""Scheduled Train Plan & Car Trip Plan Compliance API (Union Pacific).

In-memory Flask implementation. All state lives in process-local dicts;
restarting the process wipes every byte. No entity seeding at startup.
"""
import os
import re
import uuid
import secrets
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PLAN_SPEED_MPH = Decimal("25.0")
HOS_MAX_HOURS = Decimal("12.0")
DEPARTURE_DELAY_THRESHOLD_MINUTES = 30

CLOCK_START = datetime(2026, 9, 1, tzinfo=timezone.utc)

ROLES = {
    "NetworkPlanner",
    "CrewDispatcher",
    "PowerPlanner",
    "TerminalSuperintendent",
    "ServiceManager",
    "Any",
}

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
FREQ_MASK_VALUES = set(WEEKDAYS)

CRAFT_VALUES = {"CONDUCTOR", "ENGINEER"}
EVENT_TYPES = {"TRAIN_DEPARTURE", "YARD_ARRIVAL", "CLASSIFICATION_COMPLETE", "PLACED_DELIVERED"}
ROOT_CAUSE_CODES = {"CREW_SHORTAGE", "POWER_SHORTAGE", "YARD_CONGESTION", "CUSTOMER_DELAY", "OTHER"}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------------------------------------------------------------------------
# In-memory store (module-level; process restart wipes everything)
# ---------------------------------------------------------------------------
db = {
    "yards": {},
    "train_plans": {},
    "crew_pools": {},
    "locomotives": {},
    "customers": {},
    "shipments": {},
    "trip_legs": {},
    "departures": {},
    "car_events": {},
    "exceptions": {},
}

logical_clock = {"now": CLOCK_START}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# ---------------------------------------------------------------------------
# Response envelope helpers
# ---------------------------------------------------------------------------
def _now_ts():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": _now_ts(),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Route not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed."},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def _parse_dt(value):
    """Parse an ISO-8601 datetime string. Returns aware datetime or None."""
    if not isinstance(value, str):
        return None
    try:
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _round4(value):
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _dec(value):
    """Parse a value into Decimal; None if impossible."""
    try:
        return Decimal(str(value))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def current_role():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and role must be recognized.",
            400,
        )
    return role


def require_role(*roles):
    role = current_role()
    if "Any" in roles:
        return role
    if role not in roles:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Role not permitted for this endpoint.",
            403,
        )
    return role


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def _body():
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be valid JSON.", 400)
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.", 400)
    return data


def _invalid(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg, 400)


def _req(data, field):
    if field not in data or data[field] is None:
        _invalid(f"Missing required field: {field}")
    return data[field]


def _req_str(data, field):
    v = _req(data, field)
    if not isinstance(v, str) or v == "":
        _invalid(f"Field {field} must be a non-empty string.")
    return v


def _req_int(data, field, min_val=None):
    v = _req(data, field)
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid(f"Field {field} must be an integer.")
    if min_val is not None and v < min_val:
        _invalid(f"Field {field} must be >= {min_val}.")
    return v


def _req_num_dec(data, field, min_val=None, min_exclusive=False):
    v = _req(data, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _invalid(f"Field {field} must be a number.")
    d = _dec(v)
    if d is None:
        _invalid(f"Field {field} must be a number.")
    if min_val is not None:
        if min_exclusive:
            if not (d > Decimal(str(min_val))):
                _invalid(f"Field {field} must be > {min_val}.")
        else:
            if not (d >= Decimal(str(min_val))):
                _invalid(f"Field {field} must be >= {min_val}.")
    return d


def _req_dt(data, field):
    v = _req(data, field)
    dt = _parse_dt(v)
    if dt is None:
        _invalid(f"Field {field} must be an ISO-8601 datetime.")
    return dt


def _req_enum(data, field, allowed):
    v = _req(data, field)
    if not isinstance(v, str) or v not in allowed:
        _invalid(f"Field {field} has an invalid value.")
    return v


def _req_date(data, field):
    v = _req(data, field)
    if not isinstance(v, str) or not DATE_RE.match(v):
        _invalid(f"Field {field} must be YYYY-MM-DD.")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        _invalid(f"Field {field} must be a valid date.")
    return v


def _num_out(dec):
    """Render a Decimal as a JSON number (int when integral)."""
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def _pagination():
    qs = request.args
    limit = 10
    offset = 0
    if "limit" in qs:
        try:
            limit = int(qs.get("limit"))
        except (TypeError, ValueError):
            _invalid("limit must be an integer.")
        if limit < 1 or limit > 100:
            _invalid("limit must be between 1 and 100.")
    if "offset" in qs:
        try:
            offset = int(qs.get("offset"))
        except (TypeError, ValueError):
            _invalid("offset must be an integer.")
        if offset < 0:
            _invalid("offset must be >= 0.")
    return limit, offset


def _list_response(records, serializer):
    limit, offset = _pagination()
    records = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Resource creation helpers
# ---------------------------------------------------------------------------
def _new_record():
    now = logical_clock["now"]
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def _touch(rec):
    rec["updated_at"] = logical_clock["now"]


def _bump(rec):
    rec["version"] += 1
    _touch(rec)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_yard(y):
    return {
        "id": y["id"],
        "yard_code": y["yard_code"],
        "dwell_benchmark_hours": _num_out(y["dwell_benchmark_hours"]),
        "classification_capacity_cars": y["classification_capacity_cars"],
        "posture": y["posture"],
        "current_dwell_overage_hours": _num_out(Decimal(str(y["current_dwell_overage_hours"]))),
        "created_at": _iso(y["created_at"]),
        "updated_at": _iso(y["updated_at"]),
        "version": y["version"],
    }


def ser_plan(p):
    return {
        "id": p["id"],
        "train_symbol": p["train_symbol"],
        "origin_yard_id": p["origin_yard_id"],
        "destination_yard_id": p["destination_yard_id"],
        "scheduled_departure_utc": _iso(p["scheduled_departure_utc"]),
        "cutoff_minutes": p["cutoff_minutes"],
        "frequency_mask": list(p["frequency_mask"]),
        "route_distance_miles": _num_out(p["route_distance_miles"]),
        "dwell_benchmark_hours": _num_out(p["dwell_benchmark_hours"]),
        "status": p["status"],
        "created_at": _iso(p["created_at"]),
        "updated_at": _iso(p["updated_at"]),
        "version": p["version"],
    }


def ser_pool(p):
    return {
        "id": p["id"],
        "home_yard_id": p["home_yard_id"],
        "craft": p["craft"],
        "service_date": p["service_date"],
        "crews_available": p["crews_available"],
        "crews_booked": p["crews_booked"],
        "status": p["status"],
        "created_at": _iso(p["created_at"]),
        "updated_at": _iso(p["updated_at"]),
        "version": p["version"],
    }


def ser_loco(l):
    return {
        "id": l["id"],
        "unit_number": l["unit_number"],
        "current_yard_id": l["current_yard_id"],
        "horsepower": l["horsepower"],
        "status": l["status"],
        "created_at": _iso(l["created_at"]),
        "updated_at": _iso(l["updated_at"]),
        "version": l["version"],
    }


def ser_customer(c):
    return {
        "id": c["id"],
        "customer_code": c["customer_code"],
        "name": c["name"],
        "service_credit_balance": c["service_credit_balance"],
        "created_at": _iso(c["created_at"]),
        "updated_at": _iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_shipment(s):
    return {
        "id": s["id"],
        "customer_id": s["customer_id"],
        "origin_yard_id": s["origin_yard_id"],
        "destination_yard_id": s["destination_yard_id"],
        "car_count": s["car_count"],
        "first_mile_pickup_by": _iso(s["first_mile_pickup_by"]),
        "last_mile_delivery_by": _iso(s["last_mile_delivery_by"]),
        "committed_route_miles": _num_out(s["committed_route_miles"]),
        "trip_plan_status": s["trip_plan_status"],
        "compliance_status": s["compliance_status"],
        "car_velocity_mph": s["car_velocity_mph"],
        "plan_velocity_mph": s.get("plan_velocity_mph"),
        "total_missed_connections": s["total_missed_connections"],
        "status": s["status"],
        "created_at": _iso(s["created_at"]),
        "updated_at": _iso(s["updated_at"]),
        "version": s["version"],
    }


def ser_leg(l):
    return {
        "id": l["id"],
        "shipment_id": l["shipment_id"],
        "train_plan_id": l["train_plan_id"],
        "leg_sequence": l["leg_sequence"],
        "planned_connection_time": _iso(l["planned_connection_time"]),
        "planned_departure_utc": _iso(l["planned_departure_utc"]),
        "actual_departure_utc": _iso(l["actual_departure_utc"]),
        "connection_status": l["connection_status"],
        "status": l["status"],
        "created_at": _iso(l["created_at"]),
        "updated_at": _iso(l["updated_at"]),
        "version": l["version"],
    }


def ser_departure(d):
    return {
        "id": d["id"],
        "train_plan_id": d["train_plan_id"],
        "service_date": d["service_date"],
        "crew_pool_id": d["crew_pool_id"],
        "locomotive_id": d["locomotive_id"],
        "car_count_planned": d["car_count_planned"],
        "crew_hours_estimated": _num_out(d["crew_hours_estimated"]),
        "actual_departure_utc": _iso(d["actual_departure_utc"]),
        "departure_variance_minutes": d["departure_variance_minutes"],
        "status": d["status"],
        "created_at": _iso(d["created_at"]),
        "updated_at": _iso(d["updated_at"]),
        "version": d["version"],
    }


def ser_event(e):
    return {
        "id": e["id"],
        "shipment_id": e["shipment_id"],
        "yard_id": e["yard_id"],
        "event_type": e["event_type"],
        "occurred_at": _iso(e["occurred_at"]),
        "car_count": e["car_count"],
        "created_at": _iso(e["created_at"]),
    }


def ser_exception(x):
    return {
        "id": x["id"],
        "shipment_id": x["shipment_id"],
        "exception_type": x["exception_type"],
        "triage_notes": x.get("triage_notes"),
        "root_cause_code": x.get("root_cause_code"),
        "detected_at": _iso(x["detected_at"]),
        "status": x["status"],
        "created_at": _iso(x["created_at"]),
        "updated_at": _iso(x["updated_at"]),
        "version": x["version"],
    }


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def get_yard(yid):
    y = db["yards"].get(yid)
    if not y:
        raise ApiError("ERR_YARD_NOT_FOUND", "Yard not found.", 404)
    return y


def get_plan(pid):
    p = db["train_plans"].get(pid)
    if not p:
        raise ApiError("ERR_PLAN_NOT_FOUND", "Train plan not found.", 404)
    return p


def get_pool(pid):
    p = db["crew_pools"].get(pid)
    if not p:
        raise ApiError("ERR_POOL_NOT_FOUND", "Crew pool not found.", 404)
    return p


def get_loco(lid):
    l = db["locomotives"].get(lid)
    if not l:
        raise ApiError("ERR_UNIT_NOT_FOUND", "Locomotive not found.", 404)
    return l


def get_customer(cid):
    c = db["customers"].get(cid)
    if not c:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", "Customer not found.", 404)
    return c


def get_shipment(sid):
    s = db["shipments"].get(sid)
    if not s:
        raise ApiError("ERR_SHIPMENT_NOT_FOUND", "Shipment not found.", 404)
    return s


def get_leg(lid):
    l = db["trip_legs"].get(lid)
    if not l:
        raise ApiError("ERR_LEG_NOT_FOUND", "Trip leg not found.", 404)
    return l


def get_departure(did):
    d = db["departures"].get(did)
    if not d:
        raise ApiError("ERR_DEPARTURE_NOT_FOUND", "Train departure not found.", 404)
    return d


def get_exception(xid):
    x = db["exceptions"].get(xid)
    if not x:
        raise ApiError("ERR_EXCEPTION_NOT_FOUND", "Service exception not found.", 404)
    return x


# ---------------------------------------------------------------------------
# Domain logic
# ---------------------------------------------------------------------------
def recompute_yard_posture(yard):
    """Recompute current_dwell_overage_hours and posture from open dwell sessions."""
    now = logical_clock["now"]
    bench = Decimal(str(yard["dwell_benchmark_hours"]))
    total = Decimal("0")
    for ev in db["car_events"].values():
        if ev["yard_id"] != yard["id"] or ev["event_type"] != "YARD_ARRIVAL":
            continue
        # open session: no closing event for same shipment at same yard
        closed = False
        for ev2 in db["car_events"].values():
            if ev2["shipment_id"] != ev["shipment_id"] or ev2["yard_id"] != yard["id"]:
                continue
            if ev2["event_type"] in ("TRAIN_DEPARTURE", "CLASSIFICATION_COMPLETE", "PLACED_DELIVERED"):
                # must come after the arrival (by occurred_at, tie-break created_at)
                if (ev2["occurred_at"], ev2["created_at"]) >= (ev["occurred_at"], ev["created_at"]):
                    if ev2["id"] != ev["id"]:
                        closed = True
                        break
        if closed:
            continue
        elapsed_hours = Decimal(str((now - ev["occurred_at"]).total_seconds())) / Decimal("3600")
        overage = elapsed_hours - bench
        if overage > 0:
            total += overage
    if total < 0:
        total = Decimal("0")
    total = total.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    yard["current_dwell_overage_hours"] = total
    if total <= bench:
        posture = "OPEN"
    elif total <= bench * 2:
        posture = "CONGESTED"
    else:
        posture = "EMBARGOED"
    yard["posture"] = posture


def recompute_all_postures():
    for y in db["yards"].values():
        recompute_yard_posture(y)


def raise_exception(shipment_id, exception_type):
    rec = _new_record()
    rec.update({
        "shipment_id": shipment_id,
        "exception_type": exception_type,
        "triage_notes": None,
        "root_cause_code": None,
        "detected_at": logical_clock["now"],
        "status": "OPEN",
    })
    db["exceptions"][rec["id"]] = rec
    return rec


def recompute_compliance(shipment):
    """Derive compliance_status from legs / exceptions / delivery state."""
    if shipment["compliance_status"] == "OFF_PLAN":
        return  # sticky
    if shipment["total_missed_connections"] >= 2:
        shipment["compliance_status"] = "OFF_PLAN"
        return
    at_risk = False
    if shipment["total_missed_connections"] == 1:
        at_risk = True
    if not at_risk:
        for x in db["exceptions"].values():
            if (
                x["shipment_id"] == shipment["id"]
                and x["exception_type"] == "DEPARTURE_DELAY"
                and x["status"] != "RESOLVED"
            ):
                at_risk = True
                break
    shipment["compliance_status"] = "AT_RISK" if at_risk else "ON_PLAN"


def _transit_hours(plan):
    return Decimal(str(plan["route_distance_miles"])) / PLAN_SPEED_MPH


def _miss_leg(leg, cascade=True):
    """Move a leg to MISSED and fire the missed-connection cascade."""
    if leg["status"] not in ("PLANNED", "EN_ROUTE"):
        return
    leg["status"] = "MISSED"
    leg["connection_status"] = "MISSED"
    _bump(leg)
    shipment = db["shipments"].get(leg["shipment_id"])
    if shipment is None:
        return
    shipment["total_missed_connections"] += 1
    shipment["trip_plan_status"] = "MISSED_CONNECTION"
    _touch(shipment)
    raise_exception(shipment["id"], "MISSED_CONNECTION")
    recompute_compliance(shipment)
    if cascade:
        # every later leg still PLANNED misses too
        later = [
            l for l in db["trip_legs"].values()
            if l["shipment_id"] == shipment["id"]
            and l["leg_sequence"] > leg["leg_sequence"]
            and l["status"] == "PLANNED"
        ]
        later.sort(key=lambda l: l["leg_sequence"])
        for nxt in later:
            _miss_leg(nxt, cascade=False)


def _open_dwell_exists(shipment_id, yard_id, exclude_event_id=None):
    """Whether the shipment has an open dwell session at the yard."""
    arrivals = [
        e for e in db["car_events"].values()
        if e["shipment_id"] == shipment_id and e["yard_id"] == yard_id and e["event_type"] == "YARD_ARRIVAL"
    ]
    arrivals.sort(key=lambda e: (e["occurred_at"], e["created_at"]))
    closers = [
        e for e in db["car_events"].values()
        if e["shipment_id"] == shipment_id
        and e["yard_id"] == yard_id
        and e["event_type"] in ("TRAIN_DEPARTURE", "CLASSIFICATION_COMPLETE", "PLACED_DELIVERED")
        and (exclude_event_id is None or e["id"] != exclude_event_id)
    ]
    closers.sort(key=lambda e: (e["occurred_at"], e["created_at"]))
    for arr in arrivals:
        matched = False
        for c in closers:
            if (c["occurred_at"], c["created_at"]) >= (arr["occurred_at"], arr["created_at"]):
                matched = True
                break
        if not matched:
            return True
    return False


def _shipment_events(shipment_id):
    evs = [e for e in db["car_events"].values() if e["shipment_id"] == shipment_id]
    evs.sort(key=lambda e: (e["occurred_at"], e["created_at"]))
    return evs


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@app.post("/rail/_clock/set_current_utc")
def set_clock():
    require_role("NetworkPlanner")
    data = _body()
    dt = _req_dt(data, "current_utc")
    logical_clock["now"] = dt
    recompute_all_postures()
    return ok({"current_utc": _iso(dt)}, 200)


# ---------------------------------------------------------------------------
# Yards
# ---------------------------------------------------------------------------
@app.post("/rail/yards")
def create_yard():
    require_role("NetworkPlanner")
    data = _body()
    yard_code = _req_str(data, "yard_code")
    bench = _req_num_dec(data, "dwell_benchmark_hours", min_val=0, min_exclusive=True)
    cap = _req_int(data, "classification_capacity_cars", min_val=1)
    rec = _new_record()
    rec.update({
        "yard_code": yard_code,
        "dwell_benchmark_hours": bench,
        "classification_capacity_cars": cap,
        "posture": "OPEN",
        "current_dwell_overage_hours": Decimal("0"),
    })
    db["yards"][rec["id"]] = rec
    return ok(ser_yard(rec), 201)


@app.get("/rail/yards")
def list_yards():
    require_role("Any")
    return _list_response(list(db["yards"].values()), ser_yard)


@app.get("/rail/yards/<yid>")
def get_yard_ep(yid):
    require_role("Any")
    return ok(ser_yard(get_yard(yid)), 200)


# ---------------------------------------------------------------------------
# Train plans
# ---------------------------------------------------------------------------
@app.post("/rail/train-plans")
def create_plan():
    require_role("NetworkPlanner")
    data = _body()
    symbol = _req_str(data, "train_symbol")
    origin_id = _req_str(data, "origin_yard_id")
    dest_id = _req_str(data, "destination_yard_id")
    dep = _req_dt(data, "scheduled_departure_utc")
    cutoff = _req_int(data, "cutoff_minutes", min_val=1)
    mask = _req(data, "frequency_mask")
    if not isinstance(mask, list) or len(mask) == 0:
        _invalid("frequency_mask must be a non-empty array.")
    for m in mask:
        if not isinstance(m, str) or m not in FREQ_MASK_VALUES:
            _invalid("frequency_mask contains an invalid day.")
    miles = _req_num_dec(data, "route_distance_miles", min_val=0, min_exclusive=True)
    bench = _req_num_dec(data, "dwell_benchmark_hours", min_val=0, min_exclusive=False)
    # existence left-to-right
    get_yard(origin_id)
    get_yard(dest_id)
    if origin_id == dest_id:
        raise ApiError("ERR_SAME_ORIGIN_DESTINATION", "origin and destination yards must differ.", 422)
    rec = _new_record()
    rec.update({
        "train_symbol": symbol,
        "origin_yard_id": origin_id,
        "destination_yard_id": dest_id,
        "scheduled_departure_utc": dep,
        "cutoff_minutes": cutoff,
        "frequency_mask": mask,
        "route_distance_miles": miles,
        "dwell_benchmark_hours": bench,
        "status": "DRAFT",
    })
    db["train_plans"][rec["id"]] = rec
    return ok(ser_plan(rec), 201)


@app.get("/rail/train-plans")
def list_plans():
    require_role("Any")
    items = list(db["train_plans"].values())
    for f in ("origin_yard_id", "destination_yard_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if p[f] == v]
    return _list_response(items, ser_plan)


@app.get("/rail/train-plans/<pid>")
def get_plan_ep(pid):
    require_role("Any")
    return ok(ser_plan(get_plan(pid)), 200)


def _occ_check(data, field, current):
    v = data.get(field)
    if v is None:
        _invalid(f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid(f"Field {field} must be an integer.")
    if v != current:
        raise ApiError("ERR_STALE_VERSION", "Expected version does not match current version.", 412)


@app.post("/rail/train-plans/<pid>/activate")
def activate_plan(pid):
    require_role("NetworkPlanner")
    plan = get_plan(pid)
    data = _body()
    _occ_check(data, "expected_train_plan_version", plan["version"])
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT", "Activate requires plan in DRAFT.", 409)
    plan["status"] = "ACTIVE"
    _bump(plan)
    return ok(ser_plan(plan), 200)


@app.post("/rail/train-plans/<pid>/retire")
def retire_plan(pid):
    require_role("NetworkPlanner")
    plan = get_plan(pid)
    data = _body()
    _occ_check(data, "expected_train_plan_version", plan["version"])
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "Retire requires plan in ACTIVE.", 409)
    for d in db["departures"].values():
        if d["train_plan_id"] == pid and d["status"] == "SCHEDULED":
            raise ApiError("ERR_PLAN_HAS_OPEN_DEPARTURES", "SCHEDULED departures exist for the plan.", 409)
    for l in db["trip_legs"].values():
        if l["train_plan_id"] == pid and l["status"] in ("PLANNED", "EN_ROUTE"):
            raise ApiError("ERR_PLAN_IN_USE", "PLANNED or EN_ROUTE trip legs reference the plan.", 409)
    plan["status"] = "RETIRED"
    _bump(plan)
    return ok(ser_plan(plan), 200)


# ---------------------------------------------------------------------------
# Crew pools
# ---------------------------------------------------------------------------
@app.post("/rail/crew-pools")
def create_pool():
    require_role("CrewDispatcher")
    data = _body()
    home_yard_id = _req_str(data, "home_yard_id")
    craft = _req_enum(data, "craft", CRAFT_VALUES)
    service_date = _req_date(data, "service_date")
    crews_available = _req_int(data, "crews_available", min_val=1)
    get_yard(home_yard_id)
    rec = _new_record()
    rec.update({
        "home_yard_id": home_yard_id,
        "craft": craft,
        "service_date": service_date,
        "crews_available": crews_available,
        "crews_booked": 0,
        "status": "OPEN",
    })
    db["crew_pools"][rec["id"]] = rec
    return ok(ser_pool(rec), 201)


@app.get("/rail/crew-pools")
def list_pools():
    require_role("Any")
    items = list(db["crew_pools"].values())
    for f in ("home_yard_id", "craft", "service_date", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if str(p[f]) == v]
    return _list_response(items, ser_pool)


@app.get("/rail/crew-pools/<pid>")
def get_pool_ep(pid):
    require_role("Any")
    return ok(ser_pool(get_pool(pid)), 200)


@app.post("/rail/crew-pools/<pid>/replenish")
def replenish_pool(pid):
    require_role("CrewDispatcher")
    pool = get_pool(pid)
    data = _body()
    if pool["status"] != "EXHAUSTED":
        raise ApiError("ERR_POOL_NOT_REPLENISHABLE", "Replenish requires pool EXHAUSTED.", 409)
    additional = _req_int(data, "additional_crews", min_val=1)
    pool["crews_available"] += additional
    pool["status"] = "REOPENED"
    _bump(pool)
    return ok(ser_pool(pool), 200)


@app.post("/rail/crew-pools/<pid>/close")
def close_pool(pid):
    require_role("CrewDispatcher")
    pool = get_pool(pid)
    _body()
    if pool["status"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_POOL_ALREADY_CLOSED", "Pool is not OPEN or REOPENED.", 409)
    if pool["crews_booked"] != 0:
        raise ApiError("ERR_POOL_HAS_BOOKED_CREWS", "Close requires crews_booked == 0.", 409)
    pool["status"] = "CLOSED"
    _bump(pool)
    return ok(ser_pool(pool), 200)


# ---------------------------------------------------------------------------
# Locomotives
# ---------------------------------------------------------------------------
@app.post("/rail/locomotives")
def create_loco():
    require_role("PowerPlanner")
    data = _body()
    unit = _req_str(data, "unit_number")
    yard_id = _req_str(data, "current_yard_id")
    hp = _req_int(data, "horsepower", min_val=1000)
    get_yard(yard_id)
    rec = _new_record()
    rec.update({
        "unit_number": unit,
        "current_yard_id": yard_id,
        "horsepower": hp,
        "status": "AVAILABLE",
    })
    db["locomotives"][rec["id"]] = rec
    return ok(ser_loco(rec), 201)


@app.get("/rail/locomotives")
def list_locos():
    require_role("Any")
    items = list(db["locomotives"].values())
    for f in ("current_yard_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l[f] == v]
    return _list_response(items, ser_loco)


@app.get("/rail/locomotives/<lid>")
def get_loco_ep(lid):
    require_role("Any")
    return ok(ser_loco(get_loco(lid)), 200)


@app.post("/rail/locomotives/<lid>/bad-order")
def bad_order(lid):
    require_role("PowerPlanner")
    loco = get_loco(lid)
    _body()
    if loco["status"] != "AVAILABLE":
        raise ApiError("ERR_UNIT_NOT_AVAILABLE", "bad-order requires AVAILABLE.", 409)
    loco["status"] = "BAD_ORDER"
    _bump(loco)
    return ok(ser_loco(loco), 200)


@app.post("/rail/locomotives/<lid>/release-repair")
def release_repair(lid):
    require_role("PowerPlanner")
    loco = get_loco(lid)
    _body()
    if loco["status"] != "BAD_ORDER":
        raise ApiError("ERR_UNIT_NOT_BAD_ORDER", "release-repair requires BAD_ORDER.", 409)
    loco["status"] = "AVAILABLE"
    _bump(loco)
    return ok(ser_loco(loco), 200)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@app.post("/rail/customers")
def create_customer():
    require_role("ServiceManager")
    data = _body()
    code = _req_str(data, "customer_code")
    name = _req_str(data, "name")
    rec = _new_record()
    rec.update({
        "customer_code": code,
        "name": name,
        "service_credit_balance": 0,
    })
    db["customers"][rec["id"]] = rec
    return ok(ser_customer(rec), 201)


@app.get("/rail/customers")
def list_customers():
    require_role("Any")
    return _list_response(list(db["customers"].values()), ser_customer)


@app.get("/rail/customers/<cid>")
def get_customer_ep(cid):
    require_role("Any")
    return ok(ser_customer(get_customer(cid)), 200)


@app.post("/rail/customers/<cid>/service-credits")
def adjust_credits(cid):
    require_role("ServiceManager")
    cust = get_customer(cid)
    data = _body()
    delta = _req_int(data, "delta")
    new_balance = cust["service_credit_balance"] + delta
    if new_balance < 0:
        raise ApiError("ERR_CREDIT_BALANCE_NEGATIVE", "Adjustment would drive balance below zero.", 422)
    cust["service_credit_balance"] = new_balance
    _bump(cust)
    return ok(ser_customer(cust), 200)


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------
@app.post("/rail/shipments")
def create_shipment():
    require_role("ServiceManager")
    data = _body()
    customer_id = _req_str(data, "customer_id")
    origin_id = _req_str(data, "origin_yard_id")
    dest_id = _req_str(data, "destination_yard_id")
    car_count = _req_int(data, "car_count", min_val=1)
    pickup = _req_dt(data, "first_mile_pickup_by")
    delivery = _req_dt(data, "last_mile_delivery_by")
    miles = _req_num_dec(data, "committed_route_miles", min_val=0, min_exclusive=True)
    # existence left-to-right
    get_customer(customer_id)
    origin = get_yard(origin_id)
    dest = get_yard(dest_id)
    if origin_id == dest_id:
        raise ApiError("ERR_SAME_ORIGIN_DESTINATION", "origin and destination yards must differ.", 422)
    if origin["posture"] == "EMBARGOED" or dest["posture"] == "EMBARGOED":
        raise ApiError("ERR_YARD_EMBARGOED", "Origin or destination yard is EMBARGOED.", 409)
    rec = _new_record()
    rec.update({
        "customer_id": customer_id,
        "origin_yard_id": origin_id,
        "destination_yard_id": dest_id,
        "car_count": car_count,
        "first_mile_pickup_by": pickup,
        "last_mile_delivery_by": delivery,
        "committed_route_miles": miles,
        "trip_plan_status": "UNASSIGNED",
        "compliance_status": "ON_PLAN",
        "car_velocity_mph": None,
        "plan_velocity_mph": None,
        "total_missed_connections": 0,
        "status": "OPEN",
    })
    db["shipments"][rec["id"]] = rec
    return ok(ser_shipment(rec), 201)


@app.get("/rail/shipments")
def list_shipments():
    require_role("Any")
    items = list(db["shipments"].values())
    for f in ("customer_id", "origin_yard_id", "destination_yard_id", "status", "compliance_status"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s[f] == v]
    return _list_response(items, ser_shipment)


@app.get("/rail/shipments/<sid>")
def get_shipment_ep(sid):
    require_role("Any")
    return ok(ser_shipment(get_shipment(sid)), 200)


@app.post("/rail/shipments/<sid>/cancel")
def cancel_shipment(sid):
    require_role("ServiceManager")
    shipment = get_shipment(sid)
    _body()
    if shipment["status"] != "OPEN":
        raise ApiError("ERR_SHIPMENT_NOT_CANCELLABLE", "Cancel requires shipment OPEN.", 409)
    shipment["status"] = "CANCELLED"
    for leg in db["trip_legs"].values():
        if leg["shipment_id"] == sid and leg["status"] == "PLANNED":
            leg["status"] = "REPLACED"
            _bump(leg)
    _bump(shipment)
    return ok(ser_shipment(shipment), 200)


# ---------------------------------------------------------------------------
# Trip legs
# ---------------------------------------------------------------------------
@app.post("/rail/shipments/<sid>/trip-legs")
def assign_trip_legs(sid):
    require_role("NetworkPlanner")
    shipment = get_shipment(sid)
    data = _body()
    _occ_check(data, "expected_shipment_version", shipment["version"])
    legs_in = data.get("legs")
    if not isinstance(legs_in, list) or len(legs_in) == 0:
        _invalid("legs must be a non-empty array.")
    # resolve plans (existence)
    plans = []
    seqs = []
    for leg in legs_in:
        if not isinstance(leg, dict):
            _invalid("each leg must be an object.")
        pid = leg.get("train_plan_id")
        if not isinstance(pid, str) or pid == "":
            _invalid("each leg requires train_plan_id.")
        seq = leg.get("leg_sequence")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            _invalid("each leg requires integer leg_sequence >= 1.")
        plans.append(get_plan(pid))
        seqs.append(seq)
    # structural integrity
    n = len(legs_in)
    order = sorted(range(n), key=lambda i: seqs[i])
    sorted_seqs = sorted(seqs)
    if sorted_seqs != list(range(1, n + 1)):
        raise ApiError("ERR_TRIP_PLAN_DISJOINT", "leg_sequence must be contiguous 1..N.", 422)
    sorted_plans = [plans[i] for i in order]
    for k in range(n - 1):
        if sorted_plans[k]["destination_yard_id"] != sorted_plans[k + 1]["origin_yard_id"]:
            raise ApiError("ERR_TRIP_PLAN_DISJOINT", "consecutive legs must chain.", 422)
    if sorted_plans[0]["origin_yard_id"] != shipment["origin_yard_id"]:
        raise ApiError("ERR_TRIP_PLAN_DISJOINT", "first leg origin must equal shipment origin.", 422)
    if sorted_plans[-1]["destination_yard_id"] != shipment["destination_yard_id"]:
        raise ApiError("ERR_TRIP_PLAN_DISJOINT", "last leg destination must equal shipment destination.", 422)
    # embargo gating: any leg endpoint yard
    endpoint_ids = set()
    for p in sorted_plans:
        endpoint_ids.add(p["origin_yard_id"])
        endpoint_ids.add(p["destination_yard_id"])
    for yid in endpoint_ids:
        y = db["yards"].get(yid)
        if y and y["posture"] == "EMBARGOED":
            raise ApiError("ERR_YARD_EMBARGOED", "A leg endpoint yard is EMBARGOED.", 409)
    # pickup window
    if logical_clock["now"] > shipment["first_mile_pickup_by"]:
        shipment["compliance_status"] = "OFF_PLAN"
        _touch(shipment)
        raise ApiError("ERR_PICKUP_WINDOW_MISSED", "Trip-plan assignment attempted after first_mile_pickup_by.", 409)
    # supersede prior legs
    had_prior = False
    prior_missed_connection = shipment["trip_plan_status"] == "MISSED_CONNECTION"
    for leg in db["trip_legs"].values():
        if leg["shipment_id"] == sid and leg["status"] in ("PLANNED", "MISSED"):
            leg["status"] = "REPLACED"
            _bump(leg)
            had_prior = True
    # create new legs
    new_legs = []
    for idx, plan in enumerate(sorted_plans):
        seq = idx + 1
        rec = _new_record()
        if seq == 1:
            conn_time = None
            conn_status = "NOT_APPLICABLE"
        else:
            prev_plan = sorted_plans[idx - 1]
            prev_transit = _transit_hours(prev_plan)
            conn_time = prev_plan["scheduled_departure_utc"] + timedelta(hours=float(prev_transit))
            conn_status = "PENDING"
        rec.update({
            "shipment_id": sid,
            "train_plan_id": plan["id"],
            "leg_sequence": seq,
            "planned_connection_time": conn_time,
            "planned_departure_utc": plan["scheduled_departure_utc"],
            "actual_departure_utc": None,
            "connection_status": conn_status,
            "status": "PLANNED",
        })
        db["trip_legs"][rec["id"]] = rec
        new_legs.append(rec)
    # plan velocity
    first_dep = sorted_plans[0]["scheduled_departure_utc"]
    last_plan = sorted_plans[-1]
    last_arrival = last_plan["scheduled_departure_utc"] + timedelta(hours=float(_transit_hours(last_plan)))
    total_hours = Decimal(str((last_arrival - first_dep).total_seconds())) / Decimal("3600")
    if total_hours > 0:
        pv = (Decimal(str(shipment["committed_route_miles"])) / total_hours).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        shipment["plan_velocity_mph"] = float(pv)
    else:
        shipment["plan_velocity_mph"] = float(shipment["committed_route_miles"])
    # trip plan status
    if prior_missed_connection or had_prior:
        shipment["trip_plan_status"] = "REPLANNED"
    else:
        shipment["trip_plan_status"] = "ASSIGNED"
    _bump(shipment)
    return ok([ser_leg(l) for l in new_legs], 201)


@app.get("/rail/shipments/<sid>/trip-legs")
def list_shipment_legs(sid):
    require_role("Any")
    get_shipment(sid)
    items = [l for l in db["trip_legs"].values() if l["shipment_id"] == sid]
    v = request.args.get("status")
    if v is not None:
        items = [l for l in items if l["status"] == v]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    limit, offset = _pagination()
    total = len(items)
    page = items[offset:offset + limit]
    page.sort(key=lambda l: (l["leg_sequence"], l["created_at"]))
    return ok_list([ser_leg(l) for l in page], limit, offset, total)


@app.get("/rail/trip-legs")
def list_legs():
    require_role("Any")
    items = list(db["trip_legs"].values())
    for f in ("shipment_id", "train_plan_id", "status", "connection_status"):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l[f] == v]
    return _list_response(items, ser_leg)


@app.get("/rail/trip-legs/<lid>")
def get_leg_ep(lid):
    require_role("Any")
    return ok(ser_leg(get_leg(lid)), 200)


# ---------------------------------------------------------------------------
# Train departures
# ---------------------------------------------------------------------------
@app.post("/rail/train-departures")
def create_departure():
    require_role("TerminalSuperintendent")
    data = _body()
    plan_id = _req_str(data, "train_plan_id")
    service_date = _req_date(data, "service_date")
    pool_id = _req_str(data, "crew_pool_id")
    loco_id = _req_str(data, "locomotive_id")
    car_count = _req_int(data, "car_count_planned", min_val=1)
    hours = _req_num_dec(data, "crew_hours_estimated", min_val=0, min_exclusive=True)
    plan = get_plan(plan_id)
    pool = get_pool(pool_id)
    loco = get_loco(loco_id)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "Scheduling requires an ACTIVE plan.", 409)
    if loco["status"] != "AVAILABLE":
        raise ApiError("ERR_UNIT_NOT_AVAILABLE", "Locomotive not AVAILABLE.", 409)
    if loco["current_yard_id"] != plan["origin_yard_id"]:
        raise ApiError("ERR_UNIT_WRONG_YARD", "Locomotive not positioned at plan origin.", 409)
    if pool["craft"] != "CONDUCTOR" or pool["home_yard_id"] != plan["origin_yard_id"]:
        raise ApiError("ERR_POOL_CRAFT_MISMATCH", "Pool must be CONDUCTOR homed at plan origin.", 409)
    weekday = WEEKDAYS[datetime.strptime(service_date, "%Y-%m-%d").weekday()]
    if weekday not in plan["frequency_mask"]:
        raise ApiError("ERR_DEPARTURE_DAY_NOT_OPERATED", "service_date is not an operating day.", 409)
    rec = _new_record()
    rec.update({
        "train_plan_id": plan_id,
        "service_date": service_date,
        "crew_pool_id": pool_id,
        "locomotive_id": loco_id,
        "car_count_planned": car_count,
        "crew_hours_estimated": hours,
        "actual_departure_utc": None,
        "departure_variance_minutes": None,
        "status": "SCHEDULED",
    })
    db["departures"][rec["id"]] = rec
    loco["status"] = "ASSIGNED"
    _bump(loco)
    return ok(ser_departure(rec), 201)


@app.get("/rail/train-departures")
def list_departures():
    require_role("Any")
    items = list(db["departures"].values())
    for f in ("train_plan_id", "crew_pool_id", "locomotive_id", "service_date", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [d for d in items if str(d[f]) == v]
    return _list_response(items, ser_departure)


@app.get("/rail/train-departures/<did>")
def get_departure_ep(did):
    require_role("Any")
    return ok(ser_departure(get_departure(did)), 200)


@app.post("/rail/train-departures/<did>/finalize")
def finalize_departure(did):
    require_role("TerminalSuperintendent")
    dep = get_departure(did)
    _body()
    plan = db["train_plans"].get(dep["train_plan_id"])
    pool = db["crew_pools"].get(dep["crew_pool_id"])
    if dep["status"] != "SCHEDULED":
        raise ApiError("ERR_DEPARTURE_NOT_FINALIZABLE", "Finalize requires SCHEDULED.", 409)
    if plan is None or plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "Plan must be ACTIVE.", 409)
    # crew pool status gate
    if pool is None or pool["status"] not in ("OPEN", "REOPENED") or pool["crews_booked"] >= pool["crews_available"]:
        raise ApiError("ERR_NO_CREW_AVAILABLE", "No crew available in pool.", 422)
    # HOS
    if Decimal(str(dep["crew_hours_estimated"])) > HOS_MAX_HOURS:
        raise ApiError("ERR_HOS_EXCEEDED", "crew_hours_estimated exceeds HOS maximum.", 422)
    # embargo on origin yard
    origin = db["yards"].get(plan["origin_yard_id"])
    if origin is not None:
        recompute_yard_posture(origin)
        if origin["posture"] == "EMBARGOED":
            raise ApiError("ERR_YARD_EMBARGOED", "Origin yard is EMBARGOED.", 409)
    # too early
    now = logical_clock["now"]
    if now < plan["scheduled_departure_utc"]:
        raise ApiError("ERR_DEPARTURE_TOO_EARLY", "Logical clock earlier than scheduled departure.", 409)
    # commit
    dep["actual_departure_utc"] = now
    variance = int((now - plan["scheduled_departure_utc"]).total_seconds() // 60)
    dep["departure_variance_minutes"] = variance
    dep["status"] = "DEPARTED"
    _bump(dep)
    # crew booking
    pool["crews_booked"] += 1
    if pool["crews_booked"] == pool["crews_available"]:
        pool["status"] = "EXHAUSTED"
    _bump(pool)
    # locomotive repositioning
    loco = db["locomotives"].get(dep["locomotive_id"])
    if loco is not None:
        loco["status"] = "AVAILABLE"
        loco["current_yard_id"] = plan["destination_yard_id"]
        _bump(loco)
    # delay cascade
    slot = plan["scheduled_departure_utc"]
    affected_legs = [
        l for l in db["trip_legs"].values()
        if l["train_plan_id"] == plan["id"]
        and l["status"] == "PLANNED"
        and l["planned_departure_utc"] == slot
    ]
    if variance > DEPARTURE_DELAY_THRESHOLD_MINUTES:
        shipment_ids = set()
        for l in affected_legs:
            shipment_ids.add(l["shipment_id"])
        for sid in shipment_ids:
            sh = db["shipments"].get(sid)
            if sh is None:
                continue
            raise_exception(sid, "DEPARTURE_DELAY")
            if sh["compliance_status"] == "ON_PLAN":
                sh["compliance_status"] = "AT_RISK"
            _touch(sh)
    # legs -> EN_ROUTE
    for l in affected_legs:
        sh = db["shipments"].get(l["shipment_id"])
        if sh is None or sh["status"] not in ("OPEN", "IN_TRANSIT"):
            continue
        l["status"] = "EN_ROUTE"
        l["actual_departure_utc"] = now
        _bump(l)
    return ok(ser_departure(dep), 200)


@app.post("/rail/train-departures/<did>/cancel")
def cancel_departure(did):
    require_role("TerminalSuperintendent")
    dep = get_departure(did)
    _body()
    if dep["status"] != "SCHEDULED":
        raise ApiError("ERR_DEPARTURE_NOT_FINALIZABLE", "Cancel requires SCHEDULED.", 409)
    plan = db["train_plans"].get(dep["train_plan_id"])
    dep["status"] = "CANCELLED"
    _bump(dep)
    loco = db["locomotives"].get(dep["locomotive_id"])
    if loco is not None:
        loco["status"] = "AVAILABLE"
        _bump(loco)
    if plan is not None:
        slot = plan["scheduled_departure_utc"]
        affected = [
            l for l in db["trip_legs"].values()
            if l["train_plan_id"] == plan["id"]
            and l["status"] == "PLANNED"
            and l["planned_departure_utc"] == slot
        ]
        affected.sort(key=lambda l: l["leg_sequence"])
        for l in affected:
            _miss_leg(l, cascade=True)
    return ok(ser_departure(dep), 200)


# ---------------------------------------------------------------------------
# Car events
# ---------------------------------------------------------------------------
@app.post("/rail/car-events")
def create_event():
    require_role("TerminalSuperintendent")
    data = _body()
    shipment_id = _req_str(data, "shipment_id")
    yard_id = _req_str(data, "yard_id")
    event_type = _req_enum(data, "event_type", EVENT_TYPES)
    occurred_at = _req_dt(data, "occurred_at")
    car_count = _req_int(data, "car_count", min_val=1)
    shipment = get_shipment(shipment_id)
    yard = get_yard(yard_id)
    if car_count > shipment["car_count"]:
        raise ApiError("ERR_EVENT_SEQUENCE_INVALID", "car_count exceeds shipment car_count.", 409)
    # terminal shipment
    if shipment["status"] in ("DELIVERED", "CANCELLED"):
        raise ApiError("ERR_EVENT_SEQUENCE_INVALID", "Event on terminal shipment.", 409)
    # clock match
    now = logical_clock["now"]
    if occurred_at != now:
        raise ApiError("ERR_EVENT_SEQUENCE_INVALID", "occurred_at must equal the logical clock.", 409)
    # outbound sequence integrity
    if event_type in ("TRAIN_DEPARTURE", "CLASSIFICATION_COMPLETE"):
        if not _open_dwell_exists(shipment_id, yard_id):
            # The shipment's very first outbound event at its own origin yard
            # has no open YARD_ARRIVAL by construction (the shipment begins
            # OPEN at the origin without any arrival event) and must be
            # accepted so the shipment can ever depart; any other outbound
            # event without an open YARD_ARRIVAL at that yard is rejected.
            has_prior_events = any(
                e["shipment_id"] == shipment_id for e in db["car_events"].values()
            )
            is_first_origin_outbound = (
                not has_prior_events
                and yard_id == shipment["origin_yard_id"]
            )
            if not is_first_origin_outbound:
                raise ApiError("ERR_EVENT_SEQUENCE_INVALID", "Outbound event without open YARD_ARRIVAL at yard.", 409)
    if event_type == "PLACED_DELIVERED":
        # delivered car count check at destination
        delivered_so_far = sum(
            e["car_count"] for e in db["car_events"].values()
            if e["shipment_id"] == shipment_id
            and e["yard_id"] == shipment["destination_yard_id"]
            and e["event_type"] == "PLACED_DELIVERED"
        )
        if delivered_so_far + car_count > shipment["car_count"]:
            raise ApiError("ERR_EVENT_SEQUENCE_INVALID", "car_count exceeds shipment remainder.", 409)
    # persist event
    rec = {
        "id": str(uuid.uuid4()),
        "shipment_id": shipment_id,
        "yard_id": yard_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "car_count": car_count,
        "created_at": now,
    }
    db["car_events"][rec["id"]] = rec

    # --- lifecycle effects ---
    if event_type == "TRAIN_DEPARTURE":
        if shipment["status"] == "OPEN":
            shipment["status"] = "IN_TRANSIT"
            _bump(shipment)
    elif event_type == "YARD_ARRIVAL":
        # complete the EN_ROUTE leg whose train destination is this yard
        enroute = [
            l for l in db["trip_legs"].values()
            if l["shipment_id"] == shipment_id and l["status"] == "EN_ROUTE"
        ]
        enroute.sort(key=lambda l: l["leg_sequence"])
        for l in enroute:
            plan = db["train_plans"].get(l["train_plan_id"])
            if plan is not None and plan["destination_yard_id"] == yard_id:
                l["status"] = "COMPLETED"
                _bump(l)
                # evaluate next leg connection window
                nxt = None
                for cand in db["trip_legs"].values():
                    if (
                        cand["shipment_id"] == shipment_id
                        and cand["status"] == "PLANNED"
                        and cand["leg_sequence"] == l["leg_sequence"] + 1
                    ):
                        nxt = cand
                        break
                if nxt is not None:
                    nxt_plan = db["train_plans"].get(nxt["train_plan_id"])
                    if nxt_plan is not None:
                        slack_seconds = (nxt["planned_departure_utc"] - occurred_at).total_seconds()
                        slack_minutes = int(slack_seconds // 60) if slack_seconds >= 0 else -int((-slack_seconds) // 60) - (1 if (-slack_seconds) % 60 else 0)
                        # truncate toward zero
                        slack_minutes = int(slack_seconds / 60)
                        if slack_minutes < nxt_plan["cutoff_minutes"]:
                            _miss_leg(nxt, cascade=True)
                        else:
                            nxt["connection_status"] = "MADE"
                            _bump(nxt)
                break
    elif event_type == "PLACED_DELIVERED":
        if yard_id == shipment["destination_yard_id"]:
            delivered = sum(
                e["car_count"] for e in db["car_events"].values()
                if e["shipment_id"] == shipment_id
                and e["yard_id"] == shipment["destination_yard_id"]
                and e["event_type"] == "PLACED_DELIVERED"
            )
            if delivered >= shipment["car_count"] and shipment["status"] == "IN_TRANSIT":
                shipment["status"] = "DELIVERED"
                # actual velocity
                first_dep = None
                for e in _shipment_events(shipment_id):
                    if e["event_type"] == "TRAIN_DEPARTURE":
                        first_dep = e
                        break
                if first_dep is not None:
                    elapsed_hours = Decimal(str((occurred_at - first_dep["occurred_at"]).total_seconds())) / Decimal("3600")
                    if elapsed_hours == 0:
                        vel = Decimal(str(shipment["committed_route_miles"]))
                    else:
                        vel = Decimal(str(shipment["committed_route_miles"])) / elapsed_hours
                    shipment["car_velocity_mph"] = float(vel.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
                # late check
                if occurred_at > shipment["last_mile_delivery_by"]:
                    shipment["compliance_status"] = "OFF_PLAN"
                    raise_exception(shipment_id, "DELIVERY_MISS")
                    cust = db["customers"].get(shipment["customer_id"])
                    if cust is not None:
                        cust["service_credit_balance"] += shipment["car_count"]
                        _bump(cust)
                _bump(shipment)
    # posture recompute
    recompute_yard_posture(yard)
    return ok(ser_event(rec), 201)


@app.get("/rail/car-events")
def list_events():
    require_role("Any")
    items = list(db["car_events"].values())
    for f in ("shipment_id", "yard_id", "event_type"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e[f] == v]
    limit, offset = _pagination()
    items = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([ser_event(e) for e in page], limit, offset, total)


@app.get("/rail/yards/<yid>/car-events")
def list_yard_events(yid):
    require_role("Any")
    get_yard(yid)
    items = [e for e in db["car_events"].values() if e["yard_id"] == yid]
    limit, offset = _pagination()
    items = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([ser_event(e) for e in page], limit, offset, total)


@app.get("/rail/shipments/<sid>/car-events")
def list_shipment_events(sid):
    require_role("Any")
    get_shipment(sid)
    items = [e for e in db["car_events"].values() if e["shipment_id"] == sid]
    limit, offset = _pagination()
    items = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([ser_event(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Service exceptions
# ---------------------------------------------------------------------------
@app.get("/rail/service-exceptions")
def list_exceptions():
    require_role("Any")
    items = list(db["exceptions"].values())
    for f in ("shipment_id", "exception_type", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [x for x in items if x[f] == v]
    return _list_response(items, ser_exception)


@app.get("/rail/shipments/<sid>/service-exceptions")
def list_shipment_exceptions(sid):
    require_role("Any")
    get_shipment(sid)
    items = [x for x in db["exceptions"].values() if x["shipment_id"] == sid]
    return _list_response(items, ser_exception)


@app.get("/rail/service-exceptions/<xid>")
def get_exception_ep(xid):
    require_role("Any")
    return ok(ser_exception(get_exception(xid)), 200)


@app.post("/rail/service-exceptions/<xid>/triage")
def triage_exception(xid):
    require_role("ServiceManager")
    exc = get_exception(xid)
    data = _body()
    notes = data.get("triage_notes")
    rcc = data.get("root_cause_code")
    if not isinstance(notes, str) or notes == "" or not isinstance(rcc, str) or rcc not in ROOT_CAUSE_CODES:
        _invalid("triage requires non-empty triage_notes and a valid root_cause_code.")
    if exc["status"] != "OPEN":
        raise ApiError("ERR_EXCEPTION_NOT_OPEN", "Triage requires exception OPEN.", 409)
    exc["triage_notes"] = notes
    exc["root_cause_code"] = rcc
    exc["status"] = "INVESTIGATING"
    _bump(exc)
    return ok(ser_exception(exc), 200)


@app.post("/rail/service-exceptions/<xid>/resolve")
def resolve_exception(xid):
    require_role("ServiceManager")
    exc = get_exception(xid)
    _body()
    if exc["status"] != "INVESTIGATING":
        raise ApiError("ERR_EXCEPTION_NOT_INVESTIGATING", "Resolve requires exception INVESTIGATING.", 409)
    if exc["exception_type"] == "MISSED_CONNECTION":
        shipment = db["shipments"].get(exc["shipment_id"])
        if shipment is None or shipment["trip_plan_status"] not in ("ASSIGNED", "REPLANNED"):
            raise ApiError(
                "ERR_EXCEPTION_NOT_RECOVERABLE",
                "MISSED_CONNECTION exception requires the shipment replanned first.",
                409,
            )
    exc["status"] = "RESOLVED"
    _bump(exc)
    return ok(ser_exception(exc), 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
