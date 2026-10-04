#!/usr/bin/env python3
"""Delivery Point Sequencing, Route Adjustment & Service Standards API.

In-memory Flask implementation per PRD.md. No seeding; store starts empty.
Logical clock default: 2026-09-01T00:00:00Z.
"""
import os
import re
import uuid
import random
import string
from copy import deepcopy
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK = {"now": datetime(2026, 9, 1, tzinfo=timezone.utc)}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "facilities": {},
    "units": {},
    "points": {},
    "carriers": {},
    "routes": {},
    "sequence_entries": {},
    "evaluations": {},
    "adjustments": {},
    "auxiliary": {},
    "coas": {},
    "holds": {},
    "rules": {},
    "queries": {},
    "scan_events": {},
    "inquiries": {},
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {
    "PlatformAdmin", "AddressManagementSpecialist", "RouteSupervisor",
    "Postmaster", "Carrier", "CustomerServiceRep", "ServiceStandardsAdmin",
}

FACILITY_TYPES = {"P_AND_DC", "S_AND_DC", "NDC", "ANEX"}
REGION_CLASSES = {"CONTIGUOUS", "NON_CONTIGUOUS"}
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
POINT_KINDS = {"RESIDENTIAL", "BUSINESS", "CENTRALIZED", "PO_BOX"}
POINT_RESTRICTIONS = {"NONE", "BUSINESS_ONLY_HOURS", "GATED_CODE_ON_FILE", "NO_SECURE_LOCATION"}
CARRIER_CLASSES = {"REGULAR", "CITY_ASSISTANT", "RURAL", "AUXILIARY"}
ROUTE_TYPES = {"CITY", "RURAL", "HIGHWAY_CONTRACT"}
DELIVERY_ORDER_GROUPS = {"PARK_LOOP", "MOUNTED", "WALKING", "DISMOUNT"}
EVAL_KINDS = {"FULL_COUNT", "MINI_SURVEY", "SPECIAL_INSPECTION"}
CONSULTATION_OUTCOMES = {"CONCURRED", "DISPUTED", "WAIVED"}
MOVE_KINDS = {"INDIVIDUAL", "FAMILY", "BUSINESS"}
MOVE_TYPES = {"PERMANENT", "TEMPORARY"}
MAIL_CLASSES = {"FIRST_CLASS", "PRIORITY", "GROUND_ADVANTAGE", "PERIODICALS", "MARKETING"}
SCAN_CODES = {"DELIVERED", "ATTEMPTED_NO_ACCESS", "VACANT_CONFIRMED", "FORWARDED", "HELD_AT_OFFICE", "REFUSED"}
HOLD_DISPOSITIONS = {"ACCUMULATE_DELIVER_ON_END", "CARRIER_PICKUP"}
INQUIRY_KINDS = {"MISSING_MAIL", "LATE_DELIVERY", "WRONG_DELIVERY", "HOLD_NOT_HONORED", "FORWARD_NOT_RECEIVED"}
INQUIRY_CHANNELS = {"PHONE", "WEB", "WALK_IN"}
RESOLUTION_CODES = {"FOUND_AND_DELIVERED", "SENDER_CONTACTED", "FORWARD_CONFIRMED", "NO_ERROR_FOUND"}

RE_FACILITY_CODE = re.compile(r"^[A-Z]{3}$")
RE_TIME = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
RE_STATE = re.compile(r"^[A-Z]{2}$")
RE_ZIP11 = re.compile(r"^[0-9]{11}$")
RE_EMPLOYEE = re.compile(r"^E[0-9]{7}$")
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Terminal states per entity kind for ERR_ALREADY_TERMINAL refinement
TERMINAL = {
    "point": {"DISCONTINUED"},
    "route": set(),  # SUSPENDED is transitional, not terminal
    "evaluation": {"CLOSED_ADOPTED", "CLOSED_REJECTED"},
    "adjustment": {"EFFECTIVE", "REJECTED", "WITHDRAWN"},
    "auxiliary": {"COMPLETED", "CURTAILED", "DENIED"},
    "coa": {"EXPIRED", "CANCELLED"},  # forwarding_status axis
    "hold": {"EXPIRED", "COMPLETED", "CANCELLED"},
    "inquiry": {"CLOSED_ABANDONED", "RESOLVED_FINAL"},
    "rule": {"RETIRED"},
}

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)

def err_forbidden(msg="Role not permitted for the endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)

def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)

def err_reference(msg="Referenced entity does not exist"):
    return ApiError("ERR_REFERENCE_NOT_FOUND", 422, msg)

def err_invalid_state(msg="Entity not in the required state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)

def err_already_terminal(msg="Entity is in a terminal state"):
    return ApiError("ERR_ALREADY_TERMINAL", 409, msg)

def err_stale(msg="Stale version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)

def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)

def err_duplicate(msg="Duplicate key"):
    return ApiError("ERR_DUPLICATE_KEY", 409, msg)

def err_uso(msg="Universal service obligation violation"):
    return ApiError("ERR_USO_VIOLATION", 422, msg)

def err_sod(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)

def err_cross(msg="Cross-entity state gate failed"):
    return ApiError("ERR_CROSS_ENTITY_STATE", 409, msg)

def err_temporal(msg="Temporal window violated"):
    return ApiError("ERR_TEMPORAL_WINDOW", 422, msg)

def err_window_overlap(msg="Overlapping window"):
    return ApiError("ERR_WINDOW_OVERLAP", 409, msg)

def err_sequence_invalid(msg="Sequence payload invalid"):
    return ApiError("ERR_SEQUENCE_INVALID", 422, msg)

def err_sequence_dup(msg="Duplicate line_of_travel_order in sequence payload"):
    return ApiError("ERR_SEQUENCE_DUPLICATE_POSITION", 409, msg)

def err_case_capacity(msg="Case capacity exceeded"):
    return ApiError("ERR_CASE_CAPACITY_EXCEEDED", 422, msg)

def err_range(msg="Numeric range violated"):
    return ApiError("ERR_RANGE_VIOLATION", 422, msg)

def err_overrun(msg="Overrun below threshold / vacancy threshold not met"):
    return ApiError("ERR_OVERRUN_BELOW_THRESHOLD", 422, msg)

def err_no_rule(msg="No service rule covers the query"):
    return ApiError("ERR_NO_SERVICE_RULE", 422, msg)

def err_rule_overlap(msg="Rule overlap conflict"):
    return ApiError("ERR_RULE_OVERLAP_CONFLICT", 409, msg)

def err_recollection(msg="Re-collection loop exhausted"):
    return ApiError("ERR_RECOLLECTION_EXHAUSTED", 409, msg)

def err_hold_active(msg="Active CARRIER_PICKUP hold blocks vacancy marking"):
    return ApiError("ERR_HOLD_ACTIVE", 409, msg)

def err_forward_active(msg="Active forwarding order blocks discontinuation"):
    return ApiError("ERR_FORWARD_ACTIVE", 409, msg)

def err_forward_overlap(msg="Another ACTIVE COA exists for the old address"):
    return ApiError("ERR_FORWARD_OVERLAP", 409, msg)

def err_hold_overlap(msg="Hold window overlaps an existing hold"):
    return ApiError("ERR_HOLD_OVERLAP", 409, msg)

def err_reopen_window(msg="Reopen window expired"):
    return ApiError("ERR_REOPEN_WINDOW_EXPIRED", 422, msg)

# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=22))


def _timestamp_now():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def ok(data, status=200, response_type="object", pagination=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _timestamp_now()}
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_response(exc):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _timestamp_now()},
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.http_status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(e)))

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def auth_user():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    return uid, role


def require_roles(*allowed):
    uid, role = auth_user()
    if role not in allowed:
        raise err_forbidden()
    return uid, role

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def now_iso():
    return _timestamp_now()


def current_dt():
    return CLOCK["now"]


def current_date():
    return CLOCK["now"].date()


def parse_date(s):
    if not isinstance(s, str) or not RE_DATE.match(s):
        raise err_invalid_request(f"Invalid date: {s}")
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise err_invalid_request(f"Invalid date: {s}")


def parse_datetime_iso(s):
    if not isinstance(s, str):
        raise err_invalid_request("Invalid datetime")
    txt = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(txt)
    except ValueError:
        raise err_invalid_request("Invalid datetime")


def get_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def new_record(extra=None, full_common=True):
    rec = {"id": new_id(), "created_at": now_iso()}
    if full_common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    if extra:
        rec.update(extra)
    return rec


def paginate(items):
    # items already filtered, sorted
    total = len(items)
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise err_invalid_request("Invalid pagination parameters")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit out of range")
    if offset < 0:
        raise err_invalid_request("offset out of range")
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total, "has_more": offset + limit < total}
    return page, meta


def list_response(items):
    items = sorted(items, key=lambda r: r["created_at"])
    page, meta = paginate(items)
    return ok(page, status=200, response_type="array", pagination=meta)

# ---------------------------------------------------------------------------
# Computed helpers
# ---------------------------------------------------------------------------
def compute_vacancy(point):
    if point["occupancy_status"] == "VACANT" and point.get("vacant_since_date"):
        vd = parse_date(point["vacant_since_date"])
        days = (current_date() - vd).days
    else:
        days = 0
    point["vacancy_days"] = days
    occ = point["occupancy_status"]
    point["is_deliverable"] = (occ in ("OCCUPIED", "SEASONAL")) or (
        occ == "VACANT" and days < 90
    )
    return point


def route_active_point_count(route_id):
    n = 0
    for p in DB["points"].values():
        if p.get("active_route_id") == route_id and p["occupancy_status"] in ("OCCUPIED", "SEASONAL"):
            n += 1
    return n


def refresh_route_counts(route_id):
    route = DB["routes"].get(route_id)
    if route:
        route["active_delivery_point_count"] = route_active_point_count(route_id)
    return route


def unit_active_route_count(unit_id):
    n = 0
    for r in DB["routes"].values():
        if r["delivery_unit_id"] == unit_id and r["status"] in ("STANDARD", "UNDER_EVALUATION", "UNDER_ADJUSTMENT"):
            n += 1
    return n


def refresh_unit_counts(unit_id):
    unit = DB["units"].get(unit_id)
    if unit:
        unit["active_route_count"] = unit_active_route_count(unit_id)
    return unit


def route_aux_relief(route_id):
    total = 0
    for a in DB["auxiliary"].values():
        if a["carrier_route_id"] == route_id and a["status"] in ("APPROVED", "ACTIVE"):
            total += a.get("scheduled_minutes") or 0
    return total


def refresh_aux_relief(route_id):
    route = DB["routes"].get(route_id)
    if route:
        route["auxiliary_relief_minutes"] = route_aux_relief(route_id)


def case_slots(order):
    letters = 1 + (order - 1) // 2
    flats = 1 + (order - 1) // 3
    return letters, flats


def renumber_route_entries(route_id):
    entries = [e for e in DB["sequence_entries"].values() if e["carrier_route_id"] == route_id]
    entries.sort(key=lambda e: e["line_of_travel_order"])
    for idx, e in enumerate(entries, start=1):
        e["line_of_travel_order"] = idx
        letters, flats = case_slots(idx)
        e["case_slot_letters"] = letters
        e["case_slot_flats"] = flats
        e["updated_at"] = now_iso()
        e["version"] += 1
    return entries


def unit_of_route(route):
    return DB["units"].get(route["delivery_unit_id"]) if route else None

# ---------------------------------------------------------------------------
# Nested lookup helpers (left-to-right path validation)
# ---------------------------------------------------------------------------
def get_unit_or_404(unit_id):
    u = DB["units"].get(unit_id)
    if not u:
        raise err_not_found("Delivery unit not found")
    return u


def get_point_or_404(point_id):
    p = DB["points"].get(point_id)
    if not p:
        raise err_not_found("Delivery point not found")
    return p


def get_route_or_404(route_id):
    r = DB["routes"].get(route_id)
    if not r:
        raise err_not_found("Route not found")
    return r


def get_carrier_or_404(carrier_id):
    c = DB["carriers"].get(carrier_id)
    if not c:
        raise err_not_found("Carrier not found")
    return c


def get_eval_or_404(eval_id):
    e = DB["evaluations"].get(eval_id)
    if not e:
        raise err_not_found("Evaluation not found")
    return e


def get_adj_or_404(adj_id):
    a = DB["adjustments"].get(adj_id)
    if not a:
        raise err_not_found("Adjustment not found")
    return a


def get_aux_or_404(aux_id):
    a = DB["auxiliary"].get(aux_id)
    if not a:
        raise err_not_found("Auxiliary assignment not found")
    return a


def get_coa_or_404(coa_id):
    c = DB["coas"].get(coa_id)
    if not c:
        raise err_not_found("Change of address not found")
    return c


def get_hold_or_404(hold_id):
    h = DB["holds"].get(hold_id)
    if not h:
        raise err_not_found("Hold not found")
    return h


def get_rule_or_404(rule_id):
    r = DB["rules"].get(rule_id)
    if not r:
        raise err_not_found("Service standard rule not found")
    return r


def get_facility_or_404(facility_id):
    f = DB["facilities"].get(facility_id)
    if not f:
        raise err_not_found("Processing facility not found")
    return f


def get_query_or_404(query_id):
    q = DB["queries"].get(query_id)
    if not q:
        raise err_not_found("Service standard query not found")
    return q


def get_inquiry_or_404(inquiry_id):
    i = DB["inquiries"].get(inquiry_id)
    if not i:
        raise err_not_found("Inquiry not found")
    return i


def get_scan_or_404(event_id):
    s = DB["scan_events"].get(event_id)
    if not s:
        raise err_not_found("Scan event not found")
    return s


def get_entry_or_404(entry_id):
    e = DB["sequence_entries"].get(entry_id)
    if not e:
        raise err_not_found("Sequence entry not found")
    return e


