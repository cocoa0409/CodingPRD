#!/usr/bin/env python3
"""Senior Primary Care Panel Growth API - Flask implementation."""
import os
import uuid
import calendar
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK = {"current": "2026-09-01T00:00:00Z"}


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = f"{dt.microsecond // 1000:03d}"
    return f"{base}.{ms}Z"


def now_dt():
    return parse_dt(CLOCK["current"])


def now_str():
    return fmt_dt(now_dt())


def current_month():
    dt = now_dt()
    return f"{dt.year:04d}-{dt.month:02d}"


def days_in_month(month_str):
    y, m = int(month_str[:4]), int(month_str[5:7])
    return calendar.monthrange(y, m)[1]


def month_start(month_str):
    y, m = int(month_str[:4]), int(month_str[5:7])
    return datetime(y, m, 1, tzinfo=timezone.utc)


def month_end_exclusive(month_str):
    y, m = int(month_str[:4]), int(month_str[5:7])
    if m == 12:
        return datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(y, m + 1, 1, tzinfo=timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def months_elapsed(opened_on_str, clock_dt):
    opened = parse_date(opened_on_str)
    return (clock_dt.year - opened.year) * 12 + (clock_dt.month - opened.month)


# ---------------------------------------------------------------------------
# Data store (in-memory)
# ---------------------------------------------------------------------------
DB = {
    "centers": {},
    "care_teams": {},
    "patients": {},
    "health_plans": {},
    "attributions": {},
    "appointments": {},
    "rooms": {},
    "vehicles": {},
    "rides": {},
    "triage_cases": {},
    "claims": {},
    "settlements": {},
    "events": {},
}


def new_id():
    return str(uuid.uuid4())


def touch(entity):
    entity["updated_at"] = now_str()
    entity["version"] = entity.get("version", 1) + 1


def register(coll, entity):
    entity["id"] = new_id()
    ts = now_str()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    DB[coll][entity["id"]] = entity
    return entity


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------
def dec(x):
    return Decimal(str(x))


def round_cents(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_dec(d, places):
    return d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Errors / envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def req_meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": now_str(),
    }


def success(data, status=200, pagination=None):
    body = {"meta": req_meta(), "response_type": "array" if isinstance(data, list) else "object", "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def error_resp(err):
    body = {
        "meta": req_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_resp(e)


@app.errorhandler(404)
def handle_404(e):
    return error_resp(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_resp(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(500)
def handle_500(e):
    return error_resp(ApiError("ERR_INVALID_REQUEST", 400, str(getattr(e, "original_exception", e))))


# ---------------------------------------------------------------------------
# Auth & RBAC
# ---------------------------------------------------------------------------
ROLES = {
    "NetworkOperator", "EnrollmentCoordinator", "CareTeamLead", "FrontDesk",
    "TransportDispatcher", "TriageNurse", "ClaimsAdjudicator", "FinanceAnalyst",
    "FinanceController",
}

ROUTE_ROLES = {}


def roles(*allowed):
    def deco(fn):
        ROUTE_ROLES[fn.__name__] = set(allowed)
        return fn
    return deco


@app.before_request
def auth_middleware():
    if request.endpoint in ("static",):
        return None
    uid = request.headers.get("X-User-ID")
    urole = request.headers.get("X-User-Role")
    if not uid or not urole or urole not in ROLES:
        return error_resp(ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                                   "X-User-ID or X-User-Role header missing or role undeclared"))
    allowed = ROUTE_ROLES.get(request.endpoint)
    if allowed is not None and urole not in allowed:
        return error_resp(ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation"))
    return None


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def get_or_404(coll, rid):
    ent = DB[coll].get(rid)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Resource {rid} not found")
    return ent


def body():
    if not request.data:
        return {}
    try:
        b = request.get_json(force=True, silent=True)
    except Exception:
        b = None
    if b is None or not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Malformed JSON body")
    return b


def require_fields(b, fields):
    for f in fields:
        if f not in b or b[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {f}")


def check_enum(b, field, allowed):
    v = b.get(field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Illegal value for {field}")
    return v


def check_int(b, field, min_v=None):
    v = b.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be an integer")
    if min_v is not None and v < min_v:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} below minimum {min_v}")
    return v


def check_number(b, field):
    v = b.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be a number")
    return v


def parse_limit_offset():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit/offset out of range")
    return limit, offset


def list_response(items):
    items = sorted(items, key=lambda e: e["created_at"])
    limit, offset = parse_limit_offset()
    total = len(items)
    page = items[offset:offset + limit]
    return success(page, 200, {
        "limit": limit, "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    })


# ---------------------------------------------------------------------------
# Center computed helpers
# ---------------------------------------------------------------------------
def compute_panel_fill_ratio(center_id):
    teams = [t for t in DB["care_teams"].values() if t["center_id"] == center_id]
    cap = sum(t["panel_cap"] for t in teams)
    active = sum(t["active_panel_count"] for t in teams)
    if cap <= 0:
        return 0.0
    return float(round_dec(dec(active) / dec(cap), 4))


def center_of_team(team):
    return DB["centers"].get(team["center_id"])


def center_of_patient(patient_id):
    """Find the center this patient is currently attributed to (ACTIVE), else None."""
    for a in DB["attributions"].values():
        if a["patient_id"] == patient_id and a["status"] == "ACTIVE":
            team = DB["care_teams"].get(a["care_team_id"])
            if team:
                return DB["centers"].get(team["center_id"])
    return None


def apply_saturation(center):
    """Check panel_fill_ratio and transition OPEN<->SATURATED with cascades."""
    if center["status"] not in ("OPEN", "SATURATED"):
        return
    ratio = compute_panel_fill_ratio(center["id"])
    center["panel_fill_ratio"] = ratio
    if center["status"] == "OPEN" and ratio >= 1.0:
        center["status"] = "SATURATED"
        touch(center)
        for t in DB["care_teams"].values():
            if t["center_id"] == center["id"] and t["active_panel_count"] >= t["panel_cap"]:
                if t["accepting"]:
                    t["accepting"] = False
                    touch(t)
        # PENDING attributions targeting full teams -> WAITLISTED
        for t in DB["care_teams"].values():
            if t["center_id"] != center["id"]:
                continue
            if t["active_panel_count"] >= t["panel_cap"]:
                for a in DB["attributions"].values():
                    if a["care_team_id"] == t["id"] and a["status"] == "PENDING":
                        a["status"] = "WAITLISTED"
                        t["waitlist_depth"] += 1
                        touch(a)
                touch(t)
    elif center["status"] == "SATURATED" and ratio < 0.9:
        center["status"] = "OPEN"
        touch(center)
        for t in DB["care_teams"].values():
            if t["center_id"] == center["id"] and t["active_panel_count"] < t["panel_cap"]:
                if not t["accepting"]:
                    t["accepting"] = True
                # waitlist promotion: earliest created_at first, while headroom exists;
                # each promotion consumes one unit of headroom
                waiting = sorted(
                    [a for a in DB["attributions"].values()
                     if a["care_team_id"] == t["id"] and a["status"] == "WAITLISTED"],
                    key=lambda a: a["created_at"])
                headroom = t["panel_cap"] - t["active_panel_count"]
                for a in waiting:
                    if headroom > 0:
                        a["status"] = "PENDING"
                        t["waitlist_depth"] -= 1
                        headroom -= 1
                        touch(a)
                    else:
                        break
                touch(t)


# ---------------------------------------------------------------------------
# Sweeps (nightly + monthly close run) triggered by clock set
# ---------------------------------------------------------------------------
def run_sweeps():
    now = now_dt()
    cur_month = current_month()
    # No-show marking
    for appt in DB["appointments"].values():
        if appt["status"] == "SCHEDULED":
            end = parse_dt(appt["start_utc"]) + timedelta(minutes=appt["duration_minutes"])
            if now > end:
                appt["status"] = "COMPLETED_NO_SHOW"
                appt["cost_cents"] = appointment_cost(appt, no_show=True)
                touch(appt)
    # Patient strikes recompute (trailing 90 days)
    cutoff = now - timedelta(days=90)
    for p in DB["patients"].values():
        count = 0
        for appt in DB["appointments"].values():
            if appt["patient_id"] == p["id"] and appt["status"] == "COMPLETED_NO_SHOW":
                end = parse_dt(appt["start_utc"]) + timedelta(minutes=appt["duration_minutes"])
                if end >= cutoff and end <= now:
                    count += 1
        if p["no_show_strikes"] != count:
            p["no_show_strikes"] = count
            touch(p)
    # Triage expiry: OPEN > 24h
    for tc in DB["triage_cases"].values():
        if tc["status"] == "OPEN":
            opened = parse_dt(tc["created_at"])
            if now - opened > timedelta(hours=24):
                tc["status"] = "EXPIRED"
                touch(tc)
                center = center_of_patient(tc["patient_id"])
                if center is not None:
                    center["ed_referral_count_current_month"] += 1
                    touch(center)
    # Monthly close run: maturity, fill ratio, ED counter reset
    for center in DB["centers"].values():
        center["maturity_months"] = max(0, months_elapsed(center["opened_on"], now))
        center["panel_fill_ratio"] = compute_panel_fill_ratio(center["id"])
        if center.get("_ed_month") != cur_month:
            center["ed_referral_count_current_month"] = 0
            center["_ed_month"] = cur_month
        touch(center)
        apply_saturation(center)


def appointment_cost(appt, no_show=False):
    base = {"PRIMARY": 18000, "BEHAVIORAL": 22000, "CHW_OUTREACH": 9000}[appt["kind"]]
    scaled = dec(base) * dec(appt["duration_minutes"]) / dec(40)
    if no_show:
        scaled = scaled * dec("0.5")
    return round_cents(scaled)


RIDE_COST = 3200


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
@roles("NetworkOperator")
def set_clock():
    b = body()
    require_fields(b, ["current_utc"])
    try:
        dt = parse_dt(b["current_utc"])
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "current_utc must be an ISO8601 timestamp")
    CLOCK["current"] = fmt_dt(dt)
    run_sweeps()
    return success({"current_utc": CLOCK["current"]}, 200)


# ---------------------------------------------------------------------------
# Centers
# ---------------------------------------------------------------------------
def center_view(c):
    return {k: v for k, v in c.items() if not k.startswith("_")}


@app.route("/senior-care/centers", methods=["POST"])
@roles("NetworkOperator")
def create_center():
    b = body()
    require_fields(b, ["name", "neighborhood_code", "opened_on"])
    try:
        parse_date(b["opened_on"])
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "opened_on must be an ISO date")
    c = register("centers", {
        "name": b["name"],
        "neighborhood_code": b["neighborhood_code"],
        "opened_on": b["opened_on"],
        "maturity_months": 0,
        "profitability_tier": "RAMP",
        "panel_fill_ratio": 0.0,
        "cumulative_contribution_cents": 0,
        "ed_referral_count_current_month": 0,
        "status": "PRE_OPEN",
        "_ed_month": current_month(),
    })
    return success(center_view(c), 201)


@app.route("/senior-care/centers", methods=["GET"])
@roles("NetworkOperator", "FinanceAnalyst", "FinanceController", "EnrollmentCoordinator")
def list_centers():
    items = list(DB["centers"].values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response([center_view(c) for c in items])


@app.route("/senior-care/centers/<centerId>", methods=["GET"])
@roles("NetworkOperator", "FinanceAnalyst", "FinanceController", "EnrollmentCoordinator", "CareTeamLead")
def get_center(centerId):
    c = get_or_404("centers", centerId)
    return success(center_view(c), 200)


@app.route("/senior-care/centers/<centerId>/open", methods=["POST"])
@roles("NetworkOperator")
def open_center(centerId):
    c = get_or_404("centers", centerId)
    if c["status"] != "PRE_OPEN":
        raise ApiError("ERR_CENTER_NOT_PRE_OPEN", 409, "Center must be PRE_OPEN to open")
    if not any(t["center_id"] == c["id"] for t in DB["care_teams"].values()):
        raise ApiError("ERR_CENTER_HAS_NO_TEAMS", 409, "Center has no care teams at open")
    if not any(r["center_id"] == c["id"] for r in DB["rooms"].values()):
        raise ApiError("ERR_CENTER_HAS_NO_ROOMS", 409, "Center has no rooms at open")
    c["status"] = "OPEN"
    touch(c)
    return success(center_view(c), 200)


@app.route("/senior-care/centers/<centerId>/close", methods=["POST"])
@roles("NetworkOperator")
def close_center(centerId):
    c = get_or_404("centers", centerId)
    if c["status"] not in ("OPEN", "SATURATED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Center must be OPEN or SATURATED to close")
    team_ids = {t["id"] for t in DB["care_teams"].values() if t["center_id"] == c["id"]}
    for a in DB["attributions"].values():
        if a["care_team_id"] in team_ids and a["status"] in ("PENDING", "ACTIVE", "WAITLISTED"):
            raise ApiError("ERR_CENTER_HAS_ACTIVE_PANEL", 409,
                           "Center still has PENDING/ACTIVE/WAITLISTED attributions at close")
    for s in DB["settlements"].values():
        if s["center_id"] == c["id"] and s["status"] in ("OPEN", "CLOSED_PROVISIONAL"):
            raise ApiError("ERR_CENTER_HAS_OPEN_SETTLEMENT", 409,
                           "Center has an OPEN or CLOSED_PROVISIONAL settlement at close")
    c["status"] = "CLOSED"
    touch(c)
    for v in DB["vehicles"].values():
        if v["center_id"] == c["id"]:
            v["unassignable"] = True
            touch(v)
    for r in DB["rooms"].values():
        if r["center_id"] == c["id"]:
            r["unassignable"] = True
            touch(r)
    return success(center_view(c), 200)


# ---------------------------------------------------------------------------
# Care teams
# ---------------------------------------------------------------------------
def compute_staffing_score(t):
    score = dec(t["physician_count"]) * dec("1.0") + dec(t["chw_count"]) * dec("0.5") + dec(t["behavioral_count"]) * dec("0.75")
    return float(round_dec(score, 2))


@app.route("/senior-care/centers/<centerId>/care-teams", methods=["POST"])
@roles("NetworkOperator")
def create_care_team(centerId):
    c = get_or_404("centers", centerId)
    b = body()
    require_fields(b, ["team_label", "panel_cap", "physician_count", "chw_count", "behavioral_count"])
    panel_cap = check_int(b, "panel_cap", 1)
    physician = check_int(b, "physician_count", 0)
    chw = check_int(b, "chw_count", 0)
    beh = check_int(b, "behavioral_count", 0)
    t = register("care_teams", {
        "center_id": c["id"],
        "team_label": b["team_label"],
        "panel_cap": panel_cap,
        "physician_count": physician,
        "chw_count": chw,
        "behavioral_count": beh,
        "staffing_score": 0.0,
        "active_panel_count": 0,
        "waitlist_depth": 0,
        "accepting": True,
    })
    t["staffing_score"] = compute_staffing_score(t)
    touch(c)
    return success(t, 201)


@app.route("/senior-care/centers/<centerId>/care-teams", methods=["GET"])
@roles("NetworkOperator", "EnrollmentCoordinator", "CareTeamLead", "FinanceAnalyst")
def list_center_teams(centerId):
    c = get_or_404("centers", centerId)
    items = [t for t in DB["care_teams"].values() if t["center_id"] == c["id"]]
    return list_response(items)


@app.route("/senior-care/care-teams", methods=["GET"])
@roles("NetworkOperator", "EnrollmentCoordinator", "CareTeamLead", "FinanceAnalyst")
def list_teams():
    items = list(DB["care_teams"].values())
    cid = request.args.get("center_id")
    if cid is not None:
        items = [t for t in items if t["center_id"] == cid]
    return list_response(items)


@app.route("/senior-care/care-teams/<teamId>", methods=["GET"])
@roles("NetworkOperator", "EnrollmentCoordinator", "CareTeamLead", "FinanceAnalyst")
def get_team(teamId):
    return success(get_or_404("care_teams", teamId), 200)


@app.route("/senior-care/care-teams/<teamId>", methods=["PATCH"])
@roles("NetworkOperator")
def patch_team(teamId):
    t = get_or_404("care_teams", teamId)
    b = body()
    if "panel_cap" in b:
        new_cap = check_int(b, "panel_cap", 1)
        if new_cap < t["active_panel_count"]:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "panel_cap must be >= active_panel_count when lowered")
    for f in ("physician_count", "chw_count", "behavioral_count"):
        if f in b:
            check_int(b, f, 0)
    center = center_of_team(t)
    if "panel_cap" in b:
        t["panel_cap"] = b["panel_cap"]
    for f in ("physician_count", "chw_count", "behavioral_count"):
        if f in b:
            t[f] = b[f]
    t["staffing_score"] = compute_staffing_score(t)
    touch(t)
    if center is not None and center["status"] == "SATURATED":
        apply_saturation(center)
    return success(t, 200)


@app.route("/senior-care/care-teams/<teamId>/attributions", methods=["GET"])
@roles("EnrollmentCoordinator", "CareTeamLead")
def list_team_attributions(teamId):
    t = get_or_404("care_teams", teamId)
    items = [a for a in DB["attributions"].values() if a["care_team_id"] == t["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items)


@app.route("/senior-care/care-teams/<teamId>/appointments", methods=["GET"])
@roles("FrontDesk", "CareTeamLead")
def list_team_appointments(teamId):
    t = get_or_404("care_teams", teamId)
    items = [a for a in DB["appointments"].values() if a["care_team_id"] == t["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items)


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------
@app.route("/senior-care/centers/<centerId>/rooms", methods=["POST"])
@roles("NetworkOperator")
def create_room(centerId):
    c = get_or_404("centers", centerId)
    b = body()
    require_fields(b, ["room_label"])
    sb = b.get("supports_behavioral", False)
    if not isinstance(sb, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "supports_behavioral must be a boolean")
    r = register("rooms", {
        "center_id": c["id"],
        "room_label": b["room_label"],
        "supports_behavioral": sb,
    })
    return success(r, 201)


@app.route("/senior-care/centers/<centerId>/rooms", methods=["GET"])
@roles("NetworkOperator", "FrontDesk", "CareTeamLead")
def list_center_rooms(centerId):
    c = get_or_404("centers", centerId)
    return list_response([r for r in DB["rooms"].values() if r["center_id"] == c["id"]])


@app.route("/senior-care/rooms", methods=["GET"])
@roles("NetworkOperator", "FrontDesk", "CareTeamLead")
def list_rooms():
    items = list(DB["rooms"].values())
    cid = request.args.get("center_id")
    if cid is not None:
        items = [r for r in items if r["center_id"] == cid]
    return list_response(items)


@app.route("/senior-care/rooms/<roomId>", methods=["GET"])
@roles("NetworkOperator", "FrontDesk", "CareTeamLead")
def get_room(roomId):
    return success(get_or_404("rooms", roomId), 200)


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------
@app.route("/senior-care/centers/<centerId>/vehicles", methods=["POST"])
@roles("NetworkOperator")
def create_vehicle(centerId):
    c = get_or_404("centers", centerId)
    b = body()
    require_fields(b, ["plate", "seat_capacity"])
    cap = check_int(b, "seat_capacity", 1)
    wc = b.get("wheelchair_capable", False)
    if not isinstance(wc, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "wheelchair_capable must be a boolean")
    v = register("vehicles", {
        "center_id": c["id"],
        "plate": b["plate"],
        "seat_capacity": cap,
        "wheelchair_capable": wc,
    })
    return success(v, 201)


@app.route("/senior-care/centers/<centerId>/vehicles", methods=["GET"])
@roles("NetworkOperator", "TransportDispatcher")
def list_center_vehicles(centerId):
    c = get_or_404("centers", centerId)
    return list_response([v for v in DB["vehicles"].values() if v["center_id"] == c["id"]])


@app.route("/senior-care/vehicles", methods=["GET"])
@roles("NetworkOperator", "TransportDispatcher")
def list_vehicles():
    items = list(DB["vehicles"].values())
    cid = request.args.get("center_id")
    if cid is not None:
        items = [v for v in items if v["center_id"] == cid]
    return list_response(items)


@app.route("/senior-care/vehicles/<vehicleId>", methods=["GET"])
@roles("NetworkOperator", "TransportDispatcher")
def get_vehicle(vehicleId):
    return success(get_or_404("vehicles", vehicleId), 200)


@app.route("/senior-care/vehicles/<vehicleId>/ride-requests", methods=["GET"])
@roles("TransportDispatcher")
def list_vehicle_rides(vehicleId):
    v = get_or_404("vehicles", vehicleId)
    items = [r for r in DB["rides"].values() if r.get("assigned_vehicle_id") == v["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items)


# ---------------------------------------------------------------------------
# Outreach events
# ---------------------------------------------------------------------------
@app.route("/senior-care/centers/<centerId>/outreach-events", methods=["POST"])
@roles("EnrollmentCoordinator")
def create_event(centerId):
    c = get_or_404("centers", centerId)
    b = body()
    require_fields(b, ["event_label", "scheduled_on", "expected_attendance"])
    try:
        sched = parse_date(b["scheduled_on"])
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "scheduled_on must be an ISO date")
    check_int(b, "expected_attendance", 1)
    if sched < now_dt().date():
        raise ApiError("ERR_TEMPORAL_VIOLATION", 422, "scheduled_on must not be in the past")
    e = register("events", {
        "center_id": c["id"],
        "event_label": b["event_label"],
        "scheduled_on": b["scheduled_on"],
        "expected_attendance": b["expected_attendance"],
        "attributed_signups": 0,
    })
    return success(e, 201)


@app.route("/senior-care/centers/<centerId>/outreach-events", methods=["GET"])
@roles("NetworkOperator", "EnrollmentCoordinator")
def list_center_events(centerId):
    c = get_or_404("centers", centerId)
    return list_response([e for e in DB["events"].values() if e["center_id"] == c["id"]])


@app.route("/senior-care/outreach-events", methods=["GET"])
@roles("NetworkOperator", "EnrollmentCoordinator")
def list_events():
    items = list(DB["events"].values())
    cid = request.args.get("center_id")
    if cid is not None:
        items = [e for e in items if e["center_id"] == cid]
    return list_response(items)


@app.route("/senior-care/outreach-events/<eventId>", methods=["GET"])
@roles("NetworkOperator", "EnrollmentCoordinator")
def get_event(eventId):
    return success(get_or_404("events", eventId), 200)


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------
@app.route("/senior-care/patients", methods=["POST"])
@roles("EnrollmentCoordinator")
def create_patient():
    b = body()
    require_fields(b, ["full_name", "date_of_birth", "zip_code", "risk_score"])
    try:
        dob = parse_date(b["date_of_birth"])
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "date_of_birth must be an ISO date")
    risk = check_number(b, "risk_score")
    risk_d = round_dec(dec(risk), 2)
    if risk_d < dec("0.50") or risk_d > dec("4.00"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "risk_score must be between 0.50 and 4.00")
    td = b.get("transport_dependent", False)
    if not isinstance(td, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "transport_dependent must be a boolean")
    now_d = now_dt().date()
    age = now_d.year - dob.year - ((now_d.month, now_d.day) < (dob.month, dob.day))
    if age < 60:
        raise ApiError("ERR_INVALID_REQUEST", 400, "patient must be at least 60 years old")
    p = register("patients", {
        "full_name": b["full_name"],
        "date_of_birth": b["date_of_birth"],
        "zip_code": b["zip_code"],
        "risk_score": float(risk_d),
        "transport_dependent": td,
        "no_show_strikes": 0,
    })
    return success(p, 201)


@app.route("/senior-care/patients/<patientId>", methods=["GET"])
@roles("EnrollmentCoordinator", "CareTeamLead", "FrontDesk", "TriageNurse", "TransportDispatcher", "ClaimsAdjudicator")
def get_patient(patientId):
    return success(get_or_404("patients", patientId), 200)


@app.route("/senior-care/patients/<patientId>/attributions", methods=["GET"])
@roles("EnrollmentCoordinator", "FinanceAnalyst")
def list_patient_attributions(patientId):
    p = get_or_404("patients", patientId)
    return list_response([a for a in DB["attributions"].values() if a["patient_id"] == p["id"]])


@app.route("/senior-care/patients/<patientId>/triage-cases", methods=["GET"])
@roles("TriageNurse", "CareTeamLead")
def list_patient_triage(patientId):
    p = get_or_404("patients", patientId)
    return list_response([t for t in DB["triage_cases"].values() if t["patient_id"] == p["id"]])


# ---------------------------------------------------------------------------
# Health plans
# ---------------------------------------------------------------------------
@app.route("/senior-care/health-plans", methods=["POST"])
@roles("FinanceController")
def create_plan():
    b = body()
    require_fields(b, ["plan_name", "contract_type", "base_pmpm_cents", "risk_adjust_factor", "revenue_share_pct"])
    ct = check_enum(b, "contract_type", ("FULL_RISK", "SHARED_SAVINGS"))
    base = check_int(b, "base_pmpm_cents", 0)
    raf = check_number(b, "risk_adjust_factor")
    rsp = check_number(b, "revenue_share_pct")
    if dec(raf) < dec("0.80") or dec(raf) > dec("1.60"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "risk_adjust_factor must be between 0.80 and 1.60")
    if dec(rsp) < dec("0.50") or dec(rsp) > dec("1.00"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "revenue_share_pct must be between 0.50 and 1.00")
    p = register("health_plans", {
        "plan_name": b["plan_name"],
        "contract_type": ct,
        "base_pmpm_cents": base,
        "risk_adjust_factor": raf,
        "revenue_share_pct": rsp,
    })
    return success(p, 201)


@app.route("/senior-care/health-plans/<planId>", methods=["GET"])
@roles("FinanceAnalyst", "FinanceController", "EnrollmentCoordinator")
def get_plan(planId):
    return success(get_or_404("health_plans", planId), 200)


@app.route("/senior-care/health-plans/<planId>/quote", methods=["GET"])
@roles("FinanceAnalyst", "FinanceController", "EnrollmentCoordinator")
def quote_plan(planId):
    plan = get_or_404("health_plans", planId)
    risk_q = request.args.get("risk_score")
    center_id = request.args.get("center_id")
    if risk_q is None or center_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "risk_score and center_id are required")
    try:
        risk = dec(risk_q)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "risk_score must be a number")
    center = DB["centers"].get(center_id)
    if center is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Resource {center_id} not found")
    risk_clamped = max(dec("0.50"), min(dec("4.00"), risk))
    mult = {"RAMP": dec("0.95"), "BREAKEVEN": dec("1.00"), "MATURE": dec("1.05")}[center["profitability_tier"]]
    quote = round_cents(dec(plan["base_pmpm_cents"]) * risk_clamped * dec(plan["risk_adjust_factor"]) * mult)
    return success({"quote_cents": quote, "tier_applied": center["profitability_tier"]}, 200)


# ---------------------------------------------------------------------------
# Attributions
# ---------------------------------------------------------------------------
@app.route("/senior-care/patient-attributions", methods=["POST"])
@roles("EnrollmentCoordinator")
def create_attribution():
    b = body()
    require_fields(b, ["patient_id", "health_plan_id", "care_team_id", "effective_month"])
    patient = DB["patients"].get(b["patient_id"])
    if patient is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "patient_id does not reference an existing patient")
    plan = DB["health_plans"].get(b["health_plan_id"])
    if plan is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "health_plan_id does not reference an existing plan")
    team = DB["care_teams"].get(b["care_team_id"])
    if team is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "care_team_id does not reference an existing team")
    em = b["effective_month"]
    if not (isinstance(em, str) and len(em) == 7 and em[4] == "-"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "effective_month must be YYYY-MM")
    try:
        month_start(em)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "effective_month must be YYYY-MM")
    if em < current_month():
        raise ApiError("ERR_TEMPORAL_VIOLATION", 422, "effective_month must be >= current logical month")
    for a in DB["attributions"].values():
        if a["patient_id"] == patient["id"] and a["status"] in ("PENDING", "ACTIVE"):
            raise ApiError("ERR_PATIENT_ALREADY_ATTRIBUTED", 409,
                           "Patient already holds an ACTIVE or PENDING attribution")
    event = None
    if "outreach_event_id" in b and b["outreach_event_id"] is not None:
        event = DB["events"].get(b["outreach_event_id"])
        if event is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "outreach_event_id does not reference an existing event")
    a = register("attributions", {
        "patient_id": patient["id"],
        "health_plan_id": plan["id"],
        "care_team_id": team["id"],
        "effective_month": em,
        "status": "PENDING",
        "disenrolled_month": None,
        "activated_on": None,
        "disenrolled_on": None,
    })
    if "outreach_event_id" in b:
        a["outreach_event_id"] = b["outreach_event_id"]
    if event is not None:
        event["attributed_signups"] += 1
        touch(event)
    return success(a, 201)


@app.route("/senior-care/patient-attributions", methods=["GET"])
@roles("EnrollmentCoordinator", "FinanceAnalyst")
def list_attributions():
    items = list(DB["attributions"].values())
    for param, field in (("patient_id", "patient_id"), ("health_plan_id", "health_plan_id"),
                         ("care_team_id", "care_team_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a[field] == v]
    return list_response(items)


@app.route("/senior-care/patient-attributions/<attrId>", methods=["GET"])
@roles("EnrollmentCoordinator", "FinanceAnalyst")
def get_attribution(attrId):
    return success(get_or_404("attributions", attrId), 200)


@app.route("/senior-care/patient-attributions/<attrId>/activate", methods=["POST"])
@roles("EnrollmentCoordinator")
def activate_attribution(attrId):
    a = get_or_404("attributions", attrId)
    b = body()
    team = DB["care_teams"].get(a["care_team_id"])
    if "expected_care_team_version" in b and b["expected_care_team_version"] is not None:
        ev = b["expected_care_team_version"]
        if isinstance(ev, bool) or not isinstance(ev, int):
            raise ApiError("ERR_INVALID_REQUEST", 400, "expected_care_team_version must be an integer")
        if team is not None and ev != team["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "expected_care_team_version does not match the team's current version")
    if a["status"] != "PENDING":
        raise ApiError("ERR_ATTRIBUTION_NOT_PENDING", 409, "Attribution must be PENDING to activate")
    if a["effective_month"] > current_month():
        raise ApiError("ERR_ATTRIBUTION_NOT_YET_EFFECTIVE", 409, "effective_month is after the current logical month")
    if team is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Care team not found")
    if not team["accepting"]:
        raise ApiError("ERR_TEAM_NOT_ACCEPTING", 409, "Target care team accepting flag is false")
    if team["active_panel_count"] >= team["panel_cap"]:
        raise ApiError("ERR_PANEL_CAP_REACHED", 409, "CareTeam.active_panel_count >= panel_cap at activation")
    for other in DB["attributions"].values():
        if other["id"] != a["id"] and other["patient_id"] == a["patient_id"] and other["status"] in ("ACTIVE", "PENDING"):
            raise ApiError("ERR_PATIENT_ALREADY_ATTRIBUTED", 409,
                           "Patient already holds an ACTIVE or PENDING attribution")
    a["status"] = "ACTIVE"
    a["activated_on"] = now_dt().date().isoformat()
    touch(a)
    team["active_panel_count"] += 1
    touch(team)
    center = center_of_team(team)
    if center is not None:
        apply_saturation(center)
    return success(a, 200)


@app.route("/senior-care/patient-attributions/<attrId>/disenroll", methods=["POST"])
@roles("EnrollmentCoordinator")
def disenroll_attribution(attrId):
    a = get_or_404("attributions", attrId)
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_ATTRIBUTION_NOT_ACTIVE", 409, "Attribution must be ACTIVE to disenroll")
    team = DB["care_teams"].get(a["care_team_id"])
    a["status"] = "DISENROLLED"
    a["disenrolled_month"] = current_month()
    a["disenrolled_on"] = now_dt().date().isoformat()
    touch(a)
    if team is not None:
        team["active_panel_count"] = max(0, team["active_panel_count"] - 1)
        touch(team)
        center = center_of_team(team)
        if center is not None and center["status"] == "SATURATED":
            apply_saturation(center)
    return success(a, 200)


@app.route("/senior-care/patient-attributions/<attrId>/reattribute", methods=["POST"])
@roles("EnrollmentCoordinator")
def reattribute(attrId):
    a = get_or_404("attributions", attrId)
    b = body()
    require_fields(b, ["new_attribution_id"])
    if a["status"] != "DISENROLLED":
        raise ApiError("ERR_ATTRIBUTION_NOT_DISENROLLED", 409, "Attribution must be DISENROLLED to reattribute")
    new_a = DB["attributions"].get(b["new_attribution_id"])
    if new_a is None or new_a["status"] != "PENDING":
        raise ApiError("ERR_NEW_ATTRIBUTION_NOT_PENDING", 409,
                       "new_attribution_id must reference a PENDING attribution")
    if new_a["effective_month"] <= a["disenrolled_month"]:
        raise ApiError("ERR_REATTRIBUTION_MONTH_NOT_AFTER_DISENROLL", 422,
                       "New attribution effective_month must be after the old row's disenrolled_month")
    a["status"] = "REATTRIBUTED"
    touch(a)
    return success(a, 200)


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------
def rooms_overlap(s1, d1, s2, d2):
    e1 = s1 + timedelta(minutes=d1)
    e2 = s2 + timedelta(minutes=d2)
    return s1 < e2 and s2 < e1


@app.route("/senior-care/appointments", methods=["POST"])
@roles("FrontDesk", "CareTeamLead")
def create_appointment():
    b = body()
    require_fields(b, ["care_team_id", "patient_id", "room_id", "start_utc", "duration_minutes", "kind"])
    team = DB["care_teams"].get(b["care_team_id"])
    patient = DB["patients"].get(b["patient_id"])
    room = DB["rooms"].get(b["room_id"])
    dur = b["duration_minutes"]
    if isinstance(dur, bool) or dur not in (20, 40, 60):
        raise ApiError("ERR_INVALID_REQUEST", 400, "duration_minutes must be 20, 40, or 60")
    kind = check_enum(b, "kind", ("PRIMARY", "BEHAVIORAL", "CHW_OUTREACH"))
    try:
        start = parse_dt(b["start_utc"])
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "start_utc must be an ISO8601 timestamp")
    if start.minute % 20 != 0 or start.second != 0 or start.microsecond != 0:
        raise ApiError("ERR_TEMPORAL_VIOLATION", 422, "start_utc must fall on a 20-minute boundary")
    if team is None or patient is None or room is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "care_team_id, patient_id and room_id must reference existing entities")
    # Cross-reference: patient must hold ACTIVE attribution at team's center
    attributed = False
    for a in DB["attributions"].values():
        if a["patient_id"] == patient["id"] and a["status"] == "ACTIVE":
            at = DB["care_teams"].get(a["care_team_id"])
            if at is not None and at["center_id"] == team["center_id"]:
                attributed = True
                break
    if not attributed:
        raise ApiError("ERR_CROSS_REFERENCE_MISMATCH", 422,
                       "Patient is not attributed to the team's center")
    if room["center_id"] != team["center_id"]:
        raise ApiError("ERR_CROSS_REFERENCE_MISMATCH", 422, "Room does not belong to the team's center")
    if kind == "BEHAVIORAL" and not room.get("supports_behavioral", False):
        raise ApiError("ERR_CROSS_REFERENCE_MISMATCH", 422,
                       "BEHAVIORAL appointments require a supports_behavioral room")
    for appt in DB["appointments"].values():
        if appt["room_id"] == room["id"] and appt["status"] in ("SCHEDULED", "CHECKED_IN"):
            if rooms_overlap(parse_dt(appt["start_utc"]), appt["duration_minutes"], start, dur):
                raise ApiError("ERR_SCHEDULE_CONFLICT", 409, "Room is already reserved over an overlapping interval")
    a = register("appointments", {
        "care_team_id": team["id"],
        "patient_id": patient["id"],
        "room_id": room["id"],
        "start_utc": fmt_dt(start),
        "duration_minutes": dur,
        "kind": kind,
        "status": "SCHEDULED",
        "cost_cents": None,
    })
    return success(a, 201)


@app.route("/senior-care/appointments", methods=["GET"])
@roles("FrontDesk", "CareTeamLead", "TransportDispatcher", "TriageNurse")
def list_appointments():
    items = list(DB["appointments"].values())
    for param in ("care_team_id", "patient_id", "room_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a[param] == v]
    return list_response(items)


@app.route("/senior-care/appointments/<apptId>", methods=["GET"])
@roles("FrontDesk", "CareTeamLead", "TransportDispatcher", "TriageNurse")
def get_appointment(apptId):
    return success(get_or_404("appointments", apptId), 200)


@app.route("/senior-care/appointments/<apptId>/check-in", methods=["POST"])
@roles("FrontDesk")
def checkin_appointment(apptId):
    a = get_or_404("appointments", apptId)
    if a["status"] != "SCHEDULED":
        raise ApiError("ERR_APPOINTMENT_NOT_SCHEDULED", 409, "Appointment must be SCHEDULED for this operation")
    now = now_dt()
    start = parse_dt(a["start_utc"])
    end = start + timedelta(minutes=a["duration_minutes"])
    if not (start - timedelta(minutes=30) <= now <= end):
        raise ApiError("ERR_CHECKIN_WINDOW_MISSED", 409, "Logical clock outside the check-in window")
    a["status"] = "CHECKED_IN"
    touch(a)
    return success(a, 200)


@app.route("/senior-care/appointments/<apptId>/complete", methods=["POST"])
@roles("CareTeamLead")
def complete_appointment(apptId):
    a = get_or_404("appointments", apptId)
    if a["status"] != "CHECKED_IN":
        raise ApiError("ERR_APPOINTMENT_NOT_CHECKED_IN", 409, "Appointment must be CHECKED_IN to complete")
    a["status"] = "COMPLETED"
    a["cost_cents"] = appointment_cost(a, no_show=False)
    touch(a)
    for r in DB["rides"].values():
        if r["appointment_id"] == a["id"] and r["status"] in ("DISPATCHED", "EN_ROUTE"):
            r["status"] = "DELIVERED"
            r["cost_cents"] = RIDE_COST
            touch(r)
    return success(a, 200)


@app.route("/senior-care/appointments/<apptId>/cancel", methods=["POST"])
@roles("FrontDesk")
def cancel_appointment(apptId):
    a = get_or_404("appointments", apptId)
    if a["status"] != "SCHEDULED":
        raise ApiError("ERR_APPOINTMENT_NOT_SCHEDULED", 409, "Appointment must be SCHEDULED for this operation")
    if now_dt() >= parse_dt(a["start_utc"]):
        raise ApiError("ERR_CANCEL_TOO_LATE", 409, "Cannot cancel at or after start_utc")
    a["status"] = "CANCELLED"
    touch(a)
    for r in DB["rides"].values():
        if r["appointment_id"] == a["id"] and r["status"] in ("REQUESTED", "DISPATCHED"):
            r["status"] = "CANCELLED"
            touch(r)
    return success(a, 200)


# ---------------------------------------------------------------------------
# Ride requests
# ---------------------------------------------------------------------------
@app.route("/senior-care/appointments/<apptId>/ride-requests", methods=["POST"])
@roles("TransportDispatcher", "FrontDesk")
def create_ride(apptId):
    a = get_or_404("appointments", apptId)
    patient = DB["patients"].get(a["patient_id"])
    if patient is not None and patient["no_show_strikes"] >= 3:
        raise ApiError("ERR_TRANSPORT_PRIVILEGE_SUSPENDED", 409,
                       "Patient has >= 3 no-show strikes; ride creation rejected")
    start = parse_dt(a["start_utc"])
    r = register("rides", {
        "appointment_id": a["id"],
        "patient_id": a["patient_id"],
        "pickup_window_start": fmt_dt(start - timedelta(minutes=90)),
        "pickup_window_end": fmt_dt(start - timedelta(minutes=30)),
        "assigned_vehicle_id": None,
        "status": "REQUESTED",
        "failure_count": 0,
        "cost_cents": None,
    })
    return success(r, 201)


@app.route("/senior-care/appointments/<apptId>/ride-requests", methods=["GET"])
@roles("TransportDispatcher", "FrontDesk")
def list_appointment_rides(apptId):
    a = get_or_404("appointments", apptId)
    return list_response([r for r in DB["rides"].values() if r["appointment_id"] == a["id"]])


@app.route("/senior-care/ride-requests", methods=["GET"])
@roles("TransportDispatcher", "FrontDesk")
def list_rides():
    items = list(DB["rides"].values())
    for param in ("appointment_id", "patient_id", "assigned_vehicle_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    return list_response(items)


@app.route("/senior-care/ride-requests/<rideId>", methods=["GET"])
@roles("TransportDispatcher", "FrontDesk")
def get_ride(rideId):
    return success(get_or_404("rides", rideId), 200)


def windows_overlap(r1, r2):
    s1, e1 = parse_dt(r1["pickup_window_start"]), parse_dt(r1["pickup_window_end"])
    s2, e2 = parse_dt(r2["pickup_window_start"]), parse_dt(r2["pickup_window_end"])
    return s1 < e2 and s2 < e1


@app.route("/senior-care/ride-requests/<rideId>/dispatch", methods=["POST"])
@roles("TransportDispatcher")
def dispatch_ride(rideId):
    r = get_or_404("rides", rideId)
    b = body()
    require_fields(b, ["vehicle_id"])
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_RIDE_NOT_REQUESTED", 409, "Ride must be REQUESTED to dispatch")
    appt = DB["appointments"].get(r["appointment_id"])
    team = DB["care_teams"].get(appt["care_team_id"]) if appt else None
    patient = DB["patients"].get(r["patient_id"])
    v = DB["vehicles"].get(b["vehicle_id"])
    if v is None or team is None or v["center_id"] != team["center_id"]:
        raise ApiError("ERR_VEHICLE_INELIGIBLE", 422, "Vehicle missing or belongs to a different center")
    if patient is not None and patient.get("transport_dependent") and not v.get("wheelchair_capable", False):
        raise ApiError("ERR_VEHICLE_INELIGIBLE", 422, "Patient requires a wheelchair_capable vehicle")
    occupied = 0
    for other in DB["rides"].values():
        if other["id"] == r["id"]:
            continue
        if other.get("assigned_vehicle_id") == v["id"] and other["status"] in ("DISPATCHED", "EN_ROUTE"):
            if windows_overlap(r, other):
                occupied += 1
    if occupied + 1 > v["seat_capacity"]:
        raise ApiError("ERR_VEHICLE_CAPACITY_EXCEEDED", 409,
                       "Vehicle seat capacity exceeded over the overlapping pickup windows")
    if patient is not None and patient["no_show_strikes"] >= 3:
        raise ApiError("ERR_TRANSPORT_PRIVILEGE_SUSPENDED", 409,
                       "Patient has >= 3 no-show strikes; dispatch rejected")
    r["status"] = "DISPATCHED"
    r["assigned_vehicle_id"] = v["id"]
    touch(r)
    return success(r, 200)


@app.route("/senior-care/ride-requests/<rideId>/start-pickup", methods=["POST"])
@roles("TransportDispatcher")
def start_pickup(rideId):
    r = get_or_404("rides", rideId)
    if r["status"] != "DISPATCHED":
        raise ApiError("ERR_RIDE_NOT_DISPATCHED", 409, "Ride must be DISPATCHED to start pickup")
    now = now_dt()
    if not (parse_dt(r["pickup_window_start"]) <= now <= parse_dt(r["pickup_window_end"])):
        raise ApiError("ERR_PICKUP_WINDOW_MISSED", 409, "Logical clock outside the pickup window")
    r["status"] = "EN_ROUTE"
    touch(r)
    return success(r, 200)


@app.route("/senior-care/ride-requests/<rideId>/mark-no-show", methods=["POST"])
@roles("TransportDispatcher")
def mark_no_show(rideId):
    r = get_or_404("rides", rideId)
    if r["status"] != "EN_ROUTE":
        raise ApiError("ERR_RIDE_NOT_EN_ROUTE", 409, "Ride must be EN_ROUTE to mark no-show")
    r["status"] = "FAILED_NO_SHOW"
    r["failure_count"] += 1
    r["cost_cents"] = RIDE_COST
    touch(r)
    return success(r, 200)


@app.route("/senior-care/ride-requests/<rideId>/recover", methods=["POST"])
@roles("TransportDispatcher")
def recover_ride(rideId):
    r = get_or_404("rides", rideId)
    if r["status"] != "FAILED_NO_SHOW":
        raise ApiError("ERR_RIDE_NOT_FAILED", 409, "Ride must be FAILED_NO_SHOW to recover")
    appt = DB["appointments"].get(r["appointment_id"])
    if appt is not None:
        end = parse_dt(appt["start_utc"]) + timedelta(minutes=appt["duration_minutes"])
        if now_dt() >= end:
            raise ApiError("ERR_RECOVERY_WINDOW_MISSED", 409, "Recovery attempted after the appointment end time")
    r["status"] = "REQUESTED"
    r["assigned_vehicle_id"] = None
    touch(r)
    return success(r, 200)


# ---------------------------------------------------------------------------
# Triage cases
# ---------------------------------------------------------------------------
@app.route("/senior-care/triage-cases", methods=["POST"])
@roles("TriageNurse")
def create_triage():
    b = body()
    require_fields(b, ["patient_id", "channel", "severity"])
    patient = DB["patients"].get(b["patient_id"])
    channel = check_enum(b, "channel", ("AFTER_HOURS_LINE", "WALK_IN", "CARE_TEAM_ESCALATION"))
    severity = check_enum(b, "severity", ("LOW", "MODERATE", "HIGH"))
    if patient is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "patient_id does not reference an existing patient")
    t = register("triage_cases", {
        "patient_id": patient["id"],
        "channel": channel,
        "severity": severity,
        "disposition": None,
        "diversion_success": None,
        "status": "OPEN",
        "urgent_appointment_id": None,
        "resolved_on": None,
    })
    return success(t, 201)


@app.route("/senior-care/triage-cases", methods=["GET"])
@roles("TriageNurse", "CareTeamLead")
def list_triage():
    items = list(DB["triage_cases"].values())
    for param in ("patient_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [t for t in items if t[param] == v]
    return list_response(items)


@app.route("/senior-care/triage-cases/<caseId>", methods=["GET"])
@roles("TriageNurse", "CareTeamLead")
def get_triage(caseId):
    return success(get_or_404("triage_cases", caseId), 200)


@app.route("/senior-care/triage-cases/<caseId>/divert", methods=["POST"])
@roles("TriageNurse")
def divert_triage(caseId):
    t = get_or_404("triage_cases", caseId)
    b = body()
    if t["status"] != "OPEN":
        raise ApiError("ERR_TRIAGE_NOT_OPEN", 409, "Triage case must be OPEN for this operation")
    if t["severity"] == "HIGH":
        raise ApiError("ERR_SEVERITY_REQUIRES_ED", 422, "HIGH severity cannot be diverted to urgent care")
    appt_id = b.get("urgent_appointment_id")
    appt = DB["appointments"].get(appt_id) if appt_id else None
    if appt is None or appt["status"] != "SCHEDULED" or appt["kind"] != "PRIMARY":
        raise ApiError("ERR_URGENT_SLOT_INVALID", 422,
                       "urgent_appointment_id must reference a SCHEDULED PRIMARY appointment")
    team = DB["care_teams"].get(appt["care_team_id"])
    center = center_of_patient(t["patient_id"])
    if team is None or center is None or team["center_id"] != center["id"]:
        raise ApiError("ERR_CROSS_REFERENCE_MISMATCH", 422, "Urgent slot belongs to a different center")
    now = now_dt()
    start = parse_dt(appt["start_utc"])
    if start < now or start > now + timedelta(hours=24):
        raise ApiError("ERR_URGENT_SLOT_INVALID", 422, "Urgent slot must start within the next 24 hours")
    t["status"] = "RESOLVED_DIVERTED"
    t["disposition"] = "URGENT_CARE_BOOKED"
    t["urgent_appointment_id"] = appt["id"]
    t["resolved_on"] = now_dt().date().isoformat()
    touch(t)
    return success(t, 200)


@app.route("/senior-care/triage-cases/<caseId>/refer-ed", methods=["POST"])
@roles("TriageNurse")
def refer_ed(caseId):
    t = get_or_404("triage_cases", caseId)
    if t["status"] != "OPEN":
        raise ApiError("ERR_TRIAGE_NOT_OPEN", 409, "Triage case must be OPEN for this operation")
    t["status"] = "RESOLVED_ED"
    t["disposition"] = "ED_REFERRED"
    t["diversion_success"] = False
    t["resolved_on"] = now_dt().date().isoformat()
    touch(t)
    center = center_of_patient(t["patient_id"])
    if center is not None:
        center["ed_referral_count_current_month"] += 1
        touch(center)
    return success(t, 200)


@app.route("/senior-care/triage-cases/<caseId>/advise-self-care", methods=["POST"])
@roles("TriageNurse")
def advise_self_care(caseId):
    t = get_or_404("triage_cases", caseId)
    if t["status"] != "OPEN":
        raise ApiError("ERR_TRIAGE_NOT_OPEN", 409, "Triage case must be OPEN for this operation")
    if t["severity"] != "LOW":
        raise ApiError("ERR_SEVERITY_TOO_HIGH_FOR_SELF_CARE", 422,
                       "Self-care advice allowed only for LOW severity")
    t["status"] = "RESOLVED_SELF_CARE"
    t["disposition"] = "SELF_CARE_ADVISED"
    t["resolved_on"] = now_dt().date().isoformat()
    touch(t)
    return success(t, 200)


# ---------------------------------------------------------------------------
# Cost claims
# ---------------------------------------------------------------------------
def settlement_for(center_id, month):
    for s in DB["settlements"].values():
        if s["center_id"] == center_id and s["period_month"] == month:
            return s
    return None


@app.route("/senior-care/cost-claims", methods=["POST"])
@roles("ClaimsAdjudicator", "FinanceAnalyst")
def create_claim():
    b = body()
    require_fields(b, ["center_id", "patient_id", "service_month", "category", "amount_cents"])
    center = DB["centers"].get(b["center_id"])
    patient = DB["patients"].get(b["patient_id"])
    category = check_enum(b, "category",
                          ("ED_VISIT", "INPATIENT", "SPECIALIST", "PHARMACY", "TRANSPORT", "INTERNAL_VISIT"))
    amount = check_int(b, "amount_cents", 1)
    sm = b["service_month"]
    if not (isinstance(sm, str) and len(sm) == 7 and sm[4] == "-"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "service_month must be YYYY-MM")
    try:
        month_start(sm)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "service_month must be YYYY-MM")
    if center is None or patient is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "center_id and patient_id must reference existing entities")
    if sm > current_month():
        raise ApiError("ERR_TEMPORAL_VIOLATION", 422, "service_month must be <= current logical month")
    s = settlement_for(center["id"], sm)
    if s is not None and s["status"] == "FINALIZED":
        raise ApiError("ERR_SETTLEMENT_FINALIZED", 409,
                       "The period settlement is FINALIZED; claims are read-only")
    c = register("claims", {
        "center_id": center["id"],
        "patient_id": patient["id"],
        "service_month": sm,
        "category": category,
        "amount_cents": amount,
        "adjudicated_amount_cents": None,
        "status": "SUBMITTED",
    })
    return success(c, 201)


@app.route("/senior-care/cost-claims", methods=["GET"])
@roles("ClaimsAdjudicator", "FinanceAnalyst", "FinanceController")
def list_claims():
    items = list(DB["claims"].values())
    for param in ("center_id", "patient_id", "status", "service_month"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[param] == v]
    return list_response(items)


@app.route("/senior-care/cost-claims/<claimId>", methods=["GET"])
@roles("ClaimsAdjudicator", "FinanceAnalyst", "FinanceController")
def get_claim(claimId):
    return success(get_or_404("claims", claimId), 200)


@app.route("/senior-care/cost-claims/<claimId>/adjudicate", methods=["POST"])
@roles("ClaimsAdjudicator")
def adjudicate_claim(claimId):
    c = get_or_404("claims", claimId)
    b = body()
    require_fields(b, ["adjudicated_amount_cents"])
    adj = b["adjudicated_amount_cents"]
    if isinstance(adj, bool) or not isinstance(adj, int) or adj < 0 or adj > c["amount_cents"]:
        raise ApiError("ERR_ADJUDICATED_AMOUNT_INVALID", 400,
                       "adjudicated_amount_cents outside 0..amount_cents")
    if c["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED", 409, "Claim must be SUBMITTED for this operation")
    s = settlement_for(c["center_id"], c["service_month"])
    if s is not None and s["status"] not in ("OPEN", "CLOSED_PROVISIONAL"):
        raise ApiError("ERR_SETTLEMENT_FINALIZED", 409,
                       "The period settlement is FINALIZED; claims are read-only")
    c["status"] = "ADJUDICATED"
    c["adjudicated_amount_cents"] = adj
    touch(c)
    if s is not None:
        recompute_settlement_costs(s)
    return success(c, 200)


@app.route("/senior-care/cost-claims/<claimId>/reject", methods=["POST"])
@roles("ClaimsAdjudicator")
def reject_claim(claimId):
    c = get_or_404("claims", claimId)
    if c["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED", 409, "Claim must be SUBMITTED for this operation")
    s = settlement_for(c["center_id"], c["service_month"])
    if s is not None and s["status"] == "FINALIZED":
        raise ApiError("ERR_SETTLEMENT_FINALIZED", 409,
                       "The period settlement is FINALIZED; claims are read-only")
    c["status"] = "REJECTED"
    c["adjudicated_amount_cents"] = 0
    touch(c)
    return success(c, 200)


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------
def active_interval_in_period(a, period):
    """Return (start_date, end_date) inclusive dates ACTIVE within period, or None."""
    if a["status"] not in ("ACTIVE", "DISENROLLED", "REATTRIBUTED"):
        return None
    act_on = a.get("activated_on")
    if act_on is None:
        return None
    start = parse_date(act_on)
    if a["status"] in ("DISENROLLED", "REATTRIBUTED") and a.get("disenrolled_on"):
        end = parse_date(a["disenrolled_on"])
    else:
        end = None
    p_start = month_start(period).date()
    p_end = (month_end_exclusive(period) - timedelta(days=1)).date()
    lo = max(start, p_start)
    hi = min(end, p_end) if end is not None else p_end
    if lo > hi:
        return None
    return lo, hi


def compute_accrual(center_id, period, variant):
    """Returns (member_months_int, accrued_revenue_cents)."""
    dim = dec(days_in_month(period))
    total = 0
    member_months = 0
    seen_patients = set()
    for a in DB["attributions"].values():
        team = DB["care_teams"].get(a["care_team_id"])
        if team is None or team["center_id"] != center_id:
            continue
        interval = active_interval_in_period(a, period)
        if interval is None:
            continue
        lo, hi = interval
        patient = DB["patients"].get(a["patient_id"])
        plan = DB["health_plans"].get(a["health_plan_id"])
        if patient is None or plan is None:
            continue
        days_active = (hi - lo).days + 1
        if variant == "chronological":
            mm = dec(1)
        else:
            mm = dec(days_active) / dim
        base = dec(plan["base_pmpm_cents"]) * dec(plan["risk_adjust_factor"]) * dec(patient["risk_score"])
        total += round_cents(base * mm * dec(plan["revenue_share_pct"]))
        if a["patient_id"] not in seen_patients:
            seen_patients.add(a["patient_id"])
            member_months += 1 if variant == "chronological" else 0
    if variant != "chronological":
        member_months = len(seen_patients)
    return member_months, total


def compute_total_cost(center_id, period):
    total = 0
    for c in DB["claims"].values():
        if c["center_id"] == center_id and c["service_month"] == period and c["status"] == "ADJUDICATED":
            total += c["adjudicated_amount_cents"]
    p_start = month_start(period).date()
    p_end = (month_end_exclusive(period) - timedelta(days=1)).date()
    for appt in DB["appointments"].values():
        team = DB["care_teams"].get(appt["care_team_id"])
        if team is None or team["center_id"] != center_id:
            continue
        if appt["status"] in ("COMPLETED", "COMPLETED_NO_SHOW"):
            d = parse_dt(appt["start_utc"]).date()
            if p_start <= d <= p_end and appt.get("cost_cents") is not None:
                total += appt["cost_cents"]
    for r in DB["rides"].values():
        if r["status"] in ("DELIVERED", "FAILED_NO_SHOW"):
            appt = DB["appointments"].get(r["appointment_id"])
            if appt is None:
                continue
            team = DB["care_teams"].get(appt["care_team_id"])
            if team is None or team["center_id"] != center_id:
                continue
            d = parse_dt(appt["start_utc"]).date()
            if p_start <= d <= p_end:
                total += RIDE_COST
    return total


def recompute_settlement_costs(s):
    s["total_cost_of_care_cents"] = compute_total_cost(s["center_id"], s["period_month"])
    if s.get("accrued_revenue_cents") is not None:
        s["contribution_cents"] = s["accrued_revenue_cents"] - s["total_cost_of_care_cents"]
    touch(s)


def compute_profitability_tier(center):
    if center["maturity_months"] < 12:
        return "RAMP"
    if center["cumulative_contribution_cents"] < 0:
        return "RAMP"
    if center["panel_fill_ratio"] < 0.75:
        return "BREAKEVEN"
    return "MATURE"


@app.route("/senior-care/monthly-settlements", methods=["POST"])
@roles("FinanceAnalyst")
def create_settlement():
    b = body()
    require_fields(b, ["center_id", "period_month"])
    center = DB["centers"].get(b["center_id"])
    pm = b["period_month"]
    if not (isinstance(pm, str) and len(pm) == 7 and pm[4] == "-"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "period_month must be YYYY-MM")
    try:
        month_start(pm)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "period_month must be YYYY-MM")
    if center is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "center_id does not reference an existing center")
    for s in DB["settlements"].values():
        if s["center_id"] == center["id"] and s["period_month"] == pm and s["status"] != "VOIDED":
            raise ApiError("ERR_DUPLICATE_SETTLEMENT", 409,
                           "A settlement already exists for (center_id, period_month)")
    s = register("settlements", {
        "center_id": center["id"],
        "period_month": pm,
        "member_months": 0,
        "accrued_revenue_cents": None,
        "total_cost_of_care_cents": 0,
        "contribution_cents": None,
        "status": "OPEN",
    })
    return success(s, 201)


@app.route("/senior-care/monthly-settlements", methods=["GET"])
@roles("FinanceAnalyst", "FinanceController")
def list_settlements():
    items = list(DB["settlements"].values())
    for param in ("center_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s[param] == v]
    return list_response(items)


@app.route("/senior-care/monthly-settlements/<settlementId>", methods=["GET"])
@roles("FinanceAnalyst", "FinanceController")
def get_settlement(settlementId):
    return success(get_or_404("settlements", settlementId), 200)


@app.route("/senior-care/monthly-settlements/<settlementId>/close-provisional", methods=["POST"])
@roles("FinanceAnalyst")
def close_provisional(settlementId):
    s = get_or_404("settlements", settlementId)
    b = body()
    center = DB["centers"].get(s["center_id"])
    if "expected_center_version" in b and b["expected_center_version"] is not None:
        ev = b["expected_center_version"]
        if isinstance(ev, bool) or not isinstance(ev, int):
            raise ApiError("ERR_INVALID_REQUEST", 400, "expected_center_version must be an integer")
        if center is not None and ev != center["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "expected_center_version does not match the center's current version")
    if s["status"] != "OPEN":
        raise ApiError("ERR_SETTLEMENT_NOT_OPEN", 409, "Settlement must be OPEN for this operation")
    if current_month() <= s["period_month"]:
        raise ApiError("ERR_PERIOD_STILL_OPEN", 409,
                       "Cannot close-provisional while the logical clock is still inside period_month")
    mm, accrued = compute_accrual(s["center_id"], s["period_month"], "chronological")
    s["member_months"] = mm
    s["accrued_revenue_cents"] = accrued
    s["total_cost_of_care_cents"] = compute_total_cost(s["center_id"], s["period_month"])
    s["contribution_cents"] = accrued - s["total_cost_of_care_cents"]
    s["status"] = "CLOSED_PROVISIONAL"
    touch(s)
    if center is not None:
        center["cumulative_contribution_cents"] += s["contribution_cents"]
        touch(center)
    return success(s, 200)


@app.route("/senior-care/monthly-settlements/<settlementId>/finalize", methods=["POST"])
@roles("FinanceController")
def finalize_settlement(settlementId):
    s = get_or_404("settlements", settlementId)
    if s["status"] != "CLOSED_PROVISIONAL":
        raise ApiError("ERR_SETTLEMENT_NOT_PROVISIONAL", 409, "Settlement must be CLOSED_PROVISIONAL to finalize")
    for c in DB["claims"].values():
        if c["center_id"] == s["center_id"] and c["service_month"] == s["period_month"] and c["status"] == "SUBMITTED":
            raise ApiError("ERR_CLAIMS_STILL_PENDING", 409, "SUBMITTED claims remain for the period at finalize")
    center = DB["centers"].get(s["center_id"])
    mm, accrued = compute_accrual(s["center_id"], s["period_month"], "forward")
    s["member_months"] = mm
    old_contribution = s["contribution_cents"]
    s["accrued_revenue_cents"] = accrued
    s["total_cost_of_care_cents"] = compute_total_cost(s["center_id"], s["period_month"])
    s["contribution_cents"] = accrued - s["total_cost_of_care_cents"]
    s["status"] = "FINALIZED"
    touch(s)
    for c in DB["claims"].values():
        if c["center_id"] == s["center_id"] and c["service_month"] == s["period_month"] and c["status"] == "ADJUDICATED":
            c["status"] = "SETTLED"
            touch(c)
    if center is not None:
        delta = s["contribution_cents"] - old_contribution
        center["cumulative_contribution_cents"] += delta
        center["maturity_months"] = max(0, months_elapsed(center["opened_on"], now_dt()))
        center["panel_fill_ratio"] = compute_panel_fill_ratio(center["id"])
        center["profitability_tier"] = compute_profitability_tier(center)
        touch(center)
    return success(s, 200)


@app.route("/senior-care/monthly-settlements/<settlementId>/void", methods=["POST"])
@roles("FinanceController")
def void_settlement(settlementId):
    s = get_or_404("settlements", settlementId)
    if s["status"] != "OPEN":
        raise ApiError("ERR_SETTLEMENT_NOT_OPEN", 409, "Settlement must be OPEN for this operation")
    for c in DB["claims"].values():
        if c["center_id"] == s["center_id"] and c["service_month"] == s["period_month"] and c["status"] == "ADJUDICATED":
            raise ApiError("ERR_CLAIMS_ALREADY_ADJUDICATED", 409, "ADJUDICATED claims exist for the period at void")
    s["status"] = "VOIDED"
    touch(s)
    return success(s, 200)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
