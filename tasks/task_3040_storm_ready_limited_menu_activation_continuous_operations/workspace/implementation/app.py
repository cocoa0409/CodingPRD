"""Storm-Ready Continuous Ops API — Flask implementation.

Single-process, in-memory store. Implements the contract in workspace/PRD.md.
Every state-sequenced write takes its own lock so interleaved requests can't
tear cascades; each test runs against a fresh server process.
"""
import os
import re
import threading
import uuid
from datetime import datetime, date, timedelta, timezone

from flask import Flask, request, jsonify

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {
    "CommandCenterAdmin",
    "UnitManager",
    "LogisticsPlanner",
    "FieldCoordinator",
    "ReliefCoordinator",
}
ALL_ROLES = sorted(ROLES)

UP_DOWN = {"UP", "DOWN"}
CREW_ROLES = {"GRILL_OP", "SERVER", "SHIFT_LEAD"}
ASSET_KINDS = {"GENERATOR", "MOBILE_KITCHEN"}
MENU_TIERS = {"TIER1_NO_POWER", "TIER2_NO_WATER", "TIER3_NO_GAS"}
CHECKLIST_KEYS = [
    "POWER_RESTORED",
    "WATER_POTABLE",
    "GAS_LEAK_CHECK",
    "FOOD_DISCARD_LOGGED",
    "CASH_DRAWER_COUNTED",
]
ITEM_RESULTS = {"PASS", "FAIL"}
CREW_MEMBER_STATUSES = {"AVAILABLE", "ASSIGNED", "INACTIVE"}
ASSIGNMENT_STATUSES = {"SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED"}
ASSET_STATUSES = {"IDLE", "ALLOCATED", "RETURNED", "RETIRED"}
ALLOCATION_STATUSES = {"RESERVED", "DEPLOYED", "RETURNED", "CANCELLED"}
BOOKING_STATUSES = {"CONFIRMED", "CANCELLED"}
RELIEF_ORG_STATUSES = {"ACTIVE", "SUSPENDED"}
PLEDGE_STATUSES = {"PLEDGED", "CONFIRMED", "CANCELLED"}
STORM_STATUSES = {"WATCH", "WARNING", "ACTIVE", "RECOVERY", "CLOSED", "CANCELLED"}
MENU_ACTIVATION_STATUSES = {"ACTIVE", "SUPERSEDED", "ENDED"}
CHECKLIST_STATUSES = {"IN_PROGRESS", "SUBMITTED", "APPROVED", "REJECTED"}
UNIT_MENU_TIERS = {"FULL", "TIER1_NO_POWER", "TIER2_NO_WATER", "TIER3_NO_GAS"}
NON_TERMINAL_STORMS = {"WATCH", "WARNING", "ACTIVE", "RECOVERY"}
OPEN_CHECKLIST_STATUSES = {"IN_PROGRESS", "SUBMITTED", "REJECTED"}