def require_child(parent_val, child, key, what="resource"):
    if child[key] != parent_val:
        raise err_not_found(f"{what} not found in parent scope")

# ---------------------------------------------------------------------------
# Transition precondition helper (terminal refinement)
# ---------------------------------------------------------------------------
def check_state(kind, rec, allowed_states, state_field="status"):
    cur = rec[state_field]
    if cur in TERMINAL[kind]:
        raise err_already_terminal(f"{kind} is in terminal state {cur}")
    if cur not in allowed_states:
        raise err_invalid_state(f"{kind} in state {cur}; required one of {sorted(allowed_states)}")

# ===========================================================================
# CLOCK ENDPOINT
# ===========================================================================
def coa_expiry_date(coa):
    if coa["move_type"] == "TEMPORARY":
        return parse_date(coa["end_date"])
    # PERMANENT: 12 months after begin_date
    begin = parse_date(coa["begin_date"])
    year = begin.year + 1
    month = begin.month
    day = begin.day
    try:
        return date(year, month, day)
    except ValueError:
        # Feb 29 case
        return date(year, month, 28)


def fire_clock_transitions():
    """Run all date-driven transitions. Returns count of transitions fired."""
    fired = 0
    today = current_date()

    # Rule flips: SCHEDULED -> ACTIVE once effective_from <= today
    for rule in DB["rules"].values():
        if rule["status"] == "SCHEDULED" and parse_date(rule["effective_from"]) <= today:
            rule["status"] = "ACTIVE"
            touch(rule)
            fired += 1

    # COA: PENDING -> ACTIVE on begin_date
    for coa in DB["coas"].values():
        if coa["forwarding_status"] == "PENDING" and parse_date(coa["begin_date"]) <= today:
            if coa["validation_status"] == "VERIFIED":
                # check overlap
                ok_to_activate = True
                for other in DB["coas"].values():
                    if other["id"] == coa["id"]:
                        continue
                    if other["old_delivery_point_id"] == coa["old_delivery_point_id"] and other["forwarding_status"] == "ACTIVE":
                        if coa.get("supersedes_coa_id") == other["id"]:
                            other["forwarding_status"] = "CANCELLED"
                            touch(other)
                            fired += 1
                        else:
                            ok_to_activate = False
                if ok_to_activate:
                    coa["forwarding_status"] = "ACTIVE"
                    touch(coa)
                    fired += 1

    # COA: ACTIVE -> EXPIRED when date > end_date (temporary) or 12mo (permanent)
    for coa in DB["coas"].values():
        if coa["forwarding_status"] == "ACTIVE":
            exp = coa_expiry_date(coa)
            if exp is not None and today > exp:
                coa["forwarding_status"] = "EXPIRED"
                touch(coa)
                fired += 1

    # HoldMail: SCHEDULED -> ACTIVE on hold_start_date
    for hold in DB["holds"].values():
        if hold["status"] == "SCHEDULED" and parse_date(hold["hold_start_date"]) <= today:
            # overlap check vs other holds on the same point
            overlap = False
            for other in DB["holds"].values():
                if other["id"] == hold["id"]:
                    continue
                if other["delivery_point_id"] != hold["delivery_point_id"]:
                    continue
                if other["status"] not in ("SCHEDULED", "ACTIVE"):
                    continue
                # half-open [start, end+1)
                a_start = parse_date(hold["hold_start_date"])
                a_end = parse_date(hold["hold_end_date"]) + timedelta(days=1)
                b_start = parse_date(other["hold_start_date"])
                b_end = parse_date(other["hold_end_date"]) + timedelta(days=1)
                if a_start < b_end and b_start < a_end:
                    overlap = True
                    break
            if not overlap:
                hold["status"] = "ACTIVE"
                touch(hold)
                fired += 1

    # HoldMail: ACTIVE -> EXPIRED once date > hold_end_date
    for hold in DB["holds"].values():
        if hold["status"] == "ACTIVE" and parse_date(hold["hold_end_date"]) < today:
            hold["status"] = "EXPIRED"
            touch(hold)
            fired += 1

    # Adjustment: APPROVED -> EFFECTIVE on effective_date
    for adj in DB["adjustments"].values():
        if adj["status"] == "APPROVED" and parse_date(adj["effective_date"]) <= today:
            fire_adjustment_effective(adj)
            fired += 1

    # Auxiliary: APPROVED -> ACTIVE on service_date
    for aux in DB["auxiliary"].values():
        if aux["status"] == "APPROVED" and parse_date(aux["service_date"]) <= today:
            aux["status"] = "ACTIVE"
            touch(aux)
            fired += 1

    # Inquiry auto-abandon: 30 days without status change
    for inq in DB["inquiries"].values():
        if inq["status"] in ("OPEN", "INVESTIGATING", "RESOLVED"):
            last_change = parse_datetime_iso(inq.get("last_status_change_at") or inq["created_at"])
            if (current_dt() - last_change).total_seconds() >= 30 * 86400:
                inq["status"] = "CLOSED_ABANDONED"
                touch(inq)
                inq["last_status_change_at"] = inq["updated_at"]
                fired += 1

    # Vacancy recomputation
    for point in DB["points"].values():
        compute_vacancy(point)

    return fired


def fire_adjustment_effective(adj):
    """Full adopt cascade for APPROVED -> EFFECTIVE."""
    evaluation = DB["evaluations"][adj["route_evaluation_id"]]
    route = DB["routes"][evaluation["carrier_route_id"]]
    unit_id = route["delivery_unit_id"]

    # Apply point transfers
    donor_route_id = route["id"]
    receiving_routes = set()
    for move in adj.get("points_transferred_out") or []:
        point = DB["points"][move["delivery_point_id"]]
        to_route_id = move["to_route_id"]
        point["active_route_id"] = to_route_id
        # remove sequence entry from donor
        entry = next((e for e in DB["sequence_entries"].values()
                      if e["carrier_route_id"] == donor_route_id and e["delivery_point_id"] == point["id"]), None)
        prior_order = entry["line_of_travel_order"] if entry else 0
        point_created = point["created_at"]
        if entry:
            del DB["sequence_entries"][entry["id"]]
        receiving_routes.add((to_route_id, point["id"], prior_order, point_created))
        point["updated_at"] = now_iso()
        point["version"] += 1

    # Renumber donor route first
    renumber_route_entries(donor_route_id)

    # Group incoming points per receiving route, append in ascending prior order
    per_recv = {}
    for to_route_id, point_id, prior_order, created in receiving_routes:
        per_recv.setdefault(to_route_id, []).append((prior_order, created, point_id))
    for recv_route_id, items in per_recv.items():
        items.sort(key=lambda t: (t[0], t[1]))
        existing = [e for e in DB["sequence_entries"].values() if e["carrier_route_id"] == recv_route_id]
        next_order = max([e["line_of_travel_order"] for e in existing], default=0)
        for _, _, pid in items:
            next_order += 1
            letters, flats = case_slots(next_order)
            entry = new_record({
                "carrier_route_id": recv_route_id,
                "delivery_point_id": pid,
                "line_of_travel_order": next_order,
                "case_slot_letters": letters,
                "case_slot_flats": flats,
                "delivery_order_group": "PARK_LOOP",
            })
            DB["sequence_entries"][entry["id"]] = entry
        renumber_route_entries(recv_route_id)

    # Update counts on all affected routes
    affected = {donor_route_id} | {r for r, _, _, _ in receiving_routes}
    for rid in affected:
        refresh_route_counts(rid)
        r = DB["routes"].get(rid)
        if r:
            r["updated_at"] = now_iso()
            r["version"] += 1

    # Route status: UNDER_ADJUSTMENT -> STANDARD, adopt minutes
    route["current_evaluated_minutes"] = adj["proposed_evaluated_minutes"]
    route["under_evaluation_since"] = None
    route["status"] = "STANDARD"
    touch(route)

    # Evaluation closes adopted
    evaluation["status"] = "CLOSED_ADOPTED"
    touch(evaluation)

    adj["status"] = "EFFECTIVE"
    touch(adj)


@app.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = require_roles("PlatformAdmin")
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not to_iso:
        raise err_invalid_request("to_iso8601 is required")
    new_dt = parse_datetime_iso(to_iso)
    CLOCK["now"] = new_dt
    fired = fire_clock_transitions()
    return ok({"current_utc": new_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{new_dt.microsecond // 1000:03d}Z",
               "transitions_fired": fired}, status=200)

# ===========================================================================
# PROCESSING FACILITIES
# ===========================================================================
@app.route("/api/processing-facilities", methods=["POST"])
def create_facility():
    uid, role = require_roles("ServiceStandardsAdmin")
    body = get_body()
    code = body.get("facility_code")
    ftype = body.get("facility_type")
    region = body.get("region_class")
    cutoff = body.get("dispatch_cutoff_local")
    opdays = body.get("operating_days")
    if not code or not isinstance(code, str) or not RE_FACILITY_CODE.match(code):
        raise err_invalid_request("facility_code must be 3 uppercase letters")
    if ftype not in FACILITY_TYPES:
        raise err_invalid_request("invalid facility_type")
    if region not in REGION_CLASSES:
        raise err_invalid_request("invalid region_class")
    if not cutoff or not isinstance(cutoff, str) or not RE_TIME.match(cutoff):
        raise err_invalid_request("invalid dispatch_cutoff_local")
    if not isinstance(opdays, list) or not opdays:
        raise err_invalid_request("operating_days must be non-empty")
    for d in opdays:
        if d not in WEEKDAYS:
            raise err_invalid_request("invalid operating_days member")
    # uniqueness
    for f in DB["facilities"].values():
        if f["facility_code"] == code:
            raise err_duplicate("facility_code already exists")
    rec = new_record({
        "facility_code": code,
        "facility_type": ftype,
        "region_class": region,
        "dispatch_cutoff_local": cutoff,
        "operating_days": list(opdays),
        "status": "ACTIVE",
    })
    DB["facilities"][rec["id"]] = rec
    return ok(rec, status=201)


@app.route("/api/processing-facilities/<facilityId>", methods=["GET"])
def get_facility(facilityId):
    uid, role = require_roles("ServiceStandardsAdmin", "PlatformAdmin", "RouteSupervisor", "Postmaster", "CustomerServiceRep")
    f = get_facility_or_404(facilityId)
    return ok(deepcopy(f))


@app.route("/api/processing-facilities", methods=["GET"])
def list_facilities():
    uid, role = require_roles("ServiceStandardsAdmin", "PlatformAdmin", "RouteSupervisor", "Postmaster", "CustomerServiceRep")
    items = list(DB["facilities"].values())
    region = request.args.get("region_class")
    status = request.args.get("status")
    if region:
        items = [f for f in items if f["region_class"] == region]
    if status:
        items = [f for f in items if f["status"] == status]
    return list_response([deepcopy(f) for f in items])


# ---------------------------------------------------------------------------
# ServiceStandardRule
# ---------------------------------------------------------------------------
def rules_overlap(a_from, a_to, b_from, b_to):
    """Half-open conflict: end-adjacency (a_to == b_from) is a CONFLICT, must be <."""
    a_to_cmp = a_to if a_to is not None else date.max
    b_to_cmp = b_to if b_to is not None else date.max
    # overlap exists when a_from <= b_to_cmp AND b_from <= a_to_cmp
    # but end-adjacency == conflict, so inclusive comparison
    return a_from <= b_to_cmp and b_from <= a_to_cmp


@app.route("/api/processing-facilities/<facilityId>/service-standard-rules", methods=["POST"])
def create_rule(facilityId):
    uid, role = require_roles("ServiceStandardsAdmin")
    origin = get_facility_or_404(facilityId)
    body = get_body()

    dest_id = body.get("dest_facility_id")
    mail_class = body.get("mail_class")
    service_days = body.get("service_days")
    nc_extra = body.get("non_contiguous_extra_days", 2)
    eff_from_s = body.get("effective_from")
    eff_to_s = body.get("effective_to")
    expected_version = body.get("expected_facility_version")

    # existence of body FKs (priority 4)
    if not dest_id:
        raise err_invalid_request("dest_facility_id required")
    dest = DB["facilities"].get(dest_id)
    if not dest:
        raise err_reference("dest_facility_id does not exist")

    # OCC check (priority 6)
    if expected_version is None:
        raise err_invalid_request("expected_facility_version required")
    if expected_version != origin["version"]:
        raise err_stale("facility version mismatch")

    # cross-entity state (priority 9): both facilities must be ACTIVE
    if origin["status"] != "ACTIVE" or dest["status"] != "ACTIVE":
        raise err_cross("both facilities must be ACTIVE")
    if dest_id == facilityId:
        raise err_invalid_request("dest_facility_id must differ from origin")

    # enum & range
    if mail_class not in MAIL_CLASSES:
        raise err_invalid_request("invalid mail_class")
    if not isinstance(service_days, int) or service_days < 1 or service_days > 7:
        raise err_range("service_days must be 1..7")
    if not isinstance(nc_extra, int) or nc_extra < 0 or nc_extra > 10:
        raise err_range("non_contiguous_extra_days must be 0..10")

    eff_from = parse_date(eff_from_s) if eff_from_s else None
    if eff_from is None:
        raise err_invalid_request("effective_from required")
    eff_to = None
    if eff_to_s:
        eff_to = parse_date(eff_to_s)
        if eff_to < eff_from:
            raise err_temporal("effective_to must be >= effective_from")

    # overlap check (priority 11)
    for rule in DB["rules"].values():
        if rule["origin_facility_id"] == facilityId and rule["dest_facility_id"] == dest_id and rule["mail_class"] == mail_class:
            if rule["status"] == "RETIRED":
                continue
            r_from = parse_date(rule["effective_from"])
            r_to = parse_date(rule["effective_to"]) if rule.get("effective_to") else None
            if rules_overlap(eff_from, eff_to, r_from, r_to):
                raise err_window_overlap("rule window overlap")

    status = "ACTIVE" if eff_from <= current_date() else "SCHEDULED"
    rec = new_record({
        "origin_facility_id": facilityId,
        "dest_facility_id": dest_id,
        "mail_class": mail_class,
        "service_days": service_days,
        "non_contiguous_extra_days": nc_extra,
        "effective_from": eff_from_s,
        "effective_to": eff_to_s,
        "status": status,
    })
    DB["rules"][rec["id"]] = rec
    touch(origin)
    return ok(rec, status=201)


@app.route("/api/processing-facilities/<facilityId>/service-standard-rules", methods=["GET"])
def list_rules_for_facility(facilityId):
    uid, role = require_roles("ServiceStandardsAdmin", "PlatformAdmin", "RouteSupervisor", "Postmaster", "CustomerServiceRep")
    get_facility_or_404(facilityId)
    items = [r for r in DB["rules"].values() if r["origin_facility_id"] == facilityId]
    for k in ("mail_class", "status", "origin_facility_id", "dest_facility_id"):
        v = request.args.get(k)
        if v:
            items = [r for r in items if r.get(k) == v]
    return list_response([deepcopy(r) for r in items])


@app.route("/api/processing-facilities/<facilityId>/service-standard-rules/<ruleId>", methods=["GET"])
def get_rule_scoped(facilityId, ruleId):
    uid, role = require_roles("ServiceStandardsAdmin", "PlatformAdmin", "RouteSupervisor", "Postmaster", "CustomerServiceRep")
    get_facility_or_404(facilityId)
    rule = get_rule_or_404(ruleId)
    if rule["origin_facility_id"] != facilityId:
        raise err_not_found("rule not in facility scope")
    return ok(deepcopy(rule))


@app.route("/api/service-standard-rules/<ruleId>/retire", methods=["POST"])
def retire_rule(ruleId):
    uid, role = require_roles("ServiceStandardsAdmin")
    rule = get_rule_or_404(ruleId)
    if rule["status"] == "RETIRED":
        raise err_already_terminal("rule already retired")
    if rule["status"] != "ACTIVE":
        raise err_invalid_state("only ACTIVE rules may be retired")
    today = current_date()
    rule["effective_to"] = (today - timedelta(days=1)).isoformat()
    rule["status"] = "RETIRED"
    touch(rule)
    return ok(deepcopy(rule))


@app.route("/api/service-standard-rules", methods=["GET"])
def list_rules_flat():
    uid, role = require_roles("ServiceStandardsAdmin", "PlatformAdmin", "RouteSupervisor", "Postmaster", "CustomerServiceRep")
    items = list(DB["rules"].values())
    for k in ("origin_facility_id", "dest_facility_id", "mail_class", "status"):
        v = request.args.get(k)
        if v:
            items = [r for r in items if r.get(k) == v]
    return list_response([deepcopy(r) for r in items])


@app.route("/api/service-standard-rules/<ruleId>", methods=["GET"])
def get_rule_flat(ruleId):
    uid, role = require_roles("ServiceStandardsAdmin", "PlatformAdmin", "RouteSupervisor", "Postmaster", "CustomerServiceRep")
    rule = get_rule_or_404(ruleId)
    return ok(deepcopy(rule))


# ---------------------------------------------------------------------------
# ServiceStandardQuery
# ---------------------------------------------------------------------------
def compute_service_query(origin, dest, mail_class, acceptance_date_s, acceptance_time_local):
    acc_date = parse_date(acceptance_date_s)
    # rule selection
    matches = []
    for r in DB["rules"].values():
        if r["origin_facility_id"] != origin["id"]:
            continue
        if r["dest_facility_id"] != dest["id"]:
            continue
        if r["mail_class"] != mail_class:
            continue
        if r["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        r_from = parse_date(r["effective_from"])
        r_to = parse_date(r["effective_to"]) if r.get("effective_to") else None
        if r_from > acc_date:
            continue
        if r_to is not None and r_to < acc_date:
            continue
        matches.append(r)
    if not matches:
        raise err_no_rule("no covering rule")
    if len(matches) > 1:
        raise err_rule_overlap("multiple covering rules")
    rule = matches[0]

    # variant
    variant = "NON_CONTIGUOUS" if (origin["region_class"] == "NON_CONTIGUOUS" or dest["region_class"] == "NON_CONTIGUOUS") else "CONTIGUOUS"
    days = rule["service_days"] + (rule["non_contiguous_extra_days"] if variant == "NON_CONTIGUOUS" else 0)

    # cutoff handling
    if acceptance_time_local > origin["dispatch_cutoff_local"]:
        acc_date = acc_date + timedelta(days=1)
        while True:
            wd = WEEKDAYS[acc_date.weekday()]
            if wd in origin["operating_days"]:
                break
            acc_date = acc_date + timedelta(days=1)

    # roll forward; the (possibly advanced) acceptance day counts as the first
    # service day when it is a counting day
    remaining = days
    cur = acc_date
    while True:
        wd = WEEKDAYS[cur.weekday()]
        is_sunday = (cur.weekday() == 6)
        counts = wd in origin["operating_days"]
        if is_sunday:
            if not (mail_class == "PRIORITY" and variant == "CONTIGUOUS"):
                counts = False
        if counts:
            remaining -= 1
            if remaining == 0:
                break
        cur = cur + timedelta(days=1)
    committed = cur
    return committed, days, variant


@app.route("/api/service-standard-queries", methods=["POST"])
def create_query():
    uid, role = require_roles("ServiceStandardsAdmin", "CustomerServiceRep", "RouteSupervisor", "Postmaster", "PlatformAdmin")
    body = get_body()
    origin_id = body.get("origin_facility_id")
    dest_id = body.get("dest_facility_id")
    mail_class = body.get("mail_class")
    acc_date = body.get("acceptance_date")
    acc_time = body.get("acceptance_time_local")
    if not origin_id or origin_id not in DB["facilities"]:
        raise err_reference("origin_facility_id does not exist")
    if not dest_id or dest_id not in DB["facilities"]:
        raise err_reference("dest_facility_id does not exist")
    origin = DB["facilities"][origin_id]
    dest = DB["facilities"][dest_id]
    if mail_class not in MAIL_CLASSES:
        raise err_invalid_request("invalid mail_class")
    if not acc_date:
        raise err_invalid_request("acceptance_date required")
    if not acc_time or not isinstance(acc_time, str) or not RE_TIME.match(acc_time):
        raise err_invalid_request("invalid acceptance_time_local")
    committed, days, variant = compute_service_query(origin, dest, mail_class, acc_date, acc_time)
    rec = {"id": new_id(), "created_at": now_iso(),
           "origin_facility_id": origin_id,
           "dest_facility_id": dest_id,
           "mail_class": mail_class,
           "acceptance_date": acc_date,
           "acceptance_time_local": acc_time,
           "committed_delivery_date": committed.isoformat(),
           "committed_service_days": days,
           "variant_used": variant}
    DB["queries"][rec["id"]] = rec
    return ok(deepcopy(rec), status=201)


@app.route("/api/service-standard-queries/<queryId>", methods=["GET"])
def get_query(queryId):
    uid, role = require_roles("ServiceStandardsAdmin", "CustomerServiceRep", "RouteSupervisor", "Postmaster", "PlatformAdmin")
    q = get_query_or_404(queryId)
    return ok(deepcopy(q))


@app.route("/api/service-standard-queries", methods=["GET"])
def list_queries():
    uid, role = require_roles("ServiceStandardsAdmin", "CustomerServiceRep", "RouteSupervisor", "Postmaster", "PlatformAdmin")
    items = list(DB["queries"].values())
    for k in ("origin_facility_id", "dest_facility_id", "mail_class"):
        v = request.args.get(k)
        if v:
            items = [q for q in items if q.get(k) == v]
    return list_response([deepcopy(q) for q in items])


# ===========================================================================
# DELIVERY UNIT
# ===========================================================================
@app.route("/api/delivery-units", methods=["POST"])
def create_unit():
    uid, role = require_roles("PlatformAdmin")
    body = get_body()
    code = body.get("unit_code")
    name = body.get("office_name")
    fac_id = body.get("delivery_office_facility_id")
    slots = body.get("case_slot_count_per_route")
    target = body.get("scan_compliance_target", 0.98)
    if not code or not isinstance(code, str):
        raise err_invalid_request("unit_code required")
    if not name or not isinstance(name, str):
        raise err_invalid_request("office_name required")
    if not fac_id:
        raise err_invalid_request("delivery_office_facility_id required")
    fac = DB["facilities"].get(fac_id)
    if not fac:
        raise err_reference("delivery_office_facility_id does not exist")
    if fac["status"] != "ACTIVE":
        raise err_cross("referenced facility not ACTIVE")
    if not isinstance(slots, int) or slots < 4 or slots > 1000:
        raise err_range("case_slot_count_per_route must be 4..1000")
    try:
        target_f = float(target)
    except (TypeError, ValueError):
        raise err_range("scan_compliance_target must be a number")
    if target_f < 0.5 or target_f > 1.0:
        raise err_range("scan_compliance_target must be 0.5..1.0")
    target_4dp = float(Decimal(str(target_f)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    for u in DB["units"].values():
        if u["unit_code"] == code:
            raise err_duplicate("unit_code already exists")
    rec = new_record({
        "unit_code": code,
        "office_name": name,
        "delivery_office_facility_id": fac_id,
        "case_slot_count_per_route": slots,
        "universal_service_obligation": True,
        "scan_compliance_target": target_4dp,
        "active_route_count": 0,
    })
    DB["units"][rec["id"]] = rec
    return ok(rec, status=201)


@app.route("/api/delivery-units/<unitId>", methods=["GET"])
def get_unit(unitId):
    uid, role = require_roles("PlatformAdmin", "Postmaster", "RouteSupervisor", "AddressManagementSpecialist", "CustomerServiceRep", "Carrier")
    u = get_unit_or_404(unitId)
    refresh_unit_counts(unitId)
    return ok(deepcopy(u))


@app.route("/api/delivery-units", methods=["GET"])
def list_units():
    uid, role = require_roles("PlatformAdmin", "Postmaster", "RouteSupervisor", "AddressManagementSpecialist", "CustomerServiceRep")
    items = list(DB["units"].values())
    fac = request.args.get("delivery_office_facility_id")
    if fac:
        items = [u for u in items if u["delivery_office_facility_id"] == fac]
    for u in items:
        refresh_unit_counts(u["id"])
    return list_response([deepcopy(u) for u in items])


# ===========================================================================
# DELIVERY POINT
# ===========================================================================
def point_public(point):
    compute_vacancy(point)
    return deepcopy(point)


@app.route("/api/delivery-units/<unitId>/delivery-points", methods=["POST"])
def create_point(unitId):
    uid, role = require_roles("AddressManagementSpecialist")
    unit = get_unit_or_404(unitId)
    body = get_body()
    addr = body.get("address_line1")
    city = body.get("city")
    state_code = body.get("state_code")
    zip11 = body.get("zip11")
    kind = body.get("point_kind")
    restriction = body.get("delivery_restriction", "NONE")
    if not addr or not isinstance(addr, str):
        raise err_invalid_request("address_line1 required")
    if not city or not isinstance(city, str):
        raise err_invalid_request("city required")
    if not state_code or not RE_STATE.match(state_code or ""):
        raise err_invalid_request("state_code must be 2 uppercase letters")
    if not zip11 or not RE_ZIP11.match(zip11 or ""):
        raise err_invalid_request("zip11 must be 11 digits")
    if kind not in POINT_KINDS:
        raise err_invalid_request("invalid point_kind")
    if restriction not in POINT_RESTRICTIONS:
        raise err_invalid_request("invalid delivery_restriction")
    for p in DB["points"].values():
        if p["zip11"] == zip11:
            raise err_duplicate("zip11 already exists")
    rec = new_record({
        "delivery_unit_id": unitId,
        "active_route_id": None,
        "address_line1": addr,
        "city": city,
        "state_code": state_code,
        "zip11": zip11,
        "point_kind": kind,
        "occupancy_status": "UNDER_CONSTRUCTION",
        "vacant_since_date": None,
        "vacancy_days": 0,
        "is_deliverable": False,
        "delivery_restriction": restriction,
    })
    DB["points"][rec["id"]] = rec
    return ok(deepcopy(rec), status=201)


@app.route("/api/delivery-units/<unitId>/delivery-points/<pointId>", methods=["GET"])
def get_point_nested(unitId, pointId):
    uid, role = require_roles("AddressManagementSpecialist", "RouteSupervisor", "Postmaster", "CustomerServiceRep", "Carrier", "PlatformAdmin")
    get_unit_or_404(unitId)
    p = get_point_or_404(pointId)
    require_child(unitId, p, "delivery_unit_id", "Delivery point")
    return ok(point_public(p))


@app.route("/api/delivery-units/<unitId>/delivery-points", methods=["GET"])
def list_points_nested(unitId):
    uid, role = require_roles("AddressManagementSpecialist", "RouteSupervisor", "Postmaster", "CustomerServiceRep", "Carrier", "PlatformAdmin")
    get_unit_or_404(unitId)
    items = [p for p in DB["points"].values() if p["delivery_unit_id"] == unitId]
    occ = request.args.get("occupancy_status")
    route_id = request.args.get("active_route_id")
    if occ:
        items = [p for p in items if p["occupancy_status"] == occ]
    if route_id:
        items = [p for p in items if p.get("active_route_id") == route_id]
    is_del = request.args.get("is_deliverable")
    if is_del is not None and is_del != "":
        want = is_del.lower() in ("true", "1", "yes")
        for p in items:
            compute_vacancy(p)
        items = [p for p in items if p["is_deliverable"] == want]
    else:
        for p in items:
            compute_vacancy(p)
    return list_response([deepcopy(p) for p in items])


@app.route("/api/delivery-units/<unitId>/delivery-points/<pointId>/activate", methods=["POST"])
def activate_point(unitId, pointId):
    uid, role = require_roles("AddressManagementSpecialist")
    unit = get_unit_or_404(unitId)
    p = get_point_or_404(pointId)
    require_child(unitId, p, "delivery_unit_id", "Delivery point")
    body = get_body()
    route_id = body.get("route_id")
    if not route_id:
        raise err_invalid_request("route_id required")
    route = DB["routes"].get(route_id)
    if not route:
        raise err_reference("route_id does not exist")
    if route["delivery_unit_id"] != unitId:
        raise err_invalid_request("route does not belong to this unit")
    if p["occupancy_status"] == "DISCONTINUED":
        raise err_already_terminal("point discontinued")
    if p["occupancy_status"] != "UNDER_CONSTRUCTION":
        raise err_invalid_state("point must be UNDER_CONSTRUCTION")
    p["occupancy_status"] = "OCCUPIED"
    p["active_route_id"] = route_id
    touch(p)
    # append sequence entry
    existing = [e for e in DB["sequence_entries"].values() if e["carrier_route_id"] == route_id]
    next_order = max([e["line_of_travel_order"] for e in existing], default=0) + 1
    letters, flats = case_slots(next_order)
    unit_s = unit["case_slot_count_per_route"]
    if letters > unit_s or flats > unit_s:
        # roll back point mutation
        p["occupancy_status"] = "UNDER_CONSTRUCTION"
        p["active_route_id"] = None
        p["version"] -= 1
        raise err_case_capacity("case capacity exceeded on activation")
    entry = new_record({
        "carrier_route_id": route_id,
        "delivery_point_id": pointId,
        "line_of_travel_order": next_order,
        "case_slot_letters": letters,
        "case_slot_flats": flats,
        "delivery_order_group": "PARK_LOOP",
    })
    DB["sequence_entries"][entry["id"]] = entry
    refresh_route_counts(route_id)
    return ok(point_public(p))


@app.route("/api/delivery-units/<unitId>/delivery-points/<pointId>/mark-vacant", methods=["POST"])
def mark_vacant(unitId, pointId):
    uid, role = require_roles("Carrier")
    get_unit_or_404(unitId)
    p = get_point_or_404(pointId)
    require_child(unitId, p, "delivery_unit_id", "Delivery point")
    if p["occupancy_status"] == "DISCONTINUED":
        raise err_already_terminal("point discontinued")
    if p["occupancy_status"] != "OCCUPIED":
        raise err_invalid_state("point must be OCCUPIED")
    # active CARRIER_PICKUP hold blocks
    for h in DB["holds"].values():
        if h["delivery_point_id"] == pointId and h["status"] == "ACTIVE" and h["disposition"] == "CARRIER_PICKUP":
            raise err_hold_active("active CARRIER_PICKUP hold present")
    p["occupancy_status"] = "VACANT"
    p["vacant_since_date"] = current_date().isoformat()
    touch(p)
    if p.get("active_route_id"):
        refresh_route_counts(p["active_route_id"])
    compute_vacancy(p)
    return ok(point_public(p))


@app.route("/api/delivery-units/<unitId>/delivery-points/<pointId>/mark-occupied", methods=["POST"])
def mark_occupied(unitId, pointId):
    uid, role = require_roles("AddressManagementSpecialist")
    get_unit_or_404(unitId)
    p = get_point_or_404(pointId)
    require_child(unitId, p, "delivery_unit_id", "Delivery point")
    if p["occupancy_status"] == "DISCONTINUED":
        raise err_already_terminal("point discontinued")
    if p["occupancy_status"] not in ("VACANT", "SEASONAL"):
        raise err_invalid_state("point must be VACANT or SEASONAL")
    was_vacant = p["occupancy_status"] == "VACANT"
    compute_vacancy(p)
    if was_vacant and p["vacancy_days"] >= 90:
        # flag any INITIATED evaluation on the route
        if p.get("active_route_id"):
            for ev in DB["evaluations"].values():
                if ev["carrier_route_id"] == p["active_route_id"] and ev["status"] == "INITIATED":
                    ev["recount_note"] = True
    p["occupancy_status"] = "OCCUPIED"
    p["vacant_since_date"] = None
    touch(p)
    if was_vacant and p.get("active_route_id"):
        refresh_route_counts(p["active_route_id"])
    compute_vacancy(p)
    return ok(point_public(p))


@app.route("/api/delivery-units/<unitId>/delivery-points/<pointId>/mark-seasonal", methods=["POST"])
def mark_seasonal(unitId, pointId):
    uid, role = require_roles("AddressManagementSpecialist")
    get_unit_or_404(unitId)
    p = get_point_or_404(pointId)
    require_child(unitId, p, "delivery_unit_id", "Delivery point")
    if p["occupancy_status"] == "DISCONTINUED":
        raise err_already_terminal("point discontinued")
    if p["occupancy_status"] != "OCCUPIED":
        raise err_invalid_state("point must be OCCUPIED")
    p["occupancy_status"] = "SEASONAL"
    touch(p)
    compute_vacancy(p)
    return ok(point_public(p))


@app.route("/api/delivery-units/<unitId>/delivery-points/<pointId>/discontinue", methods=["POST"])
def discontinue_point(unitId, pointId):
    uid, role = require_roles("AddressManagementSpecialist")
    get_unit_or_404(unitId)
    p = get_point_or_404(pointId)
    require_child(unitId, p, "delivery_unit_id", "Delivery point")
    if p["occupancy_status"] == "DISCONTINUED":
        raise err_already_terminal("point already discontinued")
    if p["occupancy_status"] != "VACANT":
        raise err_invalid_state("point must be VACANT")
    # active COA blocks
    for c in DB["coas"].values():
        if c["old_delivery_point_id"] == pointId and c["forwarding_status"] == "ACTIVE":
            raise err_forward_active("active COA on point")
    compute_vacancy(p)
    if p["vacancy_days"] < 90:
        raise err_overrun("vacancy_days must be >= 90")
    p["occupancy_status"] = "DISCONTINUED"
    touch(p)
    # remove sequence entry, renumber
    route_id = p.get("active_route_id")
    if route_id:
        entry = next((e for e in DB["sequence_entries"].values()
                      if e["carrier_route_id"] == route_id and e["delivery_point_id"] == pointId), None)
        if entry:
            del DB["sequence_entries"][entry["id"]]
        renumber_route_entries(route_id)
        refresh_route_counts(route_id)
    compute_vacancy(p)
    return ok(point_public(p))


@app.route("/api/delivery-points", methods=["GET"])
def list_points_flat():
    uid, role = require_roles("AddressManagementSpecialist", "RouteSupervisor", "Postmaster", "CustomerServiceRep", "PlatformAdmin")
    items = list(DB["points"].values())
    for p in items:
        compute_vacancy(p)
    unit_id = request.args.get("delivery_unit_id")
    route_id = request.args.get("active_route_id")
    occ = request.args.get("occupancy_status")
    is_del = request.args.get("is_deliverable")
    if unit_id:
        items = [p for p in items if p["delivery_unit_id"] == unit_id]
    if route_id:
        items = [p for p in items if p.get("active_route_id") == route_id]
    if occ:
        items = [p for p in items if p["occupancy_status"] == occ]
    if is_del is not None and is_del != "":
        want = is_del.lower() in ("true", "1", "yes")
        items = [p for p in items if p["is_deliverable"] == want]
    return list_response([deepcopy(p) for p in items])


@app.route("/api/delivery-points/<pointId>", methods=["GET"])
def get_point_flat(pointId):
    uid, role = require_roles("AddressManagementSpecialist", "RouteSupervisor", "Postmaster", "CustomerServiceRep", "Carrier", "PlatformAdmin")
    p = get_point_or_404(pointId)
    return ok(point_public(p))


# ===========================================================================
# CARRIERS
# ===========================================================================
@app.route("/api/delivery-units/<unitId>/carriers", methods=["POST"])
def create_carrier(unitId):
    uid, role = require_roles("Postmaster")
    get_unit_or_404(unitId)
    body = get_body()
    emp = body.get("employee_id")
    name = body.get("full_name")
    cclass = body.get("carrier_class")
    if not emp or not RE_EMPLOYEE.match(emp or ""):
        raise err_invalid_request("employee_id must match ^E[0-9]{7}$")
    if not name or not isinstance(name, str):
        raise err_invalid_request("full_name required")
    if cclass not in CARRIER_CLASSES:
        raise err_invalid_request("invalid carrier_class")
    for c in DB["carriers"].values():
        if c["employee_id"] == emp:
            raise err_duplicate("employee_id already exists")
    rec = new_record({
        "delivery_unit_id": unitId,
        "employee_id": emp,
        "full_name": name,
        "carrier_class": cclass,
        "status": "AVAILABLE",
    })
    DB["carriers"][rec["id"]] = rec
    return ok(rec, status=201)


@app.route("/api/delivery-units/<unitId>/carriers/<carrierId>", methods=["GET"])
def get_carrier_nested(unitId, carrierId):
    uid, role = require_roles("Postmaster", "RouteSupervisor", "PlatformAdmin", "Carrier")
    get_unit_or_404(unitId)
    c = get_carrier_or_404(carrierId)
    require_child(unitId, c, "delivery_unit_id", "Carrier")
    return ok(deepcopy(c))


@app.route("/api/delivery-units/<unitId>/carriers", methods=["GET"])
def list_carriers_nested(unitId):
    uid, role = require_roles("Postmaster", "RouteSupervisor", "PlatformAdmin")
    get_unit_or_404(unitId)
    items = [c for c in DB["carriers"].values() if c["delivery_unit_id"] == unitId]
    cc = request.args.get("carrier_class")
    st = request.args.get("status")
    if cc:
        items = [c for c in items if c["carrier_class"] == cc]
    if st:
        items = [c for c in items if c["status"] == st]
    return list_response([deepcopy(c) for c in items])


@app.route("/api/carriers", methods=["GET"])
def list_carriers_flat():
    uid, role = require_roles("Postmaster", "RouteSupervisor", "PlatformAdmin")
    items = list(DB["carriers"].values())
    uid_f = request.args.get("delivery_unit_id")
    cc = request.args.get("carrier_class")
    st = request.args.get("status")
    if uid_f:
        items = [c for c in items if c["delivery_unit_id"] == uid_f]
    if cc:
        items = [c for c in items if c["carrier_class"] == cc]
    if st:
        items = [c for c in items if c["status"] == st]
    return list_response([deepcopy(c) for c in items])


@app.route("/api/carriers/<carrierId>", methods=["GET"])
def get_carrier_flat(carrierId):
    uid, role = require_roles("Postmaster", "RouteSupervisor", "PlatformAdmin", "Carrier")
    c = get_carrier_or_404(carrierId)
    return ok(deepcopy(c))


# ===========================================================================
# CARRIER ROUTES
# ===========================================================================
def route_public(route):
    refresh_route_counts(route["id"])
    refresh_aux_relief(route["id"])
    return deepcopy(route)


@app.route("/api/delivery-units/<unitId>/routes", methods=["POST"])
def create_route(unitId):
    uid, role = require_roles("RouteSupervisor")
    unit = get_unit_or_404(unitId)
    body = get_body()
    code = body.get("route_code")
    carrier_id = body.get("assigned_carrier_id")
    rtype = body.get("route_type")
    if not code or not isinstance(code, str):
        raise err_invalid_request("route_code required")
    if not carrier_id:
        raise err_invalid_request("assigned_carrier_id required")
    carrier = DB["carriers"].get(carrier_id)
    if not carrier:
        raise err_reference("assigned_carrier_id does not exist")
    if rtype not in ROUTE_TYPES:
        raise err_invalid_request("invalid route_type")
    if carrier["delivery_unit_id"] != unitId:
        raise err_invalid_request("carrier not of this unit")
    if carrier["status"] == "INACTIVE":
        raise err_cross("carrier is INACTIVE")
    for r in DB["routes"].values():
        if r["delivery_unit_id"] == unitId and r["route_code"] == code:
            raise err_duplicate("route_code already used in unit")
    rec = new_record({
        "delivery_unit_id": unitId,
        "route_code": code,
        "assigned_carrier_id": carrier_id,
        "route_type": rtype,
        "status": "STANDARD",
        "base_evaluated_minutes": 480,
        "current_evaluated_minutes": 480,
        "active_delivery_point_count": 0,
        "under_evaluation_since": None,
        "auxiliary_relief_minutes": 0,
    })
    DB["routes"][rec["id"]] = rec
    refresh_unit_counts(unitId)
    return ok(deepcopy(rec), status=201)


@app.route("/api/delivery-units/<unitId>/routes/<routeId>", methods=["GET"])
def get_route_nested(unitId, routeId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "AddressManagementSpecialist", "CustomerServiceRep", "Carrier", "PlatformAdmin")
    get_unit_or_404(unitId)
    r = get_route_or_404(routeId)
    require_child(unitId, r, "delivery_unit_id", "Route")
    return ok(route_public(r))


@app.route("/api/delivery-units/<unitId>/routes", methods=["GET"])
def list_routes_nested(unitId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "AddressManagementSpecialist", "CustomerServiceRep", "PlatformAdmin")
    get_unit_or_404(unitId)
    items = [r for r in DB["routes"].values() if r["delivery_unit_id"] == unitId]
    st = request.args.get("status")
    cid = request.args.get("assigned_carrier_id")
    if st:
        items = [r for r in items if r["status"] == st]
    if cid:
        items = [r for r in items if r["assigned_carrier_id"] == cid]
    for r in items:
        refresh_route_counts(r["id"])
        refresh_aux_relief(r["id"])
    return list_response([deepcopy(r) for r in items])


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/suspend", methods=["POST"])
def suspend_route(unitId, routeId):
    uid, role = require_roles("Postmaster")
    get_unit_or_404(unitId)
    r = get_route_or_404(routeId)
    require_child(unitId, r, "delivery_unit_id", "Route")
    if r["status"] != "STANDARD":
        raise err_invalid_state("route must be STANDARD")
    refresh_route_counts(routeId)
    if r["active_delivery_point_count"] != 0:
        raise err_uso("route has active points")
    r["status"] = "SUSPENDED"
    touch(r)
    # curtail open auxiliaries
    for a in DB["auxiliary"].values():
        if a["carrier_route_id"] == routeId and a["status"] in ("REQUESTED", "APPROVED", "ACTIVE"):
            a["status"] = "CURTAILED"
            touch(a)
    r["auxiliary_relief_minutes"] = 0
    refresh_unit_counts(unitId)
    return ok(route_public(r))


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/reactivate", methods=["POST"])
def reactivate_route(unitId, routeId):
    uid, role = require_roles("Postmaster")
    get_unit_or_404(unitId)
    r = get_route_or_404(routeId)
    require_child(unitId, r, "delivery_unit_id", "Route")
    body = get_body()
    new_carrier = body.get("assigned_carrier_id")
    if not new_carrier:
        raise err_invalid_request("assigned_carrier_id required")
    carrier = DB["carriers"].get(new_carrier)
    if not carrier:
        raise err_reference("assigned_carrier_id does not exist")
    if r["status"] != "SUSPENDED":
        raise err_invalid_state("route must be SUSPENDED")
    if carrier["delivery_unit_id"] != unitId:
        raise err_invalid_request("carrier not of this unit")
    if carrier["status"] != "AVAILABLE":
        raise err_invalid_state("replacement carrier must be AVAILABLE")
    r["assigned_carrier_id"] = new_carrier
    r["status"] = "STANDARD"
    touch(r)
    refresh_unit_counts(unitId)
    return ok(route_public(r))


@app.route("/api/routes", methods=["GET"])
def list_routes_flat():
    uid, role = require_roles("RouteSupervisor", "Postmaster", "AddressManagementSpecialist", "CustomerServiceRep", "PlatformAdmin")
    items = list(DB["routes"].values())
    uid_f = request.args.get("delivery_unit_id")
    cid = request.args.get("assigned_carrier_id")
    st = request.args.get("status")
    if uid_f:
        items = [r for r in items if r["delivery_unit_id"] == uid_f]
    if cid:
        items = [r for r in items if r["assigned_carrier_id"] == cid]
    if st:
        items = [r for r in items if r["status"] == st]
    for r in items:
        refresh_route_counts(r["id"])
        refresh_aux_relief(r["id"])
    return list_response([deepcopy(r) for r in items])


@app.route("/api/routes/<routeId>", methods=["GET"])
def get_route_flat(routeId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "AddressManagementSpecialist", "CustomerServiceRep", "Carrier", "PlatformAdmin")
    r = get_route_or_404(routeId)
    return ok(route_public(r))


# ===========================================================================
# SEQUENCE ENTRIES
# ===========================================================================
@app.route("/api/delivery-units/<unitId>/routes/<routeId>/sequence-entries", methods=["POST"])
def replace_sequence(unitId, routeId):
    uid, role = require_roles("RouteSupervisor")
    unit = get_unit_or_404(unitId)
    route = get_route_or_404(routeId)
    require_child(unitId, route, "delivery_unit_id", "Route")
    body = get_body()
    expected = body.get("expected_route_version")
    entries_in = body.get("entries")
    if not isinstance(entries_in, list):
        raise err_invalid_request("entries must be a list")
    # Body FK existence (priority 4)
    for ent in entries_in:
        if not isinstance(ent, dict):
            raise err_invalid_request("entry malformed")
        pid = ent.get("delivery_point_id")
        if not pid or pid not in DB["points"]:
            raise err_reference("delivery_point_id does not exist")
    # State precondition: route must not be SUSPENDED
    if route["status"] == "SUSPENDED":
        raise err_invalid_state("route suspended")
    # OCC
    if expected is None:
        raise err_invalid_request("expected_route_version required")
    if expected != route["version"]:
        raise err_stale("route version mismatch")
    # Sequence integrity (priority 12)
    positions = [ent.get("line_of_travel_order") for ent in entries_in]
    for pos in positions:
        if not isinstance(pos, int) or pos < 1:
            raise err_sequence_invalid("line_of_travel_order must be >= 1 integer")
    if len(set(positions)) != len(positions):
        raise err_sequence_dup("duplicate line_of_travel_order")
    # Case capacity: validate all letters first, then all flats (priority 13).
    # Computed slot overflow is rejected before the 1..N permutation check.
    s = unit["case_slot_count_per_route"]
    for ent in entries_in:
        letters, _ = case_slots(ent["line_of_travel_order"])
        if letters > s:
            raise err_case_capacity("letter case slot exceeds capacity")
    for ent in entries_in:
        _, flats = case_slots(ent["line_of_travel_order"])
        if flats > s:
            raise err_case_capacity("flat case slot exceeds capacity")
    n = len(positions)
    if sorted(positions) != list(range(1, n + 1)):
        raise err_sequence_invalid("positions must be a permutation of 1..N")
    for ent in entries_in:
        pid = ent["delivery_point_id"]
        point = DB["points"][pid]
        if point.get("active_route_id") != routeId:
            raise err_sequence_invalid("point not assigned to route")
        if point["occupancy_status"] not in ("OCCUPIED", "SEASONAL", "VACANT"):
            raise err_sequence_invalid("point not deliverable-eligible")
        grp = ent.get("delivery_order_group", "PARK_LOOP")
        if grp not in DELIVERY_ORDER_GROUPS:
            raise err_sequence_invalid("invalid delivery_order_group")
    # Atomic commit: drop existing entries for the route
    for eid in [e["id"] for e in DB["sequence_entries"].values() if e["carrier_route_id"] == routeId]:
        del DB["sequence_entries"][eid]
    out = []
    for ent in entries_in:
        letters, flats = case_slots(ent["line_of_travel_order"])
        rec = new_record({
            "carrier_route_id": routeId,
            "delivery_point_id": ent["delivery_point_id"],
            "line_of_travel_order": ent["line_of_travel_order"],
            "case_slot_letters": letters,
            "case_slot_flats": flats,
            "delivery_order_group": ent.get("delivery_order_group", "PARK_LOOP"),
        })
        DB["sequence_entries"][rec["id"]] = rec
        out.append(rec)
        # sync point
        point = DB["points"][ent["delivery_point_id"]]
        point["active_route_id"] = routeId
    touch(route)
    out.sort(key=lambda e: e["line_of_travel_order"])
    return ok([deepcopy(x) for x in out], status=200, response_type="array")


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/sequence-entries", methods=["GET"])
def list_sequence_entries_nested(unitId, routeId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "AddressManagementSpecialist", "Carrier", "PlatformAdmin")
    get_unit_or_404(unitId)
    r = get_route_or_404(routeId)
    require_child(unitId, r, "delivery_unit_id", "Route")
    items = [e for e in DB["sequence_entries"].values() if e["carrier_route_id"] == routeId]
    items.sort(key=lambda e: e["line_of_travel_order"])
    dp = request.args.get("delivery_point_id")
    if dp:
        items = [e for e in items if e["delivery_point_id"] == dp]
    total = len(items)
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise err_invalid_request("invalid pagination")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit out of range")
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total, "has_more": offset + limit < total}
    return ok([deepcopy(x) for x in page], status=200, response_type="array", pagination=meta)


@app.route("/api/sequence-entries", methods=["GET"])
def list_sequence_entries_flat():
    uid, role = require_roles("RouteSupervisor", "Postmaster", "AddressManagementSpecialist", "PlatformAdmin")
    items = list(DB["sequence_entries"].values())
    rid = request.args.get("carrier_route_id")
    pid = request.args.get("delivery_point_id")
    if rid:
        items = [e for e in items if e["carrier_route_id"] == rid]
    if pid:
        items = [e for e in items if e["delivery_point_id"] == pid]
    return list_response([deepcopy(e) for e in items])


@app.route("/api/sequence-entries/<entryId>", methods=["GET"])
def get_sequence_entry_flat(entryId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "AddressManagementSpecialist", "Carrier", "PlatformAdmin")
    e = get_entry_or_404(entryId)
    return ok(deepcopy(e))


# ===========================================================================
# ROUTE EVALUATION
# ===========================================================================
def round_half_up_dec(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def modeled_street_time(letters, flats, parcels):
    casing = round_half_up_dec(Decimal(letters) / Decimal("18.0"), 2) + round_half_up_dec(Decimal(flats) / Decimal("8.0"), 2)
    pull_down = round_half_up_dec(Decimal(letters + flats) / Decimal("70.0"), 2)
    street_base = round_half_up_dec(Decimal(parcels) * Decimal("2.5"), 2)
    total_lf = letters + flats
    if total_lf >= 12000:
        tier = 2
    elif total_lf >= 6000:
        tier = 1
    else:
        tier = 0
    factor = [Decimal("1.00"), Decimal("0.97"), Decimal("0.94")][tier]
    weighted = street_base + casing * Decimal("0.62") + pull_down
    modeled = (weighted * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(modeled)


def evaluation_public(e):
    return deepcopy(e)


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations", methods=["POST"])
def create_evaluation(unitId, routeId):
    uid, role = require_roles("RouteSupervisor")
    get_unit_or_404(unitId)
    route = get_route_or_404(routeId)
    require_child(unitId, route, "delivery_unit_id", "Route")
    body = get_body()
    kind = body.get("evaluation_kind")
    cws = body.get("count_week_start")
    expected = body.get("expected_route_version")
    if kind not in EVAL_KINDS:
        raise err_invalid_request("invalid evaluation_kind")
    if not cws:
        raise err_invalid_request("count_week_start required")
    parse_date(cws)
    if expected is None:
        raise err_invalid_request("expected_route_version required")
    # cross-entity state: route must be STANDARD
    if route["status"] != "STANDARD":
        raise err_cross("route must be STANDARD")
    # no other open evaluation
    for ev in DB["evaluations"].values():
        if ev["carrier_route_id"] == routeId and ev["status"] not in ("CLOSED_ADOPTED", "CLOSED_REJECTED"):
            raise err_invalid_state("another evaluation is open")
    # OCC
    if expected != route["version"]:
        raise err_stale("route version mismatch")
    rec = new_record({
        "carrier_route_id": routeId,
        "evaluation_kind": kind,
        "count_week_start": cws,
        "letters_count_total": None,
        "flats_count_total": None,
        "parcels_count_total": None,
        "actual_street_minutes_total": None,
        "office_minutes_total": None,
        "modeled_street_minutes_total": None,
        "evaluated_daily_minutes": None,
        "consultation_outcome": "PENDING",
        "status": "INITIATED",
        "recollection_used": False,
    })
    DB["evaluations"][rec["id"]] = rec
    route["status"] = "UNDER_EVALUATION"
    route["under_evaluation_since"] = now_iso()
    touch(route)
    return ok(rec, status=201)


def get_nested_evaluation(unitId, routeId, evalId):
    get_unit_or_404(unitId)
    route = get_route_or_404(routeId)
    require_child(unitId, route, "delivery_unit_id", "Route")
    ev = get_eval_or_404(evalId)
    require_child(routeId, ev, "carrier_route_id", "Evaluation")
    return route, ev


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations/<evalId>", methods=["GET"])
def get_evaluation_nested(unitId, routeId, evalId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "PlatformAdmin")
    route, ev = get_nested_evaluation(unitId, routeId, evalId)
    return ok(evaluation_public(ev))


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations", methods=["GET"])
def list_evaluations_nested(unitId, routeId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "PlatformAdmin")
    get_unit_or_404(unitId)
    r = get_route_or_404(routeId)
    require_child(unitId, r, "delivery_unit_id", "Route")
    items = [e for e in DB["evaluations"].values() if e["carrier_route_id"] == routeId]
    st = request.args.get("status")
    if st:
        items = [e for e in items if e["status"] == st]
    return list_response([deepcopy(e) for e in items])


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations/<evalId>/begin-count", methods=["POST"])
def begin_count(unitId, routeId, evalId):
    uid, role = require_roles("RouteSupervisor")
    route, ev = get_nested_evaluation(unitId, routeId, evalId)
    check_state("evaluation", ev, {"INITIATED"})
    # count weeks always run Saturday through Friday
    cws = parse_date(ev["count_week_start"])
    if cws.weekday() != 5:
        raise err_temporal("count_week_start must be a Saturday")
    if ev["evaluation_kind"] == "FULL_COUNT":
        if (cws - current_date()).days < 14:
            raise err_temporal("FULL_COUNT requires count_week_start >= 14 days ahead")
    ev["status"] = "DATA_COLLECTION"
    touch(ev)
    return ok(evaluation_public(ev))


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations/<evalId>/submit-counts", methods=["POST"])
def submit_counts(unitId, routeId, evalId):
    uid, role = require_roles("RouteSupervisor")
    route, ev = get_nested_evaluation(unitId, routeId, evalId)
    check_state("evaluation", ev, {"DATA_COLLECTION"})
    body = get_body()
    fields = ["letters_count_total", "flats_count_total", "parcels_count_total",
              "actual_street_minutes_total", "office_minutes_total"]
    vals = {}
    for f in fields:
        v = body.get(f)
        if not isinstance(v, int) or isinstance(v, bool):
            raise err_invalid_request(f"{f} must be a non-negative integer")
        if v < 0:
            raise err_range(f"{f} must be >= 0")
        vals[f] = v
    ev.update(vals)
    ev["modeled_street_minutes_total"] = modeled_street_time(vals["letters_count_total"], vals["flats_count_total"], vals["parcels_count_total"])
    ev["status"] = "CONSULTATION_SCHEDULED"
    touch(ev)
    return ok(evaluation_public(ev))


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations/<evalId>/record-consultation", methods=["POST"])
def record_consultation(unitId, routeId, evalId):
    uid, role = require_roles("RouteSupervisor")
    route, ev = get_nested_evaluation(unitId, routeId, evalId)
    check_state("evaluation", ev, {"CONSULTATION_SCHEDULED"})
    body = get_body()
    outcome = body.get("consultation_outcome")
    if outcome not in CONSULTATION_OUTCOMES:
        raise err_invalid_request("invalid consultation_outcome")
    ev["consultation_outcome"] = outcome
    actual = ev["actual_street_minutes_total"] or 0
    modeled = ev["modeled_street_minutes_total"] or 0
    office = ev["office_minutes_total"] or 0
    if outcome == "DISPUTED":
        adopted = min(actual, modeled)
    else:
        adopted = actual
    ev["evaluated_daily_minutes"] = int(round_half_up_dec(Decimal(office + adopted) / Decimal(6), 0))
    ev["status"] = "CONSULTED"
    touch(ev)
    return ok(evaluation_public(ev))


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations/<evalId>/order-recollection", methods=["POST"])
def order_recollection(unitId, routeId, evalId):
    uid, role = require_roles("Postmaster")
    route, ev = get_nested_evaluation(unitId, routeId, evalId)
    check_state("evaluation", ev, {"CONSULTED"})
    if ev["consultation_outcome"] != "DISPUTED" or ev["recollection_used"]:
        raise err_recollection("re-collection not allowed")
    ev["recollection_used"] = True
    for f in ("letters_count_total", "flats_count_total", "parcels_count_total",
              "actual_street_minutes_total", "office_minutes_total"):
        ev[f] = 0
    ev["modeled_street_minutes_total"] = None
    ev["evaluated_daily_minutes"] = None
    ev["consultation_outcome"] = "PENDING"
    ev["status"] = "DATA_COLLECTION"
    touch(ev)
    return ok(evaluation_public(ev))


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations/<evalId>/close-rejected", methods=["POST"])
def close_rejected(unitId, routeId, evalId):
    uid, role = require_roles("RouteSupervisor")
    route, ev = get_nested_evaluation(unitId, routeId, evalId)
    check_state("evaluation", ev, {"CONSULTED"})
    for adj in DB["adjustments"].values():
        if adj["route_evaluation_id"] == evalId and adj["status"] in ("DRAFT", "SUBMITTED", "APPROVED"):
            raise err_invalid_state("open adjustment exists")
    ev["status"] = "CLOSED_REJECTED"
    touch(ev)
    route["status"] = "STANDARD"
    route["under_evaluation_since"] = None
    touch(route)
    return ok(evaluation_public(ev))


@app.route("/api/evaluations", methods=["GET"])
def list_evaluations_flat():
    uid, role = require_roles("RouteSupervisor", "Postmaster", "PlatformAdmin")
    items = list(DB["evaluations"].values())
    rid = request.args.get("carrier_route_id")
    st = request.args.get("status")
    if rid:
        items = [e for e in items if e["carrier_route_id"] == rid]
    if st:
        items = [e for e in items if e["status"] == st]
    return list_response([deepcopy(e) for e in items])


@app.route("/api/evaluations/<evalId>", methods=["GET"])
def get_evaluation_flat(evalId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "PlatformAdmin")
    e = get_eval_or_404(evalId)
    return ok(evaluation_public(e))


# ===========================================================================
# ROUTE ADJUSTMENT
# ===========================================================================
def get_nested_adjustment(unitId, routeId, evalId, adjId):
    route, ev = get_nested_evaluation(unitId, routeId, evalId)
    adj = get_adj_or_404(adjId)
    require_child(evalId, adj, "route_evaluation_id", "Adjustment")
    return route, ev, adj


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations/<evalId>/adjustments", methods=["POST"])
def create_adjustment(unitId, routeId, evalId):
    uid, role = require_roles("RouteSupervisor")
    route, ev = get_nested_evaluation(unitId, routeId, evalId)
    body = get_body()
    proposed = body.get("proposed_evaluated_minutes")
    transfers = body.get("points_transferred_out", [])
    eff_date_s = body.get("effective_date")
    # a draft may be created on any evaluation that is not closed; submitting
    # (not drafting) is the step gated on CONSULTED
    if ev["status"] == "CLOSED_ADOPTED" or ev["status"] == "CLOSED_REJECTED":
        raise err_already_terminal("evaluation closed")
    if not isinstance(proposed, int) or isinstance(proposed, bool):
        raise err_invalid_request("proposed_evaluated_minutes must be integer")
    if proposed < 240 or proposed > 600:
        raise err_range("proposed_evaluated_minutes must be 240..600")
    if not isinstance(transfers, list):
        raise err_invalid_request("points_transferred_out must be a list")
    # body FK existence
    for move in transfers:
        if not isinstance(move, dict):
            raise err_invalid_request("malformed transfer")
        pid = move.get("delivery_point_id")
        trid = move.get("to_route_id")
        if not pid or pid not in DB["points"]:
            raise err_reference("delivery_point_id in transfer does not exist")
        if not trid or trid not in DB["routes"]:
            raise err_reference("to_route_id in transfer does not exist")
    # business referential: destination routes in same unit; no move to SUSPENDED
    for move in transfers:
        target = DB["routes"][move["to_route_id"]]
        if target["delivery_unit_id"] != unitId:
            raise err_invalid_request("to_route must belong to same unit")
        if target["status"] == "SUSPENDED":
            raise err_invalid_request("cannot transfer to SUSPENDED route")
    if not eff_date_s:
        raise err_invalid_request("effective_date required")
    parse_date(eff_date_s)
    rec = new_record({
        "route_evaluation_id": evalId,
        "proposed_evaluated_minutes": proposed,
        "points_transferred_out": transfers,
        "status": "DRAFT",
        "effective_date": eff_date_s,
        "approver_user_id": None,
        "submitter_user_id": None,
    })
    DB["adjustments"][rec["id"]] = rec
    return ok(deepcopy(rec), status=201)


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations/<evalId>/adjustments", methods=["GET"])
def list_adjustments_nested(unitId, routeId, evalId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "PlatformAdmin")
    route, ev = get_nested_evaluation(unitId, routeId, evalId)
    items = [a for a in DB["adjustments"].values() if a["route_evaluation_id"] == evalId]
    st = request.args.get("status")
    if st:
        items = [a for a in items if a["status"] == st]
    return list_response([deepcopy(a) for a in items])


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations/<evalId>/adjustments/<adjId>", methods=["GET"])
def get_adjustment_nested(unitId, routeId, evalId, adjId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "PlatformAdmin")
    route, ev, adj = get_nested_adjustment(unitId, routeId, evalId, adjId)
    return ok(deepcopy(adj))


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations/<evalId>/adjustments/<adjId>/submit", methods=["POST"])
def submit_adjustment(unitId, routeId, evalId, adjId):
    uid, role = require_roles("RouteSupervisor")
    route, ev, adj = get_nested_adjustment(unitId, routeId, evalId, adjId)
    check_state("adjustment", adj, {"DRAFT"})
    if ev["status"] != "CONSULTED":
        raise err_cross("evaluation must be CONSULTED")
    adj["status"] = "SUBMITTED"
    adj["submitter_user_id"] = uid
    touch(adj)
    return ok(deepcopy(adj))


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations/<evalId>/adjustments/<adjId>/approve", methods=["POST"])
def approve_adjustment(unitId, routeId, evalId, adjId):
    uid, role = require_roles("Postmaster")
    route, ev, adj = get_nested_adjustment(unitId, routeId, evalId, adjId)
    check_state("adjustment", adj, {"SUBMITTED"})
    # segregation
    if uid == adj.get("submitter_user_id"):
        raise err_sod("approver must differ from submitter")
    # temporal
    eff = parse_date(adj["effective_date"])
    if (eff - current_date()).days < 7:
        raise err_temporal("effective_date must be >= current date + 7 days")
    adj["status"] = "APPROVED"
    adj["approver_user_id"] = uid
    touch(adj)
    route["status"] = "UNDER_ADJUSTMENT"
    touch(route)
    return ok(deepcopy(adj))


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations/<evalId>/adjustments/<adjId>/reject", methods=["POST"])
def reject_adjustment(unitId, routeId, evalId, adjId):
    uid, role = require_roles("Postmaster")
    route, ev, adj = get_nested_adjustment(unitId, routeId, evalId, adjId)
    check_state("adjustment", adj, {"SUBMITTED"})
    if uid == adj.get("submitter_user_id"):
        raise err_sod("rejector must differ from submitter")
    adj["status"] = "REJECTED"
    touch(adj)
    return ok(deepcopy(adj))


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/evaluations/<evalId>/adjustments/<adjId>/withdraw", methods=["POST"])
def withdraw_adjustment(unitId, routeId, evalId, adjId):
    uid, role = require_roles("RouteSupervisor")
    route, ev, adj = get_nested_adjustment(unitId, routeId, evalId, adjId)
    check_state("adjustment", adj, {"DRAFT"})
    adj["status"] = "WITHDRAWN"
    touch(adj)
    return ok(deepcopy(adj))


@app.route("/api/adjustments", methods=["GET"])
def list_adjustments_flat():
    uid, role = require_roles("RouteSupervisor", "Postmaster", "PlatformAdmin")
    items = list(DB["adjustments"].values())
    rid = request.args.get("route_evaluation_id")
    st = request.args.get("status")
    if rid:
        items = [a for a in items if a["route_evaluation_id"] == rid]
    if st:
        items = [a for a in items if a["status"] == st]
    return list_response([deepcopy(a) for a in items])


@app.route("/api/adjustments/<adjId>", methods=["GET"])
def get_adjustment_flat(adjId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "PlatformAdmin")
    a = get_adj_or_404(adjId)
    return ok(deepcopy(a))


# ===========================================================================
# AUXILIARY ASSIGNMENT
# ===========================================================================
def in_seasonal_window(d):
    # Nov 15 - Jan 2 window (wraps year end)
    md = (d.month, d.day)
    return md >= (11, 15) or md <= (1, 2)


def get_nested_aux(unitId, routeId, auxId):
    get_unit_or_404(unitId)
    route = get_route_or_404(routeId)
    require_child(unitId, route, "delivery_unit_id", "Route")
    aux = get_aux_or_404(auxId)
    require_child(routeId, aux, "carrier_route_id", "Auxiliary assignment")
    return route, aux


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/auxiliary-assignments", methods=["POST"])
def create_aux(unitId, routeId):
    uid, role = require_roles("RouteSupervisor")
    get_unit_or_404(unitId)
    route = get_route_or_404(routeId)
    require_child(unitId, route, "delivery_unit_id", "Route")
    body = get_body()
    helper_id = body.get("helper_carrier_id")
    service_date_s = body.get("service_date")
    overrun = body.get("projected_overrun_minutes")
    surge = body.get("seasonal_surge_flag", False)
    if not helper_id:
        raise err_invalid_request("helper_carrier_id required")
    helper = DB["carriers"].get(helper_id)
    if not helper:
        raise err_reference("helper_carrier_id does not exist")
    if helper["delivery_unit_id"] != unitId:
        raise err_invalid_request("helper must be of this unit")
    if helper["carrier_class"] not in ("AUXILIARY", "CITY_ASSISTANT"):
        raise err_invalid_request("helper must be AUXILIARY or CITY_ASSISTANT")
    if helper_id == route["assigned_carrier_id"]:
        raise err_invalid_request("helper may not be the route's assigned carrier")
    if not service_date_s:
        raise err_invalid_request("service_date required")
    parse_date(service_date_s)
    if not isinstance(overrun, int) or isinstance(overrun, bool):
        raise err_invalid_request("projected_overrun_minutes must be integer")
    if overrun < 30:
        raise err_overrun("projected_overrun_minutes must be >= 30")
    rec = new_record({
        "carrier_route_id": routeId,
        "helper_carrier_id": helper_id,
        "service_date": service_date_s,
        "scheduled_minutes": None,
        "projected_overrun_minutes": overrun,
        "seasonal_surge_flag": bool(surge),
        "status": "REQUESTED",
    })
    DB["auxiliary"][rec["id"]] = rec
    return ok(deepcopy(rec), status=201)


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/auxiliary-assignments", methods=["GET"])
def list_aux_nested(unitId, routeId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "PlatformAdmin")
    get_unit_or_404(unitId)
    r = get_route_or_404(routeId)
    require_child(unitId, r, "delivery_unit_id", "Route")
    items = [a for a in DB["auxiliary"].values() if a["carrier_route_id"] == routeId]
    st = request.args.get("status")
    helper = request.args.get("helper_carrier_id")
    if st:
        items = [a for a in items if a["status"] == st]
    if helper:
        items = [a for a in items if a["helper_carrier_id"] == helper]
    return list_response([deepcopy(a) for a in items])


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/auxiliary-assignments/<auxId>/approve", methods=["POST"])
def approve_aux(unitId, routeId, auxId):
    uid, role = require_roles("Postmaster")
    route, aux = get_nested_aux(unitId, routeId, auxId)
    check_state("auxiliary", aux, {"REQUESTED"})
    helper = DB["carriers"][aux["helper_carrier_id"]]
    if helper["status"] == "INACTIVE":
        raise err_cross("helper is INACTIVE")
    if aux["helper_carrier_id"] == route["assigned_carrier_id"]:
        raise err_invalid_request("helper may not be assigned carrier")
    if aux["seasonal_surge_flag"] and not in_seasonal_window(current_date()):
        raise err_temporal("outside seasonal surge window")
    base = aux["projected_overrun_minutes"]
    if base < 30:
        raise err_overrun("overrun below threshold")
    assistance = Decimal(base)
    if aux["seasonal_surge_flag"]:
        assistance = (assistance * Decimal("1.25")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if route["current_evaluated_minutes"] > route["base_evaluated_minutes"]:
        assistance = assistance + Decimal(15)
    assistance = min(int(assistance), 240)
    aux["scheduled_minutes"] = assistance
    aux["status"] = "APPROVED"
    touch(aux)
    refresh_aux_relief(routeId)
    route["updated_at"] = now_iso()
    route["version"] += 1
    return ok(deepcopy(aux))


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/auxiliary-assignments/<auxId>/deny", methods=["POST"])
def deny_aux(unitId, routeId, auxId):
    uid, role = require_roles("Postmaster")
    route, aux = get_nested_aux(unitId, routeId, auxId)
    check_state("auxiliary", aux, {"REQUESTED"})
    aux["status"] = "DENIED"
    touch(aux)
    return ok(deepcopy(aux))


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/auxiliary-assignments/<auxId>/complete", methods=["POST"])
def complete_aux(unitId, routeId, auxId):
    uid, role = require_roles("RouteSupervisor")
    route, aux = get_nested_aux(unitId, routeId, auxId)
    check_state("auxiliary", aux, {"ACTIVE"})
    aux["status"] = "COMPLETED"
    touch(aux)
    refresh_aux_relief(routeId)
    route["updated_at"] = now_iso()
    route["version"] += 1
    return ok(deepcopy(aux))


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/auxiliary-assignments/<auxId>/curtail", methods=["POST"])
def curtail_aux(unitId, routeId, auxId):
    uid, role = require_roles("RouteSupervisor")
    route, aux = get_nested_aux(unitId, routeId, auxId)
    check_state("auxiliary", aux, {"ACTIVE"})
    aux["status"] = "CURTAILED"
    touch(aux)
    refresh_aux_relief(routeId)
    route["updated_at"] = now_iso()
    route["version"] += 1
    return ok(deepcopy(aux))


@app.route("/api/auxiliary-assignments", methods=["GET"])
def list_aux_flat():
    uid, role = require_roles("RouteSupervisor", "Postmaster", "PlatformAdmin")
    items = list(DB["auxiliary"].values())
    rid = request.args.get("carrier_route_id")
    hid = request.args.get("helper_carrier_id")
    st = request.args.get("status")
    if rid:
        items = [a for a in items if a["carrier_route_id"] == rid]
    if hid:
        items = [a for a in items if a["helper_carrier_id"] == hid]
    if st:
        items = [a for a in items if a["status"] == st]
    return list_response([deepcopy(a) for a in items])


@app.route("/api/auxiliary-assignments/<auxId>", methods=["GET"])
def get_aux_flat(auxId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "PlatformAdmin")
    a = get_aux_or_404(auxId)
    return ok(deepcopy(a))


# ===========================================================================
# CHANGE OF ADDRESS
# ===========================================================================
def get_nested_coa(unitId, coaId):
    get_unit_or_404(unitId)
    c = get_coa_or_404(coaId)
    require_child(unitId, c, "delivery_unit_id", "COA")
    return c


@app.route("/api/delivery-units/<unitId>/coas", methods=["POST"])
def create_coa(unitId):
    uid, role = require_roles("CustomerServiceRep")
    get_unit_or_404(unitId)
    body = get_body()
    old_pid = body.get("old_delivery_point_id")
    new_addr = body.get("new_address_line1")
    new_city = body.get("new_city")
    new_state = body.get("new_state_code")
    new_zip = body.get("new_zip11")
    mkind = body.get("move_kind")
    mtype = body.get("move_type")
    begin_s = body.get("begin_date")
    end_s = body.get("end_date")
    supersedes = body.get("supersedes_coa_id")
    if not old_pid:
        raise err_invalid_request("old_delivery_point_id required")
    if old_pid not in DB["points"]:
        raise err_reference("old_delivery_point_id does not exist")
    if supersedes:
        if supersedes not in DB["coas"]:
            raise err_reference("supersedes_coa_id does not exist")
    if not new_addr:
        raise err_invalid_request("new_address_line1 required")
    if not new_city:
        raise err_invalid_request("new_city required")
    if not new_state or not RE_STATE.match(new_state or ""):
        raise err_invalid_request("invalid new_state_code")
    if not new_zip or not RE_ZIP11.match(new_zip or ""):
        raise err_invalid_request("invalid new_zip11")
    if mkind not in MOVE_KINDS:
        raise err_invalid_request("invalid move_kind")
    if mtype not in MOVE_TYPES:
        raise err_invalid_request("invalid move_type")
    if not begin_s:
        raise err_invalid_request("begin_date required")
    begin = parse_date(begin_s)
    if mtype == "TEMPORARY":
        if not end_s:
            raise err_temporal("end_date required for TEMPORARY")
        end = parse_date(end_s)
        if not (begin < end <= begin + timedelta(days=364)):
            raise err_temporal("end_date must be > begin_date and <= begin+364d")
    else:
        end_s = None
    if supersedes:
        prior = DB["coas"][supersedes]
        if prior["old_delivery_point_id"] != old_pid:
            raise err_invalid_request("supersedes COA must share old point")
        if prior["forwarding_status"] not in ("PENDING", "ACTIVE"):
            raise err_invalid_state("supersedes COA must be PENDING or ACTIVE")
    rec = new_record({
        "delivery_unit_id": unitId,
        "old_delivery_point_id": old_pid,
        "new_address_line1": new_addr,
        "new_city": new_city,
        "new_state_code": new_state,
        "new_zip11": new_zip,
        "move_kind": mkind,
        "move_type": mtype,
        "begin_date": begin_s,
        "end_date": end_s,
        "supersedes_coa_id": supersedes,
        "forwarding_status": "PENDING",
        "validation_status": "UNVERIFIED",
    })
    DB["coas"][rec["id"]] = rec
    return ok(deepcopy(rec), status=201)


@app.route("/api/delivery-units/<unitId>/coas/<coaId>", methods=["GET"])
def get_coa_nested(unitId, coaId):
    uid, role = require_roles("CustomerServiceRep", "Postmaster", "PlatformAdmin")
    c = get_nested_coa(unitId, coaId)
    return ok(deepcopy(c))


@app.route("/api/delivery-units/<unitId>/coas", methods=["GET"])
def list_coas_nested(unitId):
    uid, role = require_roles("CustomerServiceRep", "Postmaster", "PlatformAdmin")
    get_unit_or_404(unitId)
    items = [c for c in DB["coas"].values() if c["delivery_unit_id"] == unitId]
    for k in ("old_delivery_point_id", "forwarding_status", "supersedes_coa_id"):
        v = request.args.get(k)
        if v:
            items = [c for c in items if c.get(k) == v]
    return list_response([deepcopy(c) for c in items])


@app.route("/api/delivery-units/<unitId>/coas/<coaId>/verify", methods=["POST"])
def verify_coa(unitId, coaId):
    uid, role = require_roles("CustomerServiceRep")
    c = get_nested_coa(unitId, coaId)
    if c["forwarding_status"] in TERMINAL["coa"]:
        raise err_already_terminal("coa terminal")
    if c["validation_status"] != "UNVERIFIED":
        raise err_invalid_state("validation_status must be UNVERIFIED")
    c["validation_status"] = "VERIFIED"
    touch(c)
    return ok(deepcopy(c))


@app.route("/api/delivery-units/<unitId>/coas/<coaId>/reject-validation", methods=["POST"])
def reject_validation_coa(unitId, coaId):
    uid, role = require_roles("CustomerServiceRep")
    c = get_nested_coa(unitId, coaId)
    if c["forwarding_status"] in TERMINAL["coa"]:
        raise err_already_terminal("coa terminal")
    if c["validation_status"] != "UNVERIFIED":
        raise err_invalid_state("validation_status must be UNVERIFIED")
    c["validation_status"] = "REJECTED"
    touch(c)
    return ok(deepcopy(c))


def _activate_coa(c):
    """Shared activation logic."""
    # cross-entity gate
    if c["validation_status"] != "VERIFIED":
        raise err_cross("COA not verified")
    # overlap check
    for other in DB["coas"].values():
        if other["id"] == c["id"]:
            continue
        if other["old_delivery_point_id"] == c["old_delivery_point_id"] and other["forwarding_status"] == "ACTIVE":
            if c.get("supersedes_coa_id") == other["id"]:
                other["forwarding_status"] = "CANCELLED"
                touch(other)
            else:
                raise err_forward_overlap("another ACTIVE COA on this point")
    c["forwarding_status"] = "ACTIVE"
    touch(c)


@app.route("/api/delivery-units/<unitId>/coas/<coaId>/activate-now", methods=["POST"])
def activate_coa_now(unitId, coaId):
    uid, role = require_roles("CustomerServiceRep")
    c = get_nested_coa(unitId, coaId)
    if c["forwarding_status"] in TERMINAL["coa"]:
        raise err_already_terminal("coa terminal")
    if c["forwarding_status"] != "PENDING":
        raise err_invalid_state("forwarding_status must be PENDING")
    if parse_date(c["begin_date"]) != current_date():
        raise err_temporal("activate-now requires begin_date == today")
    _activate_coa(c)
    return ok(deepcopy(c))


@app.route("/api/delivery-units/<unitId>/coas/<coaId>/suspend", methods=["POST"])
def suspend_coa(unitId, coaId):
    uid, role = require_roles("CustomerServiceRep")
    c = get_nested_coa(unitId, coaId)
    if c["forwarding_status"] in TERMINAL["coa"]:
        raise err_already_terminal("coa terminal")
    if c["forwarding_status"] != "ACTIVE":
        raise err_invalid_state("forwarding_status must be ACTIVE")
    c["forwarding_status"] = "SUSPENDED"
    touch(c)
    return ok(deepcopy(c))


@app.route("/api/delivery-units/<unitId>/coas/<coaId>/resume", methods=["POST"])
def resume_coa(unitId, coaId):
    uid, role = require_roles("CustomerServiceRep")
    c = get_nested_coa(unitId, coaId)
    if c["forwarding_status"] in TERMINAL["coa"]:
        raise err_already_terminal("coa terminal")
    if c["forwarding_status"] != "SUSPENDED":
        raise err_invalid_state("forwarding_status must be SUSPENDED")
    if c["move_type"] == "TEMPORARY":
        if current_date() > parse_date(c["end_date"]):
            raise err_temporal("cannot resume past end_date")
    c["forwarding_status"] = "ACTIVE"
    touch(c)
    return ok(deepcopy(c))


@app.route("/api/delivery-units/<unitId>/coas/<coaId>/cancel", methods=["POST"])
def cancel_coa(unitId, coaId):
    uid, role = require_roles("CustomerServiceRep")
    c = get_nested_coa(unitId, coaId)
    if c["forwarding_status"] in TERMINAL["coa"]:
        raise err_already_terminal("coa terminal")
    if c["forwarding_status"] not in ("PENDING", "ACTIVE", "SUSPENDED"):
        raise err_invalid_state("cannot cancel from this state")
    c["forwarding_status"] = "CANCELLED"
    touch(c)
    return ok(deepcopy(c))


@app.route("/api/coas", methods=["GET"])
def list_coas_flat():
    uid, role = require_roles("CustomerServiceRep", "Postmaster", "PlatformAdmin")
    items = list(DB["coas"].values())
    for k in ("delivery_unit_id", "old_delivery_point_id", "supersedes_coa_id", "forwarding_status"):
        v = request.args.get(k)
        if v:
            items = [c for c in items if c.get(k) == v]
    return list_response([deepcopy(c) for c in items])


@app.route("/api/coas/<coaId>", methods=["GET"])
def get_coa_flat(coaId):
    uid, role = require_roles("CustomerServiceRep", "Postmaster", "PlatformAdmin")
    c = get_coa_or_404(coaId)
    return ok(deepcopy(c))


# ===========================================================================
# HOLD MAIL
# ===========================================================================
def get_nested_hold(unitId, holdId):
    get_unit_or_404(unitId)
    h = get_hold_or_404(holdId)
    require_child(unitId, h, "delivery_unit_id", "HoldMail")
    return h


def holds_overlap(h1_start, h1_end, h2_start, h2_end):
    # half-open [start, end+1)
    a_end = h1_end + timedelta(days=1)
    b_end = h2_end + timedelta(days=1)
    return h1_start < b_end and h2_start < a_end


@app.route("/api/delivery-units/<unitId>/holds", methods=["POST"])
def create_hold(unitId):
    uid, role = require_roles("CustomerServiceRep")
    get_unit_or_404(unitId)
    body = get_body()
    pid = body.get("delivery_point_id")
    start_s = body.get("hold_start_date")
    end_s = body.get("hold_end_date")
    disposition = body.get("disposition")
    if not pid:
        raise err_invalid_request("delivery_point_id required")
    if pid not in DB["points"]:
        raise err_reference("delivery_point_id does not exist")
    if not start_s:
        raise err_invalid_request("hold_start_date required")
    if not end_s:
        raise err_invalid_request("hold_end_date required")
    start = parse_date(start_s)
    end = parse_date(end_s)
    if disposition not in HOLD_DISPOSITIONS:
        raise err_invalid_request("invalid disposition")
    if start < current_date():
        raise err_temporal("hold_start_date in the past")
    if not (start <= end <= start + timedelta(days=30)):
        raise err_temporal("hold window must be 0..30 days")
    # overlap
    for h in DB["holds"].values():
        if h["delivery_point_id"] != pid:
            continue
        if h["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if holds_overlap(start, end, parse_date(h["hold_start_date"]), parse_date(h["hold_end_date"])):
            raise err_hold_overlap("overlapping hold")
    rec = new_record({
        "delivery_unit_id": unitId,
        "delivery_point_id": pid,
        "hold_start_date": start_s,
        "hold_end_date": end_s,
        "disposition": disposition,
        "status": "SCHEDULED",
    })
    DB["holds"][rec["id"]] = rec
    return ok(deepcopy(rec), status=201)


@app.route("/api/delivery-units/<unitId>/holds/<holdId>", methods=["GET"])
def get_hold_nested(unitId, holdId):
    uid, role = require_roles("CustomerServiceRep", "Postmaster", "Carrier", "PlatformAdmin")
    h = get_nested_hold(unitId, holdId)
    return ok(deepcopy(h))


@app.route("/api/delivery-units/<unitId>/holds", methods=["GET"])
def list_holds_nested(unitId):
    uid, role = require_roles("CustomerServiceRep", "Postmaster", "Carrier", "PlatformAdmin")
    get_unit_or_404(unitId)
    items = [h for h in DB["holds"].values() if h["delivery_unit_id"] == unitId]
    pid = request.args.get("delivery_point_id")
    st = request.args.get("status")
    if pid:
        items = [h for h in items if h["delivery_point_id"] == pid]
    if st:
        items = [h for h in items if h["status"] == st]
    return list_response([deepcopy(h) for h in items])


@app.route("/api/delivery-units/<unitId>/holds/<holdId>/complete-early", methods=["POST"])
def complete_hold_early(unitId, holdId):
    uid, role = require_roles("Carrier")
    h = get_nested_hold(unitId, holdId)
    check_state("hold", h, {"ACTIVE"})
    h["status"] = "COMPLETED"
    touch(h)
    return ok(deepcopy(h))


@app.route("/api/delivery-units/<unitId>/holds/<holdId>/cancel", methods=["POST"])
def cancel_hold(unitId, holdId):
    uid, role = require_roles("CustomerServiceRep")
    h = get_nested_hold(unitId, holdId)
    check_state("hold", h, {"SCHEDULED", "ACTIVE"})
    h["status"] = "CANCELLED"
    touch(h)
    return ok(deepcopy(h))


@app.route("/api/holds", methods=["GET"])
def list_holds_flat():
    uid, role = require_roles("CustomerServiceRep", "Postmaster", "Carrier", "PlatformAdmin")
    items = list(DB["holds"].values())
    uid_f = request.args.get("delivery_unit_id")
    pid = request.args.get("delivery_point_id")
    st = request.args.get("status")
    if uid_f:
        items = [h for h in items if h["delivery_unit_id"] == uid_f]
    if pid:
        items = [h for h in items if h["delivery_point_id"] == pid]
    if st:
        items = [h for h in items if h["status"] == st]
    return list_response([deepcopy(h) for h in items])


@app.route("/api/holds/<holdId>", methods=["GET"])
def get_hold_flat(holdId):
    uid, role = require_roles("CustomerServiceRep", "Postmaster", "Carrier", "PlatformAdmin")
    h = get_hold_or_404(holdId)
    return ok(deepcopy(h))


# ===========================================================================
# DELIVERY SCAN EVENTS
# ===========================================================================
def compute_is_compliant(scan_code, gps_ok, point):
    if not gps_ok:
        return False
    compute_vacancy(point)
    occ = point["occupancy_status"]
    if scan_code == "VACANT_CONFIRMED":
        return occ == "VACANT"
    if scan_code == "DELIVERED":
        return point["is_deliverable"]
    return True


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/scan-events", methods=["POST"])
def create_scan_event(unitId, routeId):
    uid, role = require_roles("Carrier")
    get_unit_or_404(unitId)
    route = get_route_or_404(routeId)
    require_child(unitId, route, "delivery_unit_id", "Route")
    body = get_body()
    pid = body.get("delivery_point_id")
    cid = body.get("carrier_id")
    code = body.get("scan_code")
    sdt = body.get("scan_datetime")
    gps = body.get("gps_within_geofence")
    if not pid:
        raise err_invalid_request("delivery_point_id required")
    if pid not in DB["points"]:
        raise err_reference("delivery_point_id does not exist")
    if not cid:
        raise err_invalid_request("carrier_id required")
    if cid not in DB["carriers"]:
        raise err_reference("carrier_id does not exist")
    # Carrier role is entity-backed: X-User-ID is the acting Carrier's id and
    # must match the scanning carrier recorded on the event
    if cid != uid:
        raise err_forbidden("carrier identity mismatch")
    if code not in SCAN_CODES:
        raise err_invalid_request("invalid scan_code")
    if not sdt:
        raise err_invalid_request("scan_datetime required")
    parse_datetime_iso(sdt)
    if not isinstance(gps, bool):
        raise err_invalid_request("gps_within_geofence must be boolean")
    point = DB["points"][pid]
    is_compliant = compute_is_compliant(code, gps, point)
    rec = {"id": new_id(), "created_at": now_iso(),
           "carrier_route_id": routeId,
           "delivery_point_id": pid,
           "carrier_id": cid,
           "scan_code": code,
           "scan_datetime": sdt,
           "gps_within_geofence": gps,
           "is_compliant": is_compliant}
    DB["scan_events"][rec["id"]] = rec
    return ok(deepcopy(rec), status=201)


@app.route("/api/delivery-units/<unitId>/routes/<routeId>/scan-events", methods=["GET"])
def list_scans_nested(unitId, routeId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "CustomerServiceRep", "PlatformAdmin")
    get_unit_or_404(unitId)
    r = get_route_or_404(routeId)
    require_child(unitId, r, "delivery_unit_id", "Route")
    items = [s for s in DB["scan_events"].values() if s["carrier_route_id"] == routeId]
    for k in ("delivery_point_id", "scan_code", "carrier_id"):
        v = request.args.get(k)
        if v:
            items = [s for s in items if s.get(k) == v]
    return list_response([deepcopy(s) for s in items])


@app.route("/api/scan-events", methods=["GET"])
def list_scans_flat():
    uid, role = require_roles("RouteSupervisor", "Postmaster", "CustomerServiceRep", "PlatformAdmin")
    items = list(DB["scan_events"].values())
    for k in ("carrier_route_id", "delivery_point_id", "carrier_id", "scan_code"):
        v = request.args.get(k)
        if v:
            items = [s for s in items if s.get(k) == v]
    return list_response([deepcopy(s) for s in items])


@app.route("/api/scan-events/<eventId>", methods=["GET"])
def get_scan_flat(eventId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "CustomerServiceRep", "PlatformAdmin")
    s = get_scan_or_404(eventId)
    return ok(deepcopy(s))


@app.route("/api/delivery-units/<unitId>/scan-compliance", methods=["GET"])
def scan_compliance(unitId):
    uid, role = require_roles("RouteSupervisor", "Postmaster", "PlatformAdmin")
    unit = get_unit_or_404(unitId)
    week_start_s = request.args.get("week_start")
    if not week_start_s:
        raise err_invalid_request("week_start required")
    week_start = parse_date(week_start_s)
    week_end = week_start + timedelta(days=7)
    route_ids = {r["id"] for r in DB["routes"].values() if r["delivery_unit_id"] == unitId}
    total = 0
    compliant = 0
    for s in DB["scan_events"].values():
        if s["carrier_route_id"] not in route_ids:
            continue
        sdt = parse_datetime_iso(s["scan_datetime"])
        d = sdt.date()
        if week_start <= d < week_end:
            total += 1
            if s["is_compliant"]:
                compliant += 1
    if total == 0:
        rate = 1.0
    else:
        rate = float(Decimal(compliant) / Decimal(total))
        rate = float(Decimal(str(rate)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    meets = rate >= unit["scan_compliance_target"]
    return ok({
        "week_start": week_start_s,
        "total_scans": total,
        "compliant_scans": compliant,
        "compliance_rate": rate,
        "meets_target": meets,
    })


# ===========================================================================
# CUSTOMER INQUIRIES
# ===========================================================================
def get_nested_inquiry(unitId, inquiryId):
    get_unit_or_404(unitId)
    i = get_inquiry_or_404(inquiryId)
    require_child(unitId, i, "delivery_unit_id", "Inquiry")
    return i


def sla_due_compute(opened_dt):
    # +3 business days, skipping Sundays
    days_added = 0
    cur = opened_dt
    while days_added < 3:
        cur = cur + timedelta(days=1)
        if cur.weekday() != 6:  # not Sunday
            days_added += 1
    return cur


@app.route("/api/delivery-units/<unitId>/inquiries", methods=["POST"])
def create_inquiry(unitId):
    uid, role = require_roles("CustomerServiceRep")
    get_unit_or_404(unitId)
    body = get_body()
    pid = body.get("delivery_point_id")
    kind = body.get("inquiry_kind")
    channel = body.get("opened_by_channel")
    scan_id = body.get("related_scan_event_id")
    if not pid:
        raise err_invalid_request("delivery_point_id required")
    if pid not in DB["points"]:
        raise err_reference("delivery_point_id does not exist")
    if scan_id is not None and scan_id not in DB["scan_events"]:
        raise err_reference("related_scan_event_id does not exist")
    if kind not in INQUIRY_KINDS:
        raise err_invalid_request("invalid inquiry_kind")
    if channel not in INQUIRY_CHANNELS:
        raise err_invalid_request("invalid opened_by_channel")
    opened_dt = current_dt()
    due = sla_due_compute(opened_dt)
    rec = new_record({
        "delivery_unit_id": unitId,
        "delivery_point_id": pid,
        "related_scan_event_id": scan_id,
        "inquiry_kind": kind,
        "opened_by_channel": channel,
        "status": "OPEN",
        "resolution_code": None,
        "sla_due_datetime": due.strftime("%Y-%m-%dT%H:%M:%S.") + f"{due.microsecond // 1000:03d}Z",
        "reopened_count": 0,
        "resolved_at": None,
        "last_status_change_at": opened_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{opened_dt.microsecond // 1000:03d}Z",
    })
    DB["inquiries"][rec["id"]] = rec
    return ok(deepcopy(rec), status=201)


@app.route("/api/delivery-units/<unitId>/inquiries/<inquiryId>", methods=["GET"])
def get_inquiry_nested(unitId, inquiryId):
    uid, role = require_roles("CustomerServiceRep", "Postmaster", "PlatformAdmin")
    i = get_nested_inquiry(unitId, inquiryId)
    return ok(deepcopy(i))


@app.route("/api/delivery-units/<unitId>/inquiries", methods=["GET"])
def list_inquiries_nested(unitId):
    uid, role = require_roles("CustomerServiceRep", "Postmaster", "PlatformAdmin")
    get_unit_or_404(unitId)
    items = [i for i in DB["inquiries"].values() if i["delivery_unit_id"] == unitId]
    for k in ("status", "inquiry_kind", "delivery_point_id", "related_scan_event_id"):
        v = request.args.get(k)
        if v:
            items = [i for i in items if i.get(k) == v]
    return list_response([deepcopy(i) for i in items])


def _mark_status_change(i):
    i["last_status_change_at"] = i["updated_at"]


@app.route("/api/delivery-units/<unitId>/inquiries/<inquiryId>/begin-investigation", methods=["POST"])
def begin_investigation(unitId, inquiryId):
    uid, role = require_roles("CustomerServiceRep")
    i = get_nested_inquiry(unitId, inquiryId)
    check_state("inquiry", i, {"OPEN"})
    i["status"] = "INVESTIGATING"
    touch(i)
    _mark_status_change(i)
    return ok(deepcopy(i))


@app.route("/api/delivery-units/<unitId>/inquiries/<inquiryId>/resolve", methods=["POST"])
def resolve_inquiry(unitId, inquiryId):
    uid, role = require_roles("CustomerServiceRep")
    i = get_nested_inquiry(unitId, inquiryId)
    check_state("inquiry", i, {"INVESTIGATING"})
    body = get_body()
    code = body.get("resolution_code")
    if code not in RESOLUTION_CODES:
        raise err_invalid_request("invalid or missing resolution_code")
    i["resolution_code"] = code
    i["resolved_at"] = now_iso()
    if i["reopened_count"] >= 2:
        i["status"] = "RESOLVED_FINAL"
    else:
        i["status"] = "RESOLVED"
    touch(i)
    _mark_status_change(i)
    return ok(deepcopy(i))


@app.route("/api/delivery-units/<unitId>/inquiries/<inquiryId>/reopen", methods=["POST"])
def reopen_inquiry(unitId, inquiryId):
    uid, role = require_roles("CustomerServiceRep")
    i = get_nested_inquiry(unitId, inquiryId)
    check_state("inquiry", i, {"RESOLVED"})
    resolved_at = parse_datetime_iso(i["resolved_at"]) if i.get("resolved_at") else None
    if resolved_at is None:
        raise err_invalid_state("no resolution timestamp")
    if (current_dt() - resolved_at).total_seconds() > 14 * 86400:
        raise err_reopen_window("reopen window expired")
    i["status"] = "OPEN"
    i["reopened_count"] += 1
    i["resolved_at"] = None
    touch(i)
    _mark_status_change(i)
    return ok(deepcopy(i))


@app.route("/api/inquiries", methods=["GET"])
def list_inquiries_flat():
    uid, role = require_roles("CustomerServiceRep", "Postmaster", "PlatformAdmin")
    items = list(DB["inquiries"].values())
    for k in ("delivery_unit_id", "delivery_point_id", "related_scan_event_id", "status", "inquiry_kind"):
        v = request.args.get(k)
        if v:
            items = [i for i in items if i.get(k) == v]
    return list_response([deepcopy(i) for i in items])


@app.route("/api/inquiries/<inquiryId>", methods=["GET"])
def get_inquiry_flat(inquiryId):
    uid, role = require_roles("CustomerServiceRep", "Postmaster", "PlatformAdmin")
    i = get_inquiry_or_404(inquiryId)
    return ok(deepcopy(i))


# ===========================================================================
# Main
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