COLD_HOLD_LIMIT_HOURS = 4
SHIFT_CHANGE_INTERVAL_HOURS = 12
PREPOSITION_WINDOW_HOURS = 48
MEAL_RATE_CENTS = 250
TIER2_MIN_CENTS = 3000
TIER3_MIN_CENTS = 8000
TIER1_BONUS_CENTS = 0
TIER2_BONUS_CENTS = 1000
TIER3_BONUS_CENTS = 2500
SHORTFALL_PENALTY_PER_MEAL_CENTS = 100
TAX_BPS = 800

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err_unauthenticated(msg="Authentication headers missing or role not declared."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for this endpoint."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg="Resource not found."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_validation(msg="Request body failed validation."):
    return ApiError("ERR_VALIDATION", 422, msg)


def err_invalid_state(msg="Entity is not in a state that permits this transition."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version(msg="Expected version does not match current version."):
    return ApiError("ERR_STALE_VERSION", 412, msg)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

_clock_lock = threading.Lock()
_clock_now = None  # None until set; default epoch applied on first read

_CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def now_dt():
    with _clock_lock:
        if _clock_now is None:
            return _CLOCK_DEFAULT
        return _clock_now


def set_clock(dt):
    global _clock_now
    with _clock_lock:
        _clock_now = dt


def iso(dt):
    """ISO 8601 UTC with three fractional digits, 'Z' suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value, field="timestamp"):
    if not isinstance(value, str) or not ISO_RE.match(value):
        raise err_validation(f"Field '{field}' must be an ISO 8601 datetime string.")
    text = value
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # normalize offsets like +0000 -> +00:00
    m = re.search(r"([+-]\d{2})(\d{2})$", text)
    if m and ":" not in m.group(0):
        text = text[: m.start()] + m.group(1) + ":" + m.group(2)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise err_validation(f"Field '{field}' is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="service_date"):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise err_validation(f"Field '{field}' must be an ISO date (YYYY-MM-DD).")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise err_validation(f"Field '{field}' is not a valid calendar date.")


def epoch_seconds(dt):
    return (dt - EPOCH).total_seconds()


def hours_between(start, end):
    return int((end - start).total_seconds() // 3600)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class Store:
    seq_counter = 0

    def __init__(self):
        self.lock = threading.RLock()
        self.storms = {}
        self.units = {}
        self.crew_members = {}
        self.assignments = {}
        self.assets = {}
        self.allocations = {}
        self.bookings = {}
        self.activations = {}
        self.reports = {}
        self.checklists = {}
        self.checklist_items = {}  # run_id -> {key: item}
        self.cash_drops = {}
        self.relief_orgs = {}
        self.pledges = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_new(obj, with_version=True):
    # Global monotonic insertion sequence. The logical clock freezes across
    # many creates, so created_at alone cannot order them; `seq` preserves
    # the server-side acceptance order the "created_at ASC" contract needs.
    Store.seq_counter += 1
    ts = iso(now_dt())
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["seq"] = Store.seq_counter
    if with_version:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    ts = iso(now_dt())
    obj["updated_at"] = ts
    obj["version"] += 1


def get_or_404(mapping, key, label="resource"):
    obj = mapping.get(key)
    if obj is None:
        raise err_not_found(f"{label} '{key}' not found.")
    return obj


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def success(data, status=200, pagination=None):
    meta = _meta()
    body = {
        "meta": meta,
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# Auth / role gating
# ---------------------------------------------------------------------------


def require_roles(allowed):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or uid is None or role not in ROLES:
        raise err_unauthenticated()
    if role not in allowed:
        raise err_forbidden()
    return uid, role


# ---------------------------------------------------------------------------
# Body parsing helpers
# ---------------------------------------------------------------------------


def body_json(required=True):
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object.")
    return data


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise err_validation(f"Field '{field}' is required and must be a non-empty string.")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err_validation(f"Field '{field}' must be one of {sorted(allowed)}.")
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"Field '{field}' is required and must be an integer.")
    if minimum is not None and v < minimum:
        raise err_validation(f"Field '{field}' must be >= {minimum}.")
    return v


def opt_int(data, field, minimum=None, default=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, minimum=minimum)


def opt_bool(data, field, default=False):
    v = data.get(field, default)
    if not isinstance(v, bool):
        raise err_validation(f"Field '{field}' must be a boolean.")
    return v


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (TypeError, ValueError):
            raise err_validation("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise err_validation("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (TypeError, ValueError):
            raise err_validation("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise err_validation("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def storm_view(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "status": s["status"],
        "watch_started_at": s["watch_started_at"],
        "warning_count": s["warning_count"],
        "activated_at": s["activated_at"],
        "closed_at": s["closed_at"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def refresh_shift_clock(unit):
    if unit["last_shift_change_at"] is None:
        return False
    hrs = hours_between(parse_iso(unit["last_shift_change_at"]), now_dt())
    if hrs != unit["hours_since_shift_change"]:
        unit["hours_since_shift_change"] = hrs
        return True
    return False


def unit_view(u):
    return {
        "id": u["id"],
        "storm_event_id": u["storm_event_id"],
        "unit_code": u["unit_code"],
        "address": u["address"],
        "menu_tier": u["menu_tier"],
        "resource_status": dict(u["resource_status"]),
        "cash_only_flag": u["cash_only_flag"],
        "last_shift_change_at": u["last_shift_change_at"],
        "hours_since_shift_change": u["hours_since_shift_change"],
        "lodging_fund_cents": u["lodging_fund_cents"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def crew_member_view(c):
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "role": c["role"],
        "home_unit_id": c["home_unit_id"],
        "is_jump_team": c["is_jump_team"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def assignment_view(a):
    return {
        "id": a["id"],
        "unit_id": a["unit_id"],
        "crew_member_id": a["crew_member_id"],
        "assigned_from": a["assigned_from"],
        "assigned_until": a["assigned_until"],
        "travel_origin": a["travel_origin"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def asset_view(a):
    return {
        "id": a["id"],
        "kind": a["kind"],
        "home_unit_id": a["home_unit_id"],
        "status": a["status"],
        "retired_at": a["retired_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def allocation_view(a):
    return {
        "id": a["id"],
        "asset_id": a["asset_id"],
        "unit_id": a["unit_id"],
        "status": a["status"],
        "dispatched_at": a["dispatched_at"],
        "returned_at": a["returned_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def booking_view(b):
    return {
        "id": b["id"],
        "unit_id": b["unit_id"],
        "crew_assignment_id": b["crew_assignment_id"],
        "rooms": b["rooms"],
        "nightly_rate_cents": b["nightly_rate_cents"],
        "check_in": b["check_in"],
        "check_out": b["check_out"],
        "cost_cents": b["cost_cents"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def activation_view(a):
    return {
        "id": a["id"],
        "unit_id": a["unit_id"],
        "tier": a["tier"],
        "status": a["status"],
        "activated_at": a["activated_at"],
        "ended_at": a["ended_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def report_view(r):
    return {
        "id": r["id"],
        "unit_id": r["unit_id"],
        "power": r["power"],
        "water": r["water"],
        "gas": r["gas"],
        "payment_network": r["payment_network"],
        "reported_at": r["reported_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def checklist_view(c):
    return {
        "id": c["id"],
        "unit_id": c["unit_id"],
        "status": c["status"],
        "submitted_at": c["submitted_at"],
        "reviewed_at": c["reviewed_at"],
        "reviewed_by_user_id": c["reviewed_by_user_id"],
        "submitted_by_user_id": c["submitted_by_user_id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def item_view(i):
    return {
        "id": i["id"],
        "checklist_run_id": i["checklist_run_id"],
        "key": i["key"],
        "result": i["result"],
        "note": i["note"],
        "created_at": i["created_at"],
    }


def cash_drop_view(d):
    return {
        "id": d["id"],
        "unit_id": d["unit_id"],
        "amount_cents": d["amount_cents"],
        "recorded_at": d["recorded_at"],
        "shift_lead_note": d["shift_lead_note"],
        "created_at": d["created_at"],
    }


def relief_org_view(o):
    return {
        "id": o["id"],
        "name": o["name"],
        "contact_email": o["contact_email"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def pledge_view(p):
    return {
        "id": p["id"],
        "unit_id": p["unit_id"],
        "relief_org_id": p["relief_org_id"],
        "meal_count": p["meal_count"],
        "service_date": p["service_date"],
        "served_count": p["served_count"],
        "shortfall_meals": p["shortfall_meals"],
        "overage_meals": p["overage_meals"],
        "shortfall_penalty_cents": p["shortfall_penalty_cents"],
        "reimbursement_cents": p["reimbursement_cents"],
        "final_reimbursement_cents": p["final_reimbursement_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------


def derive_menu_tier(resource_status):
    if (
        resource_status["power"] == "UP"
        and resource_status["water"] == "UP"
        and resource_status["gas"] == "UP"
    ):
        return "FULL"
    if resource_status["power"] == "DOWN":
        return "TIER1_NO_POWER"
    if resource_status["water"] == "DOWN":
        return "TIER2_NO_WATER"
    return "TIER3_NO_GAS"


def latest_report(unit_id):
    reports = [r for r in db.reports.values() if r["unit_id"] == unit_id]
    if not reports:
        return None
    return max(reports, key=lambda r: (r["reported_at"], r["seq"]))


def unit_reports_sorted(unit_id):
    reports = [r for r in db.reports.values() if r["unit_id"] == unit_id]
    reports.sort(key=lambda r: (r["reported_at"], r["seq"]))
    return reports


def active_activation(unit_id):
    for a in db.activations.values():
        if a["unit_id"] == unit_id and a["status"] == "ACTIVE":
            return a
    return None


def storm_units(storm_id):
    return [u for u in db.units.values() if u["storm_event_id"] == storm_id]


def booking_nights(check_in_iso, check_out_iso):
    """Billable nights (lodging_cost): calendar dates from check_in's date
    through the date of (check_out - 1 day) inclusive.
    PRD §3.7: [2026-09-10T14:00Z, 2026-09-12T09:00Z) spans Sep 10 and 11."""
    ci = parse_iso(check_in_iso)
    co = parse_iso(check_out_iso)
    first_day = ci.date()
    last_day = (co - timedelta(days=1)).date()
    days = set()
    d = first_day
    while d <= last_day:
        days.add(d)
        d += timedelta(days=1)
    return days


def booking_touched_dates(check_in_iso, check_out_iso):
    """Calendar dates touched by the half-open stay at instant level —
    the lodging_night_overlap set. Coarser than the assignment rule: two
    stays adjacent in time that merely share a date conflict (PRD §3.7)."""
    ci = parse_iso(check_in_iso)
    co = parse_iso(check_out_iso)
    last = co - timedelta(microseconds=1)
    days = set()
    d = ci.date()
    while d <= last.date():
        days.add(d)
        d += timedelta(days=1)
    return days


def relief_reimbursement(eligible_meals, shortfall_penalty_cents):
    gross = eligible_meals * MEAL_RATE_CENTS
    if gross < TIER2_MIN_CENTS:
        bonus = TIER1_BONUS_CENTS
    elif gross < TIER3_MIN_CENTS:
        bonus = TIER2_BONUS_CENTS
    else:
        bonus = TIER3_BONUS_CENTS
    liability = gross + bonus - shortfall_penalty_cents
    tax = (liability * TAX_BPS) // (10000 + TAX_BPS)
    return liability - tax


def maybe_stamp_shift_change(unit):
    """Rolling shift-change clock: stamp if never stamped or interval reached."""
    now = now_dt()
    if unit["last_shift_change_at"] is None:
        unit["last_shift_change_at"] = iso(now)
        unit["hours_since_shift_change"] = 0
        touch(unit)
        return
    hrs = hours_between(parse_iso(unit["last_shift_change_at"]), now)
    if hrs >= SHIFT_CHANGE_INTERVAL_HOURS:
        unit["last_shift_change_at"] = iso(now)
        unit["hours_since_shift_change"] = 0
        touch(unit)
    else:
        unit["hours_since_shift_change"] = hrs


def member_non_terminal_assignments(member_id):
    return [
        a
        for a in db.assignments.values()
        if a["crew_member_id"] == member_id and a["status"] in ("SCHEDULED", "ACTIVE")
    ]


def maybe_release_member(member_id):
    member = db.crew_members.get(member_id)
    if member is None:
        return
    if member["status"] != "ASSIGNED":
        return
    if not member_non_terminal_assignments(member_id):
        member["status"] = "AVAILABLE"
        touch(member)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(_err):
    return error_response(err_not_found("Route not found."))


@app.errorhandler(405)
def handle_405(_err):
    return error_response(err_not_found("Route not found."))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@app.route("/ops/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles({"CommandCenterAdmin"})
    data = body_json()
    target = parse_iso(req_str(data, "to_iso8601"), field="to_iso8601")
    with db.lock:
        set_clock(target)
    return success({"current_utc": iso(target)})


# ---------------------------------------------------------------------------
# StormEvent
# ---------------------------------------------------------------------------


@app.route("/ops/storm-events", methods=["POST"])
def create_storm():
    require_roles({"CommandCenterAdmin"})
    data = body_json()
    name = req_str(data, "name")
    with db.lock:
        now = now_dt()
        storm = {
            "name": name,
            "status": "WATCH",
            "watch_started_at": iso(now),
            "warning_count": 0,
            "activated_at": None,
            "closed_at": None,
        }
        stamp_new(storm)
        db.storms[storm["id"]] = storm
        return success(storm_view(storm), status=201)


@app.route("/ops/storm-events", methods=["GET"])
def list_storms():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in STORM_STATUSES:
        raise err_validation("Query parameter 'status' is not a declared storm status.")
    with db.lock:
        items = sorted(db.storms.values(), key=lambda s: s["seq"])
        if status_filter is not None:
            items = [s for s in items if s["status"] == status_filter]
        page, pg = paginate([storm_view(s) for s in items], limit, offset)
        return success(page, pagination=pg)


@app.route("/ops/storm-events/<storm_id>", methods=["GET"])
def get_storm(storm_id):
    require_roles(ALL_ROLES)
    with db.lock:
        storm = get_or_404(db.storms, storm_id, "storm event")
        return success(storm_view(storm))


def _storm_action(storm_id, fn):
    require_roles({"CommandCenterAdmin"})
    with db.lock:
        storm = get_or_404(db.storms, storm_id, "storm event")
        data = body_json()
        fn(storm, data)
        touch(storm)
        return success(storm_view(storm))


def _check_storm_occ(storm, data):
    # The field is required on storm-lifecycle actions (PRD §2.5 "must carry");
    # missing/mistyped is a body-shape failure, mismatch is OCC (checked last).
    if "expected_storm_event_version" not in data or data["expected_storm_event_version"] is None:
        raise err_validation("Field 'expected_storm_event_version' is required.")
    v = data["expected_storm_event_version"]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation("Field 'expected_storm_event_version' must be an integer.")
    if v != storm["version"]:
        raise err_stale_version("expected_storm_event_version does not match current storm version.")


@app.route("/ops/storm-events/<storm_id>/escalate", methods=["POST"])
def escalate_storm(storm_id):
    def fn(storm, data):
        if storm["status"] != "WATCH":
            raise err_invalid_state("Escalation is only permitted from WATCH.")
        _check_storm_occ(storm, data)
        storm["status"] = "WARNING"
        storm["warning_count"] += 1

    return _storm_action(storm_id, fn)


@app.route("/ops/storm-events/<storm_id>/deescalate", methods=["POST"])
def deescalate_storm(storm_id):
    def fn(storm, data):
        if storm["status"] == "WARNING":
            target = "WATCH"
        elif storm["status"] == "ACTIVE":
            # no unit checklist run in IN_PROGRESS (priority 11 fiscal gate,
            # evaluated before the OCC check at priority 12)
            for u in storm_units(storm["id"]):
                for c in db.checklists.values():
                    if c["unit_id"] == u["id"] and c["status"] == "IN_PROGRESS":
                        raise ApiError(
                            "ERR_UNITS_STABILIZING",
                            409,
                            "A unit still has a checklist run IN_PROGRESS.",
                        )
            target = "RECOVERY"
        else:
            raise err_invalid_state("De-escalation is only permitted from WARNING or ACTIVE.")
        _check_storm_occ(storm, data)
        storm["status"] = target

    return _storm_action(storm_id, fn)


@app.route("/ops/storm-events/<storm_id>/activate", methods=["POST"])
def activate_storm(storm_id):
    def fn(storm, data):
        if storm["status"] not in ("WATCH", "WARNING"):
            raise err_invalid_state("Activation is only permitted from WATCH or WARNING.")
        _check_storm_occ(storm, data)
        storm["status"] = "ACTIVE"
        if storm["activated_at"] is None:
            storm["activated_at"] = iso(now_dt())

    return _storm_action(storm_id, fn)


@app.route("/ops/storm-events/<storm_id>/close", methods=["POST"])
def close_storm(storm_id):
    def fn(storm, data):
        if storm["status"] != "RECOVERY":
            raise err_invalid_state("Closure is only permitted from RECOVERY.")
        units = storm_units(storm["id"])
        for u in units:
            if u["menu_tier"] != "FULL":
                raise ApiError(
                    "ERR_UNITS_NOT_RESTORED",
                    409,
                    "Every unit's menu_tier must be FULL before closure.",
                )
        for u in units:
            for c in db.checklists.values():
                if c["unit_id"] == u["id"] and c["status"] in OPEN_CHECKLIST_STATUSES:
                    raise ApiError(
                        "ERR_OPEN_CHECKLISTS",
                        409,
                        "A unit still has an open checklist run.",
                    )
        _check_storm_occ(storm, data)
        storm["status"] = "CLOSED"
        storm["closed_at"] = iso(now_dt())

    return _storm_action(storm_id, fn)


@app.route("/ops/storm-events/<storm_id>/cancel", methods=["POST"])
def cancel_storm(storm_id):
    def fn(storm, data):
        if storm["status"] not in ("WATCH", "WARNING"):
            raise err_invalid_state("Cancellation is only permitted from WATCH or WARNING.")
        _check_storm_occ(storm, data)
        storm["status"] = "CANCELLED"

    return _storm_action(storm_id, fn)


@app.route("/ops/storm-events/<storm_id>/units", methods=["POST"])
def create_unit(storm_id):
    require_roles({"CommandCenterAdmin"})
    data = body_json()
    unit_code = req_str(data, "unit_code")
    address = req_str(data, "address")
    fund = opt_int(data, "lodging_fund_cents", minimum=0, default=0)
    with db.lock:
        storm = get_or_404(db.storms, storm_id, "storm event")
        unit = {
            "storm_event_id": storm["id"],
            "unit_code": unit_code,
            "address": address,
            "menu_tier": "FULL",
            "resource_status": {
                "power": "UP",
                "water": "UP",
                "gas": "UP",
                "payment_network": "UP",
            },
            "cash_only_flag": False,
            "last_shift_change_at": None,
            "hours_since_shift_change": 0,
            "lodging_fund_cents": fund,
        }
        stamp_new(unit)
        db.units[unit["id"]] = unit
        return success(unit_view(unit), status=201)


@app.route("/ops/storm-events/<storm_id>/units", methods=["GET"])
def list_storm_units(storm_id):
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    tier_filter = request.args.get("menu_tier")
    if tier_filter is not None and tier_filter not in UNIT_MENU_TIERS:
        raise err_validation("Query parameter 'menu_tier' is not a declared menu tier.")
    with db.lock:
        get_or_404(db.storms, storm_id, "storm event")
        items = sorted(
            [u for u in db.units.values() if u["storm_event_id"] == storm_id],
            key=lambda u: u["seq"],
        )
        if tier_filter is not None:
            items = [u for u in items if u["menu_tier"] == tier_filter]
        page, pg = paginate([unit_view(u) for u in items], limit, offset)
        return success(page, pagination=pg)


# ---------------------------------------------------------------------------
# Unit
# ---------------------------------------------------------------------------


@app.route("/ops/units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    require_roles(ALL_ROLES)
    with db.lock:
        unit = get_or_404(db.units, unit_id, "unit")
        refresh_shift_clock(unit)
        return success(unit_view(unit))


@app.route("/ops/units/<unit_id>", methods=["PATCH"])
def top_up_unit(unit_id):
    require_roles({"CommandCenterAdmin"})
    with db.lock:
        unit = get_or_404(db.units, unit_id, "unit")
        data = body_json()
        amount = req_int(data, "lodging_fund_top_up_cents")
        unit["lodging_fund_cents"] += amount
        touch(unit)
        return success(unit_view(unit))


# ---------------------------------------------------------------------------
# ConditionReport
# ---------------------------------------------------------------------------


@app.route("/ops/units/<unit_id>/condition-reports", methods=["POST"])
def create_condition_report(unit_id):
    require_roles({"UnitManager"})
    with db.lock:
        unit = get_or_404(db.units, unit_id, "unit")
        data = body_json()
        power = req_enum(data, "power", UP_DOWN)
        water = req_enum(data, "water", UP_DOWN)
        gas = req_enum(data, "gas", UP_DOWN)
        payment = req_enum(data, "payment_network", UP_DOWN)
        now = now_dt()
        report = {
            "unit_id": unit_id,
            "power": power,
            "water": water,
            "gas": gas,
            "payment_network": payment,
            "reported_at": iso(now),
        }
        stamp_new(report)
        db.reports[report["id"]] = report
        # cascade
        unit["resource_status"] = {
            "power": power,
            "water": water,
            "gas": gas,
            "payment_network": payment,
        }
        unit["cash_only_flag"] = payment == "DOWN"
        new_tier = derive_menu_tier(unit["resource_status"])
        unit["menu_tier"] = new_tier
        act = active_activation(unit_id)
        if act is not None and act["tier"] != new_tier:
            act["status"] = "ENDED"
            act["ended_at"] = iso(now)
            touch(act)
        touch(unit)
        return success(report_view(report), status=201)


@app.route("/ops/units/<unit_id>/condition-reports", methods=["GET"])
def list_condition_reports(unit_id):
    require_roles({"CommandCenterAdmin", "UnitManager", "LogisticsPlanner", "FieldCoordinator"})
    limit, offset = parse_pagination()
    with db.lock:
        get_or_404(db.units, unit_id, "unit")
        items = unit_reports_sorted(unit_id)
        page, pg = paginate([report_view(r) for r in items], limit, offset)
        return success(page, pagination=pg)


# ---------------------------------------------------------------------------
# MenuActivation
# ---------------------------------------------------------------------------


@app.route("/ops/units/<unit_id>/menu-activations", methods=["POST"])
def create_menu_activation(unit_id):
    require_roles({"UnitManager"})
    with db.lock:
        unit = get_or_404(db.units, unit_id, "unit")
        data = body_json()
        tier = req_enum(data, "tier", MENU_TIERS)
        if unit["menu_tier"] == "FULL":
            raise ApiError(
                "ERR_UNIT_NOT_STORM_AFFECTED",
                409,
                "Menu activation is only permitted on a storm-affected unit.",
            )
        if tier != unit["menu_tier"]:
            raise err_validation("Requested tier must equal the unit's current menu_tier.")
        now = now_dt()
        existing = active_activation(unit_id)
        if existing is not None:
            existing["status"] = "SUPERSEDED"
            existing["ended_at"] = iso(now)
            touch(existing)
        act = {
            "unit_id": unit_id,
            "tier": tier,
            "status": "ACTIVE",
            "activated_at": iso(now),
            "ended_at": None,
        }
        stamp_new(act)
        db.activations[act["id"]] = act
        return success(activation_view(act), status=201)


@app.route("/ops/units/<unit_id>/menu-activations", methods=["GET"])
def list_menu_activations(unit_id):
    require_roles({"CommandCenterAdmin", "UnitManager"})
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in MENU_ACTIVATION_STATUSES:
        raise err_validation("Query parameter 'status' is not a declared activation status.")
    with db.lock:
        get_or_404(db.units, unit_id, "unit")
        items = sorted(
            [a for a in db.activations.values() if a["unit_id"] == unit_id],
            key=lambda a: a["seq"],
        )
        if status_filter is not None:
            items = [a for a in items if a["status"] == status_filter]
        page, pg = paginate([activation_view(a) for a in items], limit, offset)
        return success(page, pagination=pg)


@app.route("/ops/units/<unit_id>/menu-activations/deactivate", methods=["POST"])
def deactivate_menu_activation(unit_id):
    require_roles({"UnitManager"})
    with db.lock:
        unit = get_or_404(db.units, unit_id, "unit")
        data = body_json()
        act = active_activation(unit_id)
        if act is None:
            raise err_invalid_state("The unit has no ACTIVE menu activation.")
        # OCC last (priority 12); field required by PRD §2.5
        if "expected_unit_version" not in data or data["expected_unit_version"] is None:
            raise err_validation("Field 'expected_unit_version' is required.")
        v = data["expected_unit_version"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err_validation("Field 'expected_unit_version' must be an integer.")
        if v != unit["version"]:
            raise err_stale_version("expected_unit_version does not match current unit version.")
        act["status"] = "ENDED"
        act["ended_at"] = iso(now_dt())
        touch(act)
        touch(unit)
        return success(unit_view(unit))


# ---------------------------------------------------------------------------
# ChecklistRun / ChecklistItem
# ---------------------------------------------------------------------------


@app.route("/ops/units/<unit_id>/checklists", methods=["POST"])
def create_checklist(unit_id):
    require_roles({"UnitManager"})
    with db.lock:
        unit = get_or_404(db.units, unit_id, "unit")
        for c in db.checklists.values():
            if c["unit_id"] == unit_id and c["status"] in ("IN_PROGRESS", "SUBMITTED"):
                raise err_invalid_state(
                    "Another checklist run of this unit is IN_PROGRESS or SUBMITTED."
                )
        run = {
            "unit_id": unit_id,
            "status": "IN_PROGRESS",
            "submitted_at": None,
            "reviewed_at": None,
            "reviewed_by_user_id": None,
            "submitted_by_user_id": None,
        }
        stamp_new(run)
        db.checklists[run["id"]] = run
        db.checklist_items[run["id"]] = {}
        return success(checklist_view(run), status=201)


@app.route("/ops/units/<unit_id>/checklists", methods=["GET"])
def list_checklists(unit_id):
    require_roles({"CommandCenterAdmin", "UnitManager"})
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in CHECKLIST_STATUSES:
        raise err_validation("Query parameter 'status' is not a declared checklist status.")
    with db.lock:
        get_or_404(db.units, unit_id, "unit")
        items = sorted(
            [c for c in db.checklists.values() if c["unit_id"] == unit_id],
            key=lambda c: c["seq"],
        )
        if status_filter is not None:
            items = [c for c in items if c["status"] == status_filter]
        page, pg = paginate([checklist_view(c) for c in items], limit, offset)
        return success(page, pagination=pg)


def _get_nested_run(unit_id, run_id):
    unit = get_or_404(db.units, unit_id, "unit")
    run = db.checklists.get(run_id)
    if run is None or run["unit_id"] != unit["id"]:
        raise err_not_found(f"checklist run '{run_id}' not found under unit '{unit_id}'.")
    return unit, run


@app.route("/ops/units/<unit_id>/checklists/<run_id>", methods=["GET"])
def get_checklist(unit_id, run_id):
    require_roles({"CommandCenterAdmin", "UnitManager"})
    with db.lock:
        _, run = _get_nested_run(unit_id, run_id)
        return success(checklist_view(run))


@app.route("/ops/units/<unit_id>/checklists/<run_id>/items", methods=["POST"])
def record_checklist_item(unit_id, run_id):
    require_roles({"UnitManager"})
    with db.lock:
        _, run = _get_nested_run(unit_id, run_id)
        data = body_json()
        key = req_enum(data, "key", set(CHECKLIST_KEYS))
        result = req_enum(data, "result", ITEM_RESULTS)
        note = data.get("note")
        if note is not None and not isinstance(note, str):
            raise err_validation("Field 'note' must be a string.")
        if result == "FAIL" and (note is None or note == ""):
            raise err_validation("Field 'note' is required when result is FAIL.")
        if run["status"] != "IN_PROGRESS":
            raise err_invalid_state("Items may only be recorded while the run is IN_PROGRESS.")
        items = db.checklist_items.setdefault(run_id, {})
        if key in items:
            item = items[key]
            item["result"] = result
            item["note"] = note
            item["created_at"] = iso(now_dt())
        else:
            item = {
                "checklist_run_id": run_id,
                "key": key,
                "result": result,
                "note": note,
            }
            stamp_new(item, with_version=False)
            items[key] = item
        return success(item_view(item), status=201)


@app.route("/ops/units/<unit_id>/checklists/<run_id>/items", methods=["GET"])
def list_checklist_items(unit_id, run_id):
    require_roles({"CommandCenterAdmin", "UnitManager"})
    with db.lock:
        _, run = _get_nested_run(unit_id, run_id)
        items = db.checklist_items.get(run["id"], {})
        ordered = [items[k] for k in CHECKLIST_KEYS if k in items]
        return success([item_view(i) for i in ordered], pagination={
            "limit": len(ordered) or 10,
            "offset": 0,
            "total_count": len(ordered),
            "has_more": False,
        })


@app.route("/ops/units/<unit_id>/checklists/<run_id>/submit", methods=["POST"])
def submit_checklist(unit_id, run_id):
    uid, _role = require_roles({"UnitManager"})
    with db.lock:
        unit, run = _get_nested_run(unit_id, run_id)
        if run["status"] != "IN_PROGRESS":
            raise err_invalid_state("Only an IN_PROGRESS run may be submitted.")
        # Food-safety gates (priority 6), fixed order
        items = db.checklist_items.get(run_id, {})
        if sorted(items.keys()) != sorted(CHECKLIST_KEYS) or any(
            items[k]["result"] != "PASS" for k in CHECKLIST_KEYS
        ):
            raise ApiError(
                "ERR_CHECKLIST_INCOMPLETE",
                409,
                "All five checklist items must be recorded with result PASS.",
            )
        rs = unit["resource_status"]
        if rs["power"] != "UP" or rs["water"] != "UP" or rs["gas"] != "UP":
            raise ApiError(
                "ERR_RESOURCES_STILL_DOWN",
                409,
                "Power, water and gas axes must all be UP.",
            )
        latest = latest_report(unit_id)
        if latest is None or not (
            latest["power"] == "UP"
            and latest["water"] == "UP"
            and latest["gas"] == "UP"
            and latest["payment_network"] == "UP"
        ):
            raise ApiError(
                "ERR_REPORT_NOT_ALL_CLEAR",
                409,
                "The latest condition report does not show all four axes UP.",
            )
        deadline = parse_iso(latest["reported_at"]) + timedelta(hours=COLD_HOLD_LIMIT_HOURS)
        if now_dt() > deadline:
            raise ApiError(
                "ERR_COLD_HOLD_EXPIRED",
                409,
                "The all-clear report is older than the 4-hour cold-hold limit.",
            )
        run["status"] = "SUBMITTED"
        run["submitted_at"] = iso(now_dt())
        run["submitted_by_user_id"] = uid
        touch(run)
        return success(checklist_view(run))


def _review_checklist(unit_id, run_id, decision):
    uid, _role = require_roles({"CommandCenterAdmin"})
    with db.lock:
        unit, run = _get_nested_run(unit_id, run_id)
        if run["status"] != "SUBMITTED":
            raise err_invalid_state("Only a SUBMITTED run may be reviewed.")
        if uid == run["submitted_by_user_id"]:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                403,
                "The reviewer must differ from the submitter.",
            )
        now = now_dt()
        run["reviewed_at"] = iso(now)
        run["reviewed_by_user_id"] = uid
        if decision == "approve":
            run["status"] = "APPROVED"
            unit["menu_tier"] = "FULL"
            act = active_activation(unit_id)
            if act is not None:
                act["status"] = "ENDED"
                act["ended_at"] = iso(now)
                touch(act)
            touch(run)
            touch(unit)
        else:
            run["status"] = "REJECTED"
            touch(run)
        return success(checklist_view(run))


@app.route("/ops/units/<unit_id>/checklists/<run_id>/approve", methods=["POST"])
def approve_checklist(unit_id, run_id):
    return _review_checklist(unit_id, run_id, "approve")


@app.route("/ops/units/<unit_id>/checklists/<run_id>/reject", methods=["POST"])
def reject_checklist(unit_id, run_id):
    return _review_checklist(unit_id, run_id, "reject")


@app.route("/ops/units/<unit_id>/checklists/<run_id>/rework", methods=["POST"])
def rework_checklist(unit_id, run_id):
    require_roles({"UnitManager"})
    with db.lock:
        _, run = _get_nested_run(unit_id, run_id)
        if run["status"] != "REJECTED":
            raise err_invalid_state("Only a REJECTED run may be reworked.")
        run["status"] = "IN_PROGRESS"
        touch(run)
        return success(checklist_view(run))


# ---------------------------------------------------------------------------
# CashDrop
# ---------------------------------------------------------------------------


@app.route("/ops/units/<unit_id>/cash-drops", methods=["POST"])
def create_cash_drop(unit_id):
    require_roles({"UnitManager"})
    with db.lock:
        unit = get_or_404(db.units, unit_id, "unit")
        data = body_json()
        amount = req_int(data, "amount_cents", minimum=1)
        note = req_str(data, "shift_lead_note")
        if not unit["cash_only_flag"]:
            raise ApiError(
                "ERR_NOT_CASH_ONLY",
                409,
                "Cash drops are only permitted while the unit is cash-only.",
            )
        drop = {
            "unit_id": unit_id,
            "amount_cents": amount,
            "recorded_at": iso(now_dt()),
            "shift_lead_note": note,
        }
        stamp_new(drop, with_version=False)
        db.cash_drops[drop["id"]] = drop
        return success(cash_drop_view(drop), status=201)


@app.route("/ops/units/<unit_id>/cash-drops", methods=["GET"])
def list_cash_drops(unit_id):
    require_roles({"CommandCenterAdmin", "UnitManager"})
    limit, offset = parse_pagination()
    with db.lock:
        get_or_404(db.units, unit_id, "unit")
        items = sorted(
            [d for d in db.cash_drops.values() if d["unit_id"] == unit_id],
            key=lambda d: d["seq"],
        )
        page, pg = paginate([cash_drop_view(d) for d in items], limit, offset)
        return success(page, pagination=pg)


# ---------------------------------------------------------------------------
# ReliefOrg / ReliefPledge
# ---------------------------------------------------------------------------


@app.route("/ops/relief-orgs", methods=["POST"])
def create_relief_org():
    require_roles({"ReliefCoordinator"})
    data = body_json()
    name = req_str(data, "name")
    email = req_str(data, "contact_email")
    with db.lock:
        org = {"name": name, "contact_email": email, "status": "ACTIVE"}
        stamp_new(org)
        db.relief_orgs[org["id"]] = org
        return success(relief_org_view(org), status=201)


@app.route("/ops/relief-orgs", methods=["GET"])
def list_relief_orgs():
    require_roles({"CommandCenterAdmin", "ReliefCoordinator"})
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in RELIEF_ORG_STATUSES:
        raise err_validation("Query parameter 'status' is not a declared relief-org status.")
    with db.lock:
        items = sorted(db.relief_orgs.values(), key=lambda o: o["seq"])
        if status_filter is not None:
            items = [o for o in items if o["status"] == status_filter]
        page, pg = paginate([relief_org_view(o) for o in items], limit, offset)
        return success(page, pagination=pg)


@app.route("/ops/relief-orgs/<org_id>", methods=["GET"])
def get_relief_org(org_id):
    require_roles({"CommandCenterAdmin", "ReliefCoordinator"})
    with db.lock:
        org = get_or_404(db.relief_orgs, org_id, "relief org")
        return success(relief_org_view(org))


@app.route("/ops/relief-orgs/<org_id>", methods=["PATCH"])
def patch_relief_org(org_id):
    require_roles({"ReliefCoordinator"})
    with db.lock:
        org = get_or_404(db.relief_orgs, org_id, "relief org")
        data = body_json()
        status = req_enum(data, "status", RELIEF_ORG_STATUSES)
        org["status"] = status
        touch(org)
        return success(relief_org_view(org))


@app.route("/ops/units/<unit_id>/relief-pledges", methods=["POST"])
def create_pledge(unit_id):
    require_roles({"ReliefCoordinator"})
    with db.lock:
        unit = get_or_404(db.units, unit_id, "unit")
        data = body_json()
        org_id = data.get("relief_org_id")
        if not isinstance(org_id, str) or org_id == "":
            raise err_validation("Field 'relief_org_id' is required.")
        meal_count = req_int(data, "meal_count", minimum=1)
        service_date = req_str(data, "service_date")
        parse_date(service_date, field="service_date")
        org = get_or_404(db.relief_orgs, org_id, "relief org")
        if unit["menu_tier"] == "FULL":
            raise ApiError(
                "ERR_UNIT_NOT_STORM_AFFECTED",
                409,
                "Pledges require a storm-affected unit.",
            )
        if org["status"] != "ACTIVE":
            raise ApiError(
                "ERR_RELIEF_ORG_INACTIVE",
                409,
                "The relief organization is not ACTIVE.",
            )
        pledge = {
            "unit_id": unit_id,
            "relief_org_id": org_id,
            "meal_count": meal_count,
            "service_date": service_date,
            "served_count": None,
            "shortfall_meals": None,
            "overage_meals": None,
            "shortfall_penalty_cents": None,
            "reimbursement_cents": None,
            "final_reimbursement_cents": None,
            "status": "PLEDGED",
        }
        stamp_new(pledge)
        db.pledges[pledge["id"]] = pledge
        return success(pledge_view(pledge), status=201)


@app.route("/ops/units/<unit_id>/relief-pledges", methods=["GET"])
def list_pledges(unit_id):
    require_roles({"CommandCenterAdmin", "UnitManager", "ReliefCoordinator"})
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in PLEDGE_STATUSES:
        raise err_validation("Query parameter 'status' is not a declared pledge status.")
    with db.lock:
        get_or_404(db.units, unit_id, "unit")
        items = sorted(
            [p for p in db.pledges.values() if p["unit_id"] == unit_id],
            key=lambda p: p["seq"],
        )
        if status_filter is not None:
            items = [p for p in items if p["status"] == status_filter]
        page, pg = paginate([pledge_view(p) for p in items], limit, offset)
        return success(page, pagination=pg)


def _get_nested_pledge(unit_id, pledge_id):
    unit = get_or_404(db.units, unit_id, "unit")
    pledge = db.pledges.get(pledge_id)
    if pledge is None or pledge["unit_id"] != unit["id"]:
        raise err_not_found(f"relief pledge '{pledge_id}' not found under unit '{unit_id}'.")
    return unit, pledge


@app.route("/ops/units/<unit_id>/relief-pledges/<pledge_id>/confirm", methods=["POST"])
def confirm_pledge(unit_id, pledge_id):
    require_roles({"ReliefCoordinator"})
    with db.lock:
        _, pledge = _get_nested_pledge(unit_id, pledge_id)
        data = body_json()
        served = req_int(data, "served_count", minimum=0)
        if pledge["status"] != "PLEDGED":
            raise err_invalid_state("Only a PLEDGED pledge may be confirmed.")
        svc = parse_date(pledge["service_date"])
        day_start = datetime(svc.year, svc.month, svc.day, tzinfo=timezone.utc)
        if now_dt() < day_start:
            raise ApiError(
                "ERR_SERVICE_NOT_PAST",
                409,
                "The pledge service day has not begun.",
            )
        shortfall = max(0, pledge["meal_count"] - served)
        overage = max(0, served - pledge["meal_count"])
        penalty = shortfall * SHORTFALL_PENALTY_PER_MEAL_CENTS
        eligible = served - overage  # capped at meal_count
        pledge["served_count"] = served
        pledge["shortfall_meals"] = shortfall
        pledge["overage_meals"] = overage
        pledge["shortfall_penalty_cents"] = penalty
        pledge["reimbursement_cents"] = relief_reimbursement(eligible, penalty)
        pledge["status"] = "CONFIRMED"
        touch(pledge)
        return success(pledge_view(pledge))


@app.route("/ops/units/<unit_id>/relief-pledges/<pledge_id>/cancel", methods=["POST"])
def cancel_pledge(unit_id, pledge_id):
    require_roles({"ReliefCoordinator"})
    with db.lock:
        _, pledge = _get_nested_pledge(unit_id, pledge_id)
        if pledge["status"] != "PLEDGED":
            raise err_invalid_state("Only a PLEDGED pledge may be cancelled.")
        pledge["status"] = "CANCELLED"
        touch(pledge)
        return success(pledge_view(pledge))


@app.route("/ops/relief-orgs/<org_id>/relief-pledges", methods=["GET"])
def list_org_pledges(org_id):
    require_roles({"CommandCenterAdmin", "ReliefCoordinator"})
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in PLEDGE_STATUSES:
        raise err_validation("Query parameter 'status' is not a declared pledge status.")
    with db.lock:
        get_or_404(db.relief_orgs, org_id, "relief org")
        items = sorted(
            [p for p in db.pledges.values() if p["relief_org_id"] == org_id],
            key=lambda p: p["seq"],
        )
        if status_filter is not None:
            items = [p for p in items if p["status"] == status_filter]
        page, pg = paginate([pledge_view(p) for p in items], limit, offset)
        return success(page, pagination=pg)


# ---------------------------------------------------------------------------
# CrewMember / CrewAssignment
# ---------------------------------------------------------------------------


@app.route("/ops/crew-members", methods=["POST"])
def create_crew_member():
    require_roles({"FieldCoordinator"})
    data = body_json()
    full_name = req_str(data, "full_name")
    role = req_enum(data, "role", CREW_ROLES)
    home_unit_id = data.get("home_unit_id")
    if not isinstance(home_unit_id, str) or home_unit_id == "":
        raise err_validation("Field 'home_unit_id' is required.")
    is_jump = opt_bool(data, "is_jump_team", default=False)
    with db.lock:
        get_or_404(db.units, home_unit_id, "unit")
        member = {
            "full_name": full_name,
            "role": role,
            "home_unit_id": home_unit_id,
            "is_jump_team": is_jump,
            "status": "AVAILABLE",
        }
        stamp_new(member)
        db.crew_members[member["id"]] = member
        return success(crew_member_view(member), status=201)


@app.route("/ops/crew-members", methods=["GET"])
def list_crew_members():
    require_roles({"CommandCenterAdmin", "FieldCoordinator"})
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in CREW_MEMBER_STATUSES:
        raise err_validation("Query parameter 'status' is not a declared crew-member status.")
    jump_filter = request.args.get("is_jump_team")
    jump_val = None
    if jump_filter is not None:
        if jump_filter not in ("true", "false"):
            raise err_validation("Query parameter 'is_jump_team' must be 'true' or 'false'.")
        jump_val = jump_filter == "true"
    with db.lock:
        items = sorted(db.crew_members.values(), key=lambda c: c["seq"])
        if status_filter is not None:
            items = [c for c in items if c["status"] == status_filter]
        if jump_val is not None:
            items = [c for c in items if c["is_jump_team"] == jump_val]
        page, pg = paginate([crew_member_view(c) for c in items], limit, offset)
        return success(page, pagination=pg)


@app.route("/ops/crew-members/<member_id>", methods=["GET"])
def get_crew_member(member_id):
    require_roles({"CommandCenterAdmin", "FieldCoordinator"})
    with db.lock:
        member = get_or_404(db.crew_members, member_id, "crew member")
        return success(crew_member_view(member))


@app.route("/ops/crew-members/<member_id>", methods=["PATCH"])
def patch_crew_member(member_id):
    require_roles({"FieldCoordinator"})
    with db.lock:
        member = get_or_404(db.crew_members, member_id, "crew member")
        data = body_json()
        status = req_enum(data, "status", {"AVAILABLE", "INACTIVE"})
        if status == "INACTIVE" and member["status"] == "ASSIGNED":
            raise err_invalid_state("An ASSIGNED crew member cannot be set INACTIVE.")
        member["status"] = status
        touch(member)
        return success(crew_member_view(member))


@app.route("/ops/assignments", methods=["POST"])
def create_assignment():
    require_roles({"FieldCoordinator"})
    data = body_json()
    member_id = data.get("crew_member_id")
    if not isinstance(member_id, str) or member_id == "":
        raise err_validation("Field 'crew_member_id' is required.")
    unit_id = data.get("unit_id")
    if not isinstance(unit_id, str) or unit_id == "":
        raise err_validation("Field 'unit_id' is required.")
    assigned_from = req_str(data, "assigned_from")
    assigned_until = req_str(data, "assigned_until")
    travel_origin = req_str(data, "travel_origin")
    with db.lock:
        member = get_or_404(db.crew_members, member_id, "crew member")
        get_or_404(db.units, unit_id, "unit")
        from_dt = parse_iso(assigned_from, field="assigned_from")
        until_dt = parse_iso(assigned_until, field="assigned_until")
        if until_dt <= from_dt:
            raise err_validation("assigned_until must be strictly after assigned_from.")
        if member["status"] == "INACTIVE":
            raise ApiError(
                "ERR_CREW_MEMBER_INACTIVE",
                409,
                "The crew member is INACTIVE.",
            )
        for existing in member_non_terminal_assignments(member_id):
            ex_unit = db.units.get(existing["unit_id"])
            if ex_unit is not None:
                ex_storm = db.storms.get(ex_unit["storm_event_id"])
                if ex_storm is not None and ex_storm["status"] in ("CANCELLED", "CLOSED"):
                    continue
            ex_from = parse_iso(existing["assigned_from"])
            ex_until = parse_iso(existing["assigned_until"])
            if from_dt < ex_until and ex_from < until_dt:
                raise ApiError(
                    "ERR_ASSIGNMENT_OVERLAP",
                    409,
                    "The crew member already has an overlapping SCHEDULED/ACTIVE assignment.",
                )
        asg = {
            "unit_id": unit_id,
            "crew_member_id": member_id,
            "assigned_from": iso(from_dt),
            "assigned_until": iso(until_dt),
            "travel_origin": travel_origin,
            "status": "SCHEDULED",
        }
        stamp_new(asg)
        db.assignments[asg["id"]] = asg
        if member["status"] == "AVAILABLE":
            member["status"] = "ASSIGNED"
            touch(member)
        return success(assignment_view(asg), status=201)


@app.route("/ops/assignments", methods=["GET"])
def list_assignments():
    require_roles({"CommandCenterAdmin", "FieldCoordinator"})
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ASSIGNMENT_STATUSES:
        raise err_validation("Query parameter 'status' is not a declared assignment status.")
    with db.lock:
        items = sorted(db.assignments.values(), key=lambda a: a["seq"])
        if status_filter is not None:
            items = [a for a in items if a["status"] == status_filter]
        page, pg = paginate([assignment_view(a) for a in items], limit, offset)
        return success(page, pagination=pg)


@app.route("/ops/assignments/<asg_id>", methods=["GET"])
def get_assignment(asg_id):
    require_roles({"CommandCenterAdmin", "FieldCoordinator"})
    with db.lock:
        asg = get_or_404(db.assignments, asg_id, "assignment")
        return success(assignment_view(asg))


@app.route("/ops/assignments/<asg_id>/start", methods=["POST"])
def start_assignment(asg_id):
    require_roles({"FieldCoordinator"})
    with db.lock:
        asg = get_or_404(db.assignments, asg_id, "assignment")
        if asg["status"] != "SCHEDULED":
            raise err_invalid_state("Only a SCHEDULED assignment may be started.")
        unit = db.units[asg["unit_id"]]
        member = db.crew_members[asg["crew_member_id"]]
        storm = db.storms[unit["storm_event_id"]]
        if storm["status"] not in ("ACTIVE", "RECOVERY"):
            raise ApiError(
                "ERR_STORM_NOT_ACTIVE",
                409,
                "The target unit's storm is not ACTIVE or RECOVERY.",
            )
        if not member["is_jump_team"]:
            raise ApiError(
                "ERR_NOT_JUMP_TEAM",
                409,
                "The crew member is not jump-team certified.",
            )
        if now_dt() < parse_iso(asg["assigned_from"]):
            raise ApiError(
                "ERR_ASSIGNMENT_WINDOW",
                409,
                "The assignment window has not begun.",
            )
        if unit["menu_tier"] == "FULL":
            raise ApiError(
                "ERR_UNIT_NOT_IN_STORM_TIER",
                409,
                "The target unit is not on a storm-tier menu.",
            )
        asg["status"] = "ACTIVE"
        touch(asg)
        maybe_stamp_shift_change(unit)
        return success(assignment_view(asg))


@app.route("/ops/assignments/<asg_id>/complete", methods=["POST"])
def complete_assignment(asg_id):
    require_roles({"FieldCoordinator"})
    with db.lock:
        asg = get_or_404(db.assignments, asg_id, "assignment")
        if asg["status"] != "ACTIVE":
            raise err_invalid_state("Only an ACTIVE assignment may be completed.")
        unit = db.units[asg["unit_id"]]
        asg["status"] = "COMPLETED"
        touch(asg)
        maybe_stamp_shift_change(unit)
        maybe_release_member(asg["crew_member_id"])
        return success(assignment_view(asg))


@app.route("/ops/assignments/<asg_id>/cancel", methods=["POST"])
def cancel_assignment(asg_id):
    require_roles({"FieldCoordinator"})
    with db.lock:
        asg = get_or_404(db.assignments, asg_id, "assignment")
        if asg["status"] != "SCHEDULED":
            raise err_invalid_state("Only a SCHEDULED assignment may be cancelled.")
        asg["status"] = "CANCELLED"
        touch(asg)
        maybe_release_member(asg["crew_member_id"])
        return success(assignment_view(asg))


# ---------------------------------------------------------------------------
# Asset / AssetAllocation
# ---------------------------------------------------------------------------


@app.route("/ops/assets", methods=["POST"])
def create_asset():
    require_roles({"LogisticsPlanner"})
    data = body_json()
    kind = req_enum(data, "kind", ASSET_KINDS)
    home_unit_id = data.get("home_unit_id")
    if not isinstance(home_unit_id, str) or home_unit_id == "":
        raise err_validation("Field 'home_unit_id' is required.")
    with db.lock:
        get_or_404(db.units, home_unit_id, "unit")
        asset = {"kind": kind, "home_unit_id": home_unit_id, "status": "IDLE", "retired_at": None}
        stamp_new(asset)
        db.assets[asset["id"]] = asset
        return success(asset_view(asset), status=201)


@app.route("/ops/assets", methods=["GET"])
def list_assets():
    require_roles({"CommandCenterAdmin", "LogisticsPlanner"})
    limit, offset = parse_pagination()
    kind_filter = request.args.get("kind")
    if kind_filter is not None and kind_filter not in ASSET_KINDS:
        raise err_validation("Query parameter 'kind' is not a declared asset kind.")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ASSET_STATUSES:
        raise err_validation("Query parameter 'status' is not a declared asset status.")
    with db.lock:
        items = sorted(db.assets.values(), key=lambda a: a["seq"])
        if kind_filter is not None:
            items = [a for a in items if a["kind"] == kind_filter]
        if status_filter is not None:
            items = [a for a in items if a["status"] == status_filter]
        page, pg = paginate([asset_view(a) for a in items], limit, offset)
        return success(page, pagination=pg)


@app.route("/ops/assets/<asset_id>", methods=["GET"])
def get_asset(asset_id):
    require_roles({"CommandCenterAdmin", "LogisticsPlanner"})
    with db.lock:
        asset = get_or_404(db.assets, asset_id, "asset")
        return success(asset_view(asset))


@app.route("/ops/assets/<asset_id>/retire", methods=["POST"])
def retire_asset(asset_id):
    require_roles({"LogisticsPlanner"})
    with db.lock:
        asset = get_or_404(db.assets, asset_id, "asset")
        if asset["status"] not in ("IDLE", "RETURNED"):
            raise err_invalid_state("Only an IDLE or RETURNED asset may be retired.")
        asset["status"] = "RETIRED"
        asset["retired_at"] = iso(now_dt())
        touch(asset)
        return success(asset_view(asset))


@app.route("/ops/allocations", methods=["POST"])
def create_allocation():
    require_roles({"LogisticsPlanner"})
    data = body_json()
    asset_id = data.get("asset_id")
    if not isinstance(asset_id, str) or asset_id == "":
        raise err_validation("Field 'asset_id' is required.")
    unit_id = data.get("unit_id")
    if not isinstance(unit_id, str) or unit_id == "":
        raise err_validation("Field 'unit_id' is required.")
    with db.lock:
        asset = get_or_404(db.assets, asset_id, "asset")
        unit = get_or_404(db.units, unit_id, "unit")
        storm = db.storms[unit["storm_event_id"]]
        if asset["status"] != "IDLE":
            raise ApiError("ERR_ASSET_NOT_IDLE", 409, "The asset is not IDLE.")
        window_end = parse_iso(storm["watch_started_at"]) + timedelta(
            hours=PREPOSITION_WINDOW_HOURS
        )
        if storm["status"] not in ("WATCH", "WARNING") or now_dt() > window_end:
            raise ApiError(
                "ERR_PREPOSITION_WINDOW_EXPIRED",
                409,
                "The pre-positioning window has expired.",
            )
        rs = unit["resource_status"]
        if asset["kind"] == "GENERATOR":
            if rs["power"] != "DOWN":
                raise ApiError(
                    "ERR_ASSET_KIND_MISMATCH",
                    409,
                    "A GENERATOR requires the unit's power axis DOWN.",
                )
        else:  # MOBILE_KITCHEN
            if rs["water"] != "DOWN" and rs["gas"] != "DOWN":
                raise ApiError(
                    "ERR_ASSET_KIND_MISMATCH",
                    409,
                    "A MOBILE_KITCHEN requires water or gas DOWN.",
                )
        alloc = {
            "asset_id": asset_id,
            "unit_id": unit_id,
            "status": "RESERVED",
            "dispatched_at": None,
            "returned_at": None,
        }
        stamp_new(alloc)
        db.allocations[alloc["id"]] = alloc
        asset["status"] = "ALLOCATED"
        touch(asset)
        return success(allocation_view(alloc), status=201)


@app.route("/ops/allocations", methods=["GET"])
def list_allocations():
    require_roles({"CommandCenterAdmin", "LogisticsPlanner"})
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ALLOCATION_STATUSES:
        raise err_validation("Query parameter 'status' is not a declared allocation status.")
    with db.lock:
        items = sorted(db.allocations.values(), key=lambda a: a["seq"])
        if status_filter is not None:
            items = [a for a in items if a["status"] == status_filter]
        page, pg = paginate([allocation_view(a) for a in items], limit, offset)
        return success(page, pagination=pg)


@app.route("/ops/allocations/<alloc_id>", methods=["GET"])
def get_allocation(alloc_id):
    require_roles({"CommandCenterAdmin", "LogisticsPlanner"})
    with db.lock:
        alloc = get_or_404(db.allocations, alloc_id, "allocation")
        return success(allocation_view(alloc))


@app.route("/ops/allocations/<alloc_id>/dispatch", methods=["POST"])
def dispatch_allocation(alloc_id):
    require_roles({"LogisticsPlanner"})
    with db.lock:
        alloc = get_or_404(db.allocations, alloc_id, "allocation")
        if alloc["status"] not in ("RESERVED", "RETURNED"):
            raise err_invalid_state("Only a RESERVED or RETURNED allocation may be dispatched.")
        redeploy = alloc["status"] == "RETURNED"
        alloc["status"] = "DEPLOYED"
        alloc["dispatched_at"] = iso(now_dt())
        touch(alloc)
        if redeploy:
            asset = db.assets[alloc["asset_id"]]
            asset["status"] = "ALLOCATED"
            touch(asset)
        return success(allocation_view(alloc))


@app.route("/ops/allocations/<alloc_id>/return", methods=["POST"])
def return_allocation(alloc_id):
    require_roles({"LogisticsPlanner"})
    with db.lock:
        alloc = get_or_404(db.allocations, alloc_id, "allocation")
        if alloc["status"] != "DEPLOYED":
            raise err_invalid_state("Only a DEPLOYED allocation may be returned.")
        unit = db.units[alloc["unit_id"]]
        if unit["menu_tier"] != "FULL":
            raise ApiError(
                "ERR_UNIT_STILL_LIMITED",
                409,
                "The unit is not back on its FULL menu.",
            )
        alloc["status"] = "RETURNED"
        alloc["returned_at"] = iso(now_dt())
        touch(alloc)
        asset = db.assets[alloc["asset_id"]]
        asset["status"] = "RETURNED"
        touch(asset)
        return success(allocation_view(alloc))


@app.route("/ops/allocations/<alloc_id>/cancel", methods=["POST"])
def cancel_allocation(alloc_id):
    require_roles({"LogisticsPlanner"})
    with db.lock:
        alloc = get_or_404(db.allocations, alloc_id, "allocation")
        if alloc["status"] != "RESERVED":
            raise err_invalid_state("Only a RESERVED allocation may be cancelled.")
        alloc["status"] = "CANCELLED"
        touch(alloc)
        asset = db.assets[alloc["asset_id"]]
        asset["status"] = "IDLE"
        touch(asset)
        return success(allocation_view(alloc))


# ---------------------------------------------------------------------------
# LodgingBooking
# ---------------------------------------------------------------------------


@app.route("/ops/lodging-bookings", methods=["POST"])
def create_booking():
    require_roles({"FieldCoordinator"})
    data = body_json()
    asg_id = data.get("crew_assignment_id")
    if not isinstance(asg_id, str) or asg_id == "":
        raise err_validation("Field 'crew_assignment_id' is required.")
    unit_id = data.get("unit_id")
    if not isinstance(unit_id, str) or unit_id == "":
        raise err_validation("Field 'unit_id' is required.")
    with db.lock:
        get_or_404(db.assignments, asg_id, "assignment")
        unit = get_or_404(db.units, unit_id, "unit")
        rooms = req_int(data, "rooms", minimum=1)
        rate = req_int(data, "nightly_rate_cents", minimum=1)
        check_in = req_str(data, "check_in")
        check_out = req_str(data, "check_out")
        ci = parse_iso(check_in, field="check_in")
        co = parse_iso(check_out, field="check_out")
        if co <= ci:
            raise err_validation("check_out must be strictly after check_in.")
        new_dates = booking_touched_dates(check_in, check_out)
        for b in db.bookings.values():
            if b["crew_assignment_id"] == asg_id and b["status"] == "CONFIRMED":
                if booking_touched_dates(b["check_in"], b["check_out"]) & new_dates:
                    raise ApiError(
                        "ERR_LODGING_OVERLAP",
                        409,
                        "The new booking shares a calendar night with a CONFIRMED booking.",
                    )
        cost = rooms * rate * len(booking_nights(check_in, check_out))
        if unit["lodging_fund_cents"] < cost:
            raise ApiError(
                "ERR_LODGING_FUND_EXCEEDED",
                409,
                "The booking cost exceeds the unit's lodging fund.",
            )
        booking = {
            "unit_id": unit_id,
            "crew_assignment_id": asg_id,
            "rooms": rooms,
            "nightly_rate_cents": rate,
            "check_in": iso(ci),
            "check_out": iso(co),
            "cost_cents": cost,
            "status": "CONFIRMED",
        }
        stamp_new(booking)
        db.bookings[booking["id"]] = booking
        unit["lodging_fund_cents"] -= cost
        touch(unit)
        return success(booking_view(booking), status=201)


@app.route("/ops/lodging-bookings", methods=["GET"])
def list_bookings():
    require_roles({"CommandCenterAdmin", "FieldCoordinator"})
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in BOOKING_STATUSES:
        raise err_validation("Query parameter 'status' is not a declared booking status.")
    with db.lock:
        items = sorted(db.bookings.values(), key=lambda b: b["seq"])
        if status_filter is not None:
            items = [b for b in items if b["status"] == status_filter]
        page, pg = paginate([booking_view(b) for b in items], limit, offset)
        return success(page, pagination=pg)


@app.route("/ops/lodging-bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    require_roles({"CommandCenterAdmin", "FieldCoordinator"})
    with db.lock:
        booking = get_or_404(db.bookings, booking_id, "lodging booking")
        return success(booking_view(booking))


@app.route("/ops/lodging-bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    require_roles({"FieldCoordinator"})
    with db.lock:
        booking = get_or_404(db.bookings, booking_id, "lodging booking")
        if booking["status"] != "CONFIRMED":
            raise err_invalid_state("Only a CONFIRMED booking may be cancelled.")
        booking["status"] = "CANCELLED"
        touch(booking)
        unit = db.units[booking["unit_id"]]
        unit["lodging_fund_cents"] += booking["cost_cents"]
        touch(unit)
        return success(booking_view(booking))


# ---------------------------------------------------------------------------
# Reverse-reachability reads
# ---------------------------------------------------------------------------


def _list_simple(items, view):
    ordered = sorted(items, key=lambda x: x["seq"])
    return success(
        [view(i) for i in ordered],
        pagination={
            "limit": len(ordered) if ordered else 10,
            "offset": 0,
            "total_count": len(ordered),
            "has_more": False,
        },
    )


@app.route("/ops/units/<unit_id>/crew-members", methods=["GET"])
def list_unit_crew_members(unit_id):
    require_roles({"CommandCenterAdmin", "FieldCoordinator"})
    with db.lock:
        get_or_404(db.units, unit_id, "unit")
        return _list_simple(
            [c for c in db.crew_members.values() if c["home_unit_id"] == unit_id],
            crew_member_view,
        )


@app.route("/ops/units/<unit_id>/assets", methods=["GET"])
def list_unit_assets(unit_id):
    require_roles({"CommandCenterAdmin", "LogisticsPlanner"})
    with db.lock:
        get_or_404(db.units, unit_id, "unit")
        return _list_simple(
            [a for a in db.assets.values() if a["home_unit_id"] == unit_id], asset_view
        )


@app.route("/ops/units/<unit_id>/assignments", methods=["GET"])
def list_unit_assignments(unit_id):
    require_roles({"CommandCenterAdmin", "FieldCoordinator"})
    with db.lock:
        get_or_404(db.units, unit_id, "unit")
        return _list_simple(
            [a for a in db.assignments.values() if a["unit_id"] == unit_id], assignment_view
        )


@app.route("/ops/crew-members/<member_id>/assignments", methods=["GET"])
def list_member_assignments(member_id):
    require_roles({"CommandCenterAdmin", "FieldCoordinator"})
    with db.lock:
        get_or_404(db.crew_members, member_id, "crew member")
        return _list_simple(
            [a for a in db.assignments.values() if a["crew_member_id"] == member_id],
            assignment_view,
        )


@app.route("/ops/assignments/<asg_id>/lodging-bookings", methods=["GET"])
def list_assignment_bookings(asg_id):
    require_roles({"CommandCenterAdmin", "FieldCoordinator"})
    with db.lock:
        get_or_404(db.assignments, asg_id, "assignment")
        return _list_simple(
            [b for b in db.bookings.values() if b["crew_assignment_id"] == asg_id],
            booking_view,
        )


@app.route("/ops/assets/<asset_id>/allocations", methods=["GET"])
def list_asset_allocations(asset_id):
    require_roles({"CommandCenterAdmin", "LogisticsPlanner"})
    with db.lock:
        get_or_404(db.assets, asset_id, "asset")
        return _list_simple(
            [a for a in db.allocations.values() if a["asset_id"] == asset_id],
            allocation_view,
        )


@app.route("/ops/units/<unit_id>/allocations", methods=["GET"])
def list_unit_allocations(unit_id):
    require_roles({"CommandCenterAdmin", "LogisticsPlanner"})
    with db.lock:
        get_or_404(db.units, unit_id, "unit")
        return _list_simple(
            [a for a in db.allocations.values() if a["unit_id"] == unit_id],
            allocation_view,
        )


@app.route("/ops/units/<unit_id>/lodging-bookings", methods=["GET"])
def list_unit_bookings(unit_id):
    require_roles({"CommandCenterAdmin", "FieldCoordinator"})
    with db.lock:
        get_or_404(db.units, unit_id, "unit")
        return _list_simple(
            [b for b in db.bookings.values() if b["unit_id"] == unit_id], booking_view
        )


@app.route("/ops/checklists/<run_id>", methods=["GET"])
def get_checklist_flat(run_id):
    require_roles({"CommandCenterAdmin", "UnitManager"})
    with db.lock:
        run = get_or_404(db.checklists, run_id, "checklist run")
        return success(checklist_view(run))


@app.route("/ops/checklists/<run_id>/items", methods=["GET"])
def get_checklist_items_flat(run_id):
    require_roles({"CommandCenterAdmin", "UnitManager"})
    with db.lock:
        run = get_or_404(db.checklists, run_id, "checklist run")
        items = db.checklist_items.get(run["id"], {})
        ordered = [items[k] for k in CHECKLIST_KEYS if k in items]
        return success(
            [item_view(i) for i in ordered],
            pagination={
                "limit": len(ordered) or 10,
                "offset": 0,
                "total_count": len(ordered),
                "has_more": False,
            },
        )


# ---------------------------------------------------------------------------
# Reporting cadence
# ---------------------------------------------------------------------------


@app.route("/ops/run-report", methods=["POST"])
def run_report():
    require_roles({"CommandCenterAdmin"})
    with db.lock:
        now = now_dt()
        per_unit = []
        for storm in db.storms.values():
            if storm["status"] not in NON_TERMINAL_STORMS:
                continue
            for unit in sorted(storm_units(storm["id"]), key=lambda u: u["seq"]):
                changed = refresh_shift_clock(unit)
                if changed:
                    touch(unit)
                per_unit.append(
                    {
                        "unit_id": unit["id"],
                        "menu_tier": unit["menu_tier"],
                        "cash_only_flag": unit["cash_only_flag"],
                        "hours_since_shift_change": unit["hours_since_shift_change"],
                    }
                )
        pending = [
            p
            for p in db.pledges.values()
            if p["status"] == "CONFIRMED" and p["final_reimbursement_cents"] is None
        ]
        pending.sort(key=lambda p: (p["service_date"], p["seq"]))
        for p in pending:
            eligible = p["served_count"]
            penalty = 0 if p["served_count"] >= p["meal_count"] else p["shortfall_penalty_cents"]
            p["final_reimbursement_cents"] = relief_reimbursement(eligible, penalty)
            touch(p)
        return success(
            {
                "generated_at": iso(now),
                "units_reported": len(per_unit),
                "pledges_finalized": len(pending),
                "per_unit": per_unit,
            }
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
