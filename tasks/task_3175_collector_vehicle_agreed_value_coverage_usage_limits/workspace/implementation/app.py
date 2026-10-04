"""Collector Vehicle Agreed-Value Coverage & Usage Limits API.

Implements PRD.md for task_3175. In-memory store; logical clock test-driving;
envelope per scaffold response_envelope. Python + Flask.
"""

import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Store (empty at boot -- no seeding)
# ---------------------------------------------------------------------------

db = {
    "members": {},
    "vehicles": {},
    "photos": {},
    "guides": {},
    "guide_entries": {},
    "appraisals": {},
    "auction_results": {},
    "valuations": {},
    "policies": {},
    "drivers": {},
    "usage_events": {},
    "repair_shops": {},
    "claims": {},
    "restoration_projects": {},
    "receipts": {},
    "club_memberships": {},
    "club_events": {},
    "event_registrations": {},
    "roadside_events": {},
}

ROLES = {"Member", "Underwriter", "Appraiser", "ClaimsAdjuster", "ClubCoordinator", "PlatformAdmin"}

REQUIRED_PHOTO_TYPES = [
    "FRONT", "REAR", "DRIVER_SIDE", "PASSENGER_SIDE", "INTERIOR", "ENGINE", "ODOMETER", "VIN_PLATE",
]

VEHICLE_CLASSES = ["ANTIQUE", "CLASSIC", "MODERN_COLLECTIBLE", "EXOTIC"]
CONDITION_GRADES = ["EXCELLENT", "GOOD", "FAIR", "PROJECT"]
STORAGE_TYPES = ["ENCLOSED_GARAGE", "CARPORT", "OUTDOOR"]
PRIMARY_USES = ["SHOW", "PLEASURE", "RESTORATION"]
DRIVING_RECORDS = ["CLEAN", "MINOR_VIOLATIONS", "MAJOR_VIOLATIONS"]
USAGE_TIERS = ["LIMITED", "REGULAR", "EXTENDED"]
EVENT_KINDS = ["ORDINARY", "CLUB_EVENT", "PARADE", "EXHIBITION"]
LOSS_TYPES = ["COLLISION", "THEFT", "FIRE", "VANDALISM", "WEATHER"]
SERVICE_TYPES = ["FLATBED_TOW", "BATTERY", "FUEL", "LOCKOUT"]
CLUB_TIERS = ["BASIC", "ENTHUSIAST", "CONCOURS"]
VALUATION_METHODS = ["GUIDE_TOOL", "CERTIFIED_APPRAISAL", "AUCTION_COMPOSITE"]

AGE_MIN = {"ANTIQUE": 45, "CLASSIC": 25, "MODERN_COLLECTIBLE": 15, "EXOTIC": 10}
CONDITION_MULT = {"EXCELLENT": Decimal("1.25"), "GOOD": Decimal("1.00"),
                  "FAIR": Decimal("0.75"), "PROJECT": Decimal("0.50")}
USAGE_MULT = {"LIMITED": Decimal("0.85"), "REGULAR": Decimal("1.00"), "EXTENDED": Decimal("1.20")}
STORAGE_MULT = {"ENCLOSED_GARAGE": Decimal("0.95"), "CARPORT": Decimal("1.00"),
                "OUTDOOR": Decimal("1.00")}
CLUB_MULT = {"CONCOURS": Decimal("0.90"), "ENTHUSIAST": Decimal("0.95"), "BASIC": Decimal("1.00")}
ROADSIDE_LIMIT = {"BASIC": 2, "ENTHUSIAST": 4, "CONCOURS": 6}
STAGE_ORDER = ["DISASSEMBLY", "BODYWORK", "MECHANICAL", "FINISH", "COMPLETE"]
STAGE_CAP = {"DISASSEMBLY": Decimal("0.10"), "BODYWORK": Decimal("0.25"),
             "MECHANICAL": Decimal("0.40"), "FINISH": Decimal("0.55")}

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_clock = {"now": datetime(2026, 9, 1, tzinfo=timezone.utc)}


def clock_now():
    return _clock["now"]


def parse_dt(value):
    """Parse an ISO-8601 datetime string. Raises ApiError(400) on failure."""
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", "Expected an ISO 8601 datetime string", 400)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "Invalid ISO 8601 datetime: %s" % value, 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_iso():
    """Wall-clock timestamp with 3 fractional digits, for meta/created_at/updated_at."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (datetime.now(timezone.utc).microsecond // 1000)


def ts():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (n.microsecond // 1000)


def iso_of(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def round_half_up(x):
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Errors and envelope
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": {"api_request_id": "req_" + uuid.uuid4().hex[:24],
                 "api_request_timestamp": ts()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return handle_api_error(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(405)
def handle_405(e):
    return handle_api_error(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


def respond(data, code=200):
    body = {
        "meta": {"api_request_id": "req_" + uuid.uuid4().hex[:24],
                 "api_request_timestamp": ts()},
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), code


def parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "limit and offset must be integers", 400)
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100", 400)
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset must be >= 0", 400)
    return limit, offset


def respond_list(items, code=200):
    items = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:24],
            "api_request_timestamp": ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + limit) < total,
        },
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), code


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def role():
    r = request.headers.get("X-User-Role")
    if r not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header missing or not a declared role", 401)
    return r


def user_id():
    return request.headers.get("X-User-ID")


def require_role(*roles):
    r = role()
    if r not in roles:
        raise ApiError("ERR_FORBIDDEN", "Role %s is not permitted for this endpoint" % r, 403)
    return r


def member_check(owner_member_id):
    """Entity-backed role check for Member on member-owned resources."""
    r = role()
    if r == "Member":
        if user_id() != owner_member_id:
            raise ApiError("ERR_FORBIDDEN", "Member may act only on their own resources", 403)


def member_owns_via_vehicle(vehicle):
    member_check(vehicle["member_id"])


def member_owns_via_policy(policy):
    member_check(policy["member_id"])


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object", 400)
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object", 400)
    return data


def req_str(data, name):
    v = data.get(name)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", "Field %s is required and must be a string" % name, 400)
    return v


def opt_str(data, name):
    v = data.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", "Field %s must be a string" % name, 400)
    return v


def req_int(data, name):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Field %s is required and must be an integer" % name, 400)
    return v


def opt_int(data, name, default=None):
    v = data.get(name)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer" % name, 400)
    return v


def req_bool(data, name):
    v = data.get(name)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", "Field %s is required and must be a boolean" % name, 400)
    return v


def opt_bool(data, name, default=None):
    v = data.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", "Field %s must be a boolean" % name, 400)
    return v


def req_enum(data, name, allowed):
    v = data.get(name)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", "Field %s must be one of %s" % (name, allowed), 400)
    return v


def req_dt(data, name):
    return parse_dt(req_str(data, name))


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------

def new_entity():
    now = ts()
    return {"id": str(uuid.uuid4()), "created_at": now, "updated_at": now, "version": 1}


def touch(rec):
    rec["updated_at"] = ts()
    rec["version"] = rec.get("version", 1) + 1


def get_or_404(store, key):
    rec = db[store].get(key)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "%s not found: %s" % (store, key), 404)
    return rec


def ref_or_422(store, key, field):
    if key is None or key not in db[store]:
        raise ApiError("ERR_REFERENCED_NOT_FOUND", "Referenced %s not found: %s" % (field, key), 422)
    return db[store][key]


# ---------------------------------------------------------------------------
# Derived recomputations
# ---------------------------------------------------------------------------

def compute_eligibility(v):
    age = clock_now().year - v["year"]
    reasons = []
    if age < AGE_MIN[v["vehicle_class"]]:
        reasons.append("AGE")
    if v["storage_type"] == "OUTDOOR":
        reasons.append("STORAGE")
    if v["condition_grade"] == "PROJECT" and v["primary_use"] != "RESTORATION":
        reasons.append("CONDITION")
    v["eligibility_reasons"] = reasons
    v["eligibility_status"] = "ELIGIBLE" if not reasons else "INELIGIBLE"


def recompute_documentation(v):
    accepted_types = {
        p["photo_type"] for p in db["photos"].values()
        if p["vehicle_id"] == v["id"] and p["status"] == "ACCEPTED"
    }
    v["accepted_photo_count"] = len(accepted_types)
    v["documentation_status"] = (
        "COMPLETE" if all(t in accepted_types for t in REQUIRED_PHOTO_TYPES) else "INCOMPLETE"
    )
    touch(v)


def valuation_stale(val):
    if val["status"] != "APPROVED":
        return False
    if val.get("guide_id"):
        g = db["guides"].get(val["guide_id"])
        if g and g["status"] == "SUPERSEDED":
            return True
    approved_at = val.get("approved_at")
    if approved_at and clock_now() > parse_dt(approved_at) + timedelta(days=365):
        return True
    return False


def sync_vehicle_current_valuation(v):
    cur = None
    if v.get("current_valuation_id"):
        cand = db["valuations"].get(v["current_valuation_id"])
        if cand and cand["status"] == "APPROVED" and not cand["is_stale"]:
            cur = cand
    if cur is None:
        approved = [x for x in db["valuations"].values()
                    if x["vehicle_id"] == v["id"] and x["status"] == "APPROVED" and not x["is_stale"]]
        cur = approved[-1] if approved else None
    v["current_valuation_id"] = cur["id"] if cur else None
    v["current_agreed_value_cents"] = cur["final_agreed_value_cents"] if cur else None


def active_club_membership(member_id):
    for m in db["club_memberships"].values():
        if m["member_id"] == member_id and m["status"] == "ACTIVE":
            return m
    return None


def active_restoration_for_policy(policy_id):
    for rp in db["restoration_projects"].values():
        if rp["policy_id"] == policy_id and rp["status"] == "ACTIVE":
            return rp
    return None


def recompute_premium(policy):
    vehicle = db["vehicles"][policy["vehicle_id"]]
    base = policy["coverage_limit_cents"]
    t1 = round_half_up(min(base, 5000000) * Decimal("0.009"))
    t2 = round_half_up(max(0, min(base, 15000000) - 5000000) * Decimal("0.007"))
    t3 = round_half_up(max(0, base - 15000000) * Decimal("0.0055"))
    tiered_base = t1 + t2 + t3
    memb = active_club_membership(policy["member_id"])
    club = CLUB_MULT[memb["tier"]] if memb else Decimal("1.00")
    core = round_half_up(Decimal(tiered_base) * USAGE_MULT[policy["usage_tier"]]
                         * STORAGE_MULT[vehicle["storage_type"]] * club)
    endorsement_fee = round_half_up(policy["endorsement_limit_cents"] * Decimal("0.01"))
    policy["premium_cents"] = core + endorsement_fee


def recompute_endorsement(project):
    """Pinned order: receipts total -> stage cap -> endorsement -> policy coverage -> premium."""
    policy = db["policies"][project["policy_id"]]
    receipts_total = sum(r["amount_cents"] for r in db["receipts"].values()
                         if r["project_id"] == project["id"])
    project["receipts_total_cents"] = receipts_total
    if project["status"] == "ACTIVE" and project["stage"] in STAGE_CAP:
        cap = int((Decimal(policy["agreed_value_cents"]) * STAGE_CAP[project["stage"]])
                  .quantize(Decimal("1"), rounding=ROUND_FLOOR))
        project["endorsement_limit_cents"] = min(receipts_total, cap)
    else:
        project["endorsement_limit_cents"] = 0
    policy["endorsement_limit_cents"] = project["endorsement_limit_cents"]
    policy["coverage_limit_cents"] = policy["agreed_value_cents"] + project["endorsement_limit_cents"]
    recompute_premium(policy)
    touch(policy)
    touch(project)


def policy_events_chronological(policy_id):
    events = [e for e in db["usage_events"].values()
              if e["policy_id"] == policy_id and e["status"] == "RECORDED"]
    events.sort(key=lambda e: (e["event_date"], e["created_at"], e["id"]))
    return events


def recompute_ledger(policy):
    events = policy_events_chronological(policy["id"])
    allowance = policy["annual_mileage_allowance"]
    cumulative = 0
    total_overage = 0
    for e in events:
        e["billable_miles"] = e["reported_miles"] if e["event_kind"] == "ORDINARY" else 0
        c_before = cumulative
        cumulative += e["billable_miles"]
        overage_miles = max(0, cumulative - allowance) - max(0, c_before - allowance)
        e["overage_charge_cents"] = round_half_up(overage_miles * Decimal("12.5"))
        total_overage += e["overage_charge_cents"]
    policy["billable_miles_used"] = cumulative
    policy["overage_charge_cents"] = total_overage
    policy["remaining_allowance_miles"] = allowance - cumulative


def recompute_event_count(event):
    count = sum(1 for r in db["event_registrations"].values()
                if r["event_id"] == event["id"] and r["status"] == "REGISTERED")
    if event["registered_count"] != count:
        event["registered_count"] = count
        touch(event)


def recompute_roadside_used(memb):
    count = sum(1 for e in db["roadside_events"].values()
                if e["membership_id"] == memb["id"] and e["status"] in ("DISPATCHED", "COMPLETED"))
    if memb["roadside_calls_used"] != count:
        memb["roadside_calls_used"] = count
        touch(memb)


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------

@app.post("/_clock/set_current_utc")
def set_clock():
    require_role("PlatformAdmin")
    data = body()
    to = parse_dt(req_str(data, "to_iso8601"))
    _clock["now"] = to
    # stale valuations by age
    for val in db["valuations"].values():
        if val["status"] == "APPROVED" and not val["is_stale"]:
            if valuation_stale(val):
                val["is_stale"] = True
                val["status"] = "STALE"
                touch(val)
    # cascade: ACTIVE policies pinned to newly stale valuations -> UNDER_REVIEW
    for pol in db["policies"].values():
        if pol["status"] == "ACTIVE":
            val = db["valuations"].get(pol["valuation_id"])
            if val and (val["status"] == "STALE" or val["is_stale"]):
                pol["status"] = "UNDER_REVIEW"
                touch(pol)
    # vehicle current valuation resync
    for v in db["vehicles"].values():
        before = (v.get("current_valuation_id"), v.get("current_agreed_value_cents"))
        sync_vehicle_current_valuation(v)
        after = (v.get("current_valuation_id"), v.get("current_agreed_value_cents"))
        if before != after:
            touch(v)
    # lapse policies whose period_end has been reached
    for pol in db["policies"].values():
        if pol["status"] == "ACTIVE" and to >= parse_dt(pol["period_end"]):
            pol["status"] = "LAPSED"
            touch(pol)
    return respond({"current_utc": iso_of(to)})


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

def member_view(m):
    return dict(m)


@app.post("/members")
def create_member():
    require_role("PlatformAdmin")
    data = body()
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    has_daily_driver = req_bool(data, "has_daily_driver")
    desc = opt_str(data, "daily_driver_vehicle_desc")
    record = req_enum(data, "driving_record_status", DRIVING_RECORDS)
    for m in db["members"].values():
        if m["email"] == email:
            raise ApiError("ERR_VALIDATION", "A member with this email already exists", 400)
    m = new_entity()
    m.update({
        "full_name": full_name,
        "email": email,
        "has_daily_driver": has_daily_driver,
        "daily_driver_vehicle_desc": desc,
        "driving_record_status": record,
        "status": "ACTIVE",
    })
    db["members"][m["id"]] = m
    return respond(member_view(m), 201)


@app.get("/members")
def list_members():
    require_role("PlatformAdmin", "Underwriter", "ClaimsAdjuster", "ClubCoordinator")
    items = list(db["members"].values())
    status = request.args.get("status")
    if status:
        items = [m for m in items if m["status"] == status]
    return respond_list(items)


@app.get("/members/<mid>")
def get_member(mid):
    m = get_or_404("members", mid)
    require_role("PlatformAdmin", "Underwriter", "ClaimsAdjuster", "ClubCoordinator", "Member")
    member_check(m["id"])
    return respond(member_view(m))


@app.patch("/members/<mid>")
def patch_member(mid):
    require_role("PlatformAdmin")
    m = get_or_404("members", mid)
    data = body()
    changed = False
    if "driving_record_status" in data:
        v = data["driving_record_status"]
        if v not in DRIVING_RECORDS:
            raise ApiError("ERR_VALIDATION", "Invalid driving_record_status", 400)
        m["driving_record_status"] = v
        changed = True
    if "has_daily_driver" in data:
        m["has_daily_driver"] = opt_bool(data, "has_daily_driver")
        changed = True
    if "daily_driver_vehicle_desc" in data:
        m["daily_driver_vehicle_desc"] = opt_str(data, "daily_driver_vehicle_desc")
        changed = True
    if "status" in data:
        new_status = data["status"]
        if new_status not in ("ACTIVE", "SUSPENDED", "TERMINATED"):
            raise ApiError("ERR_VALIDATION", "Invalid status", 400)
        cur = m["status"]
        allowed = {
            "ACTIVE": {"SUSPENDED", "TERMINATED"},
            "SUSPENDED": {"ACTIVE", "TERMINATED"},
            "TERMINATED": set(),
        }
        if new_status != cur:
            if new_status not in allowed.get(cur, set()):
                raise ApiError("ERR_INVALID_STATE",
                               "Cannot transition member from %s to %s" % (cur, new_status), 409)
            if new_status == "TERMINATED":
                for pol in db["policies"].values():
                    if pol["member_id"] == m["id"] and pol["status"] in ("ACTIVE", "UNDER_REVIEW", "SUSPENDED"):
                        raise ApiError("ERR_INVALID_STATE",
                                       "Member has policies in ACTIVE/UNDER_REVIEW/SUSPENDED", 409)
            m["status"] = new_status
            changed = True
            if new_status == "TERMINATED":
                for cm in db["club_memberships"].values():
                    if cm["member_id"] == m["id"] and cm["status"] == "ACTIVE":
                        cm["status"] = "LAPSED"
                        touch(cm)
    if changed:
        touch(m)
    return respond(member_view(m))


@app.get("/members/<mid>/event-registrations")
def member_event_registrations(mid):
    m = get_or_404("members", mid)
    require_role("PlatformAdmin", "ClubCoordinator", "Member")
    member_check(m["id"])
    items = [r for r in db["event_registrations"].values() if r["member_id"] == m["id"]]
    return respond_list(items)


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------

def vehicle_view(v):
    return dict(v)


@app.post("/vehicles")
def create_vehicle():
    require_role("Member")
    mid = user_id()
    if not mid or mid not in db["members"]:
        raise ApiError("ERR_FORBIDDEN", "Acting member not found", 403)
    data = body()
    vin = req_str(data, "vin")
    year = req_int(data, "year")
    make = req_str(data, "make")
    model = req_str(data, "model")
    vehicle_class = req_enum(data, "vehicle_class", VEHICLE_CLASSES)
    condition_grade = req_enum(data, "condition_grade", CONDITION_GRADES)
    storage_type = req_enum(data, "storage_type", STORAGE_TYPES)
    primary_use = req_enum(data, "primary_use", PRIMARY_USES)
    for v in db["vehicles"].values():
        if v["vin"] == vin:
            raise ApiError("ERR_DUPLICATE_VIN", "A vehicle with this VIN already exists", 409)
    v = new_entity()
    v.update({
        "member_id": mid,
        "vin": vin,
        "year": year,
        "make": make,
        "model": model,
        "vehicle_class": vehicle_class,
        "condition_grade": condition_grade,
        "storage_type": storage_type,
        "primary_use": primary_use,
        "eligibility_status": "PENDING",
        "eligibility_reasons": [],
        "documentation_status": "INCOMPLETE",
        "accepted_photo_count": 0,
        "current_valuation_id": None,
        "current_agreed_value_cents": None,
        "status": "REGISTERED",
    })
    db["vehicles"][v["id"]] = v
    return respond(vehicle_view(v), 201)


@app.get("/vehicles")
def list_vehicles():
    require_role("PlatformAdmin", "Underwriter", "Appraiser", "ClaimsAdjuster", "Member")
    items = list(db["vehicles"].values())
    member_id = request.args.get("member_id")
    if member_id:
        items = [v for v in items if v["member_id"] == member_id]
    if role() == "Member":
        items = [v for v in items if v["member_id"] == user_id()]
    return respond_list(items)


@app.get("/vehicles/<vid>")
def get_vehicle(vid):
    v = get_or_404("vehicles", vid)
    require_role("PlatformAdmin", "Underwriter", "Appraiser", "ClaimsAdjuster", "Member")
    if role() == "Member":
        member_check(v["member_id"])
    return respond(vehicle_view(v))


@app.post("/vehicles/<vid>/evaluate-eligibility")
def evaluate_eligibility(vid):
    require_role("Underwriter", "PlatformAdmin")
    v = get_or_404("vehicles", vid)
    compute_eligibility(v)
    touch(v)
    return respond(vehicle_view(v))


# --- Photos ---

@app.post("/vehicles/<vid>/photos")
def submit_photo(vid):
    require_role("Member")
    v = get_or_404("vehicles", vid)
    member_owns_via_vehicle(v)
    data = body()
    photo_type = req_enum(data, "photo_type", REQUIRED_PHOTO_TYPES)
    image_ref = req_str(data, "image_ref")
    captured = req_dt(data, "captured_at")
    for p in db["photos"].values():
        if p["vehicle_id"] == v["id"] and p["photo_type"] == photo_type \
                and p["status"] in ("SUBMITTED", "ACCEPTED"):
            raise ApiError("ERR_PHOTO_TYPE_DUPLICATE",
                           "A SUBMITTED or ACCEPTED photo of this type already exists", 409)
    p = new_entity()
    p.update({
        "vehicle_id": v["id"],
        "photo_type": photo_type,
        "image_ref": image_ref,
        "captured_at": iso_of(captured),
        "status": "SUBMITTED",
        "review_note": None,
    })
    db["photos"][p["id"]] = p
    recompute_documentation(v)
    return respond(dict(p), 201)


@app.get("/vehicles/<vid>/photos")
def list_photos(vid):
    v = get_or_404("vehicles", vid)
    require_role("PlatformAdmin", "Underwriter", "Member")
    if role() == "Member":
        member_owns_via_vehicle(v)
    items = [p for p in db["photos"].values() if p["vehicle_id"] == v["id"]]
    return respond_list(items)


@app.post("/vehicles/<vid>/photos/<pid>/review")
def review_photo(vid, pid):
    require_role("Underwriter")
    v = get_or_404("vehicles", vid)
    p = get_or_404("photos", pid)
    if p["vehicle_id"] != v["id"]:
        raise ApiError("ERR_NOT_FOUND", "Photo not found under this vehicle", 404)
    if p["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Photo is not in SUBMITTED status", 409)
    data = body()
    decision = req_enum(data, "decision", ["ACCEPT", "REJECT"])
    note = opt_str(data, "review_note")
    was_complete = v["documentation_status"] == "COMPLETE"
    p["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    p["review_note"] = note
    touch(p)
    recompute_documentation(v)
    now_complete = v["documentation_status"] == "COMPLETE"
    if now_complete and not was_complete:
        for pol in db["policies"].values():
            if pol["vehicle_id"] == v["id"] and pol["status"] == "PENDING_DOCUMENTS":
                pol["status"] = "QUOTED"
                touch(pol)
    return respond(dict(p))


# ---------------------------------------------------------------------------
# Valuation guides
# ---------------------------------------------------------------------------

@app.post("/valuation-guides")
def create_guide():
    require_role("PlatformAdmin")
    data = body()
    edition = req_str(data, "edition")
    effective = req_dt(data, "effective_date")
    for g in db["guides"].values():
        if g["edition"] == edition:
            raise ApiError("ERR_DUPLICATE_EDITION",
                           "A valuation guide with this edition already exists", 409)
    g = new_entity()
    g.update({"edition": edition, "effective_date": iso_of(effective), "status": "DRAFT"})
    db["guides"][g["id"]] = g
    return respond(dict(g), 201)


@app.get("/valuation-guides/<gid>")
def get_guide(gid):
    require_role("PlatformAdmin", "Underwriter")
    g = get_or_404("guides", gid)
    return respond(dict(g))


@app.post("/valuation-guides/<gid>/entries")
def add_guide_entry(gid):
    require_role("PlatformAdmin")
    g = get_or_404("guides", gid)
    if g["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Entries may be added to DRAFT guides only", 409)
    data = body()
    vehicle_class = req_enum(data, "vehicle_class", VEHICLE_CLASSES)
    make = req_str(data, "make")
    year_min = req_int(data, "year_min")
    year_max = req_int(data, "year_max")
    base_value = req_int(data, "base_value_cents")
    e = new_entity()
    e.update({
        "guide_id": g["id"],
        "vehicle_class": vehicle_class,
        "make": make,
        "year_min": year_min,
        "year_max": year_max,
        "base_value_cents": base_value,
    })
    db["guide_entries"][e["id"]] = e
    return respond(dict(e), 201)


@app.get("/valuation-guides/<gid>/entries")
def list_guide_entries(gid):
    require_role("PlatformAdmin", "Underwriter")
    g = get_or_404("guides", gid)
    items = [e for e in db["guide_entries"].values() if e["guide_id"] == g["id"]]
    return respond_list(items)


@app.post("/valuation-guides/<gid>/publish")
def publish_guide(gid):
    require_role("PlatformAdmin")
    g = get_or_404("guides", gid)
    if g["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only DRAFT guides can be published", 409)
    entries = [e for e in db["guide_entries"].values() if e["guide_id"] == g["id"]]
    if not entries:
        raise ApiError("ERR_INVALID_STATE", "A guide with no entries cannot be published", 409)
    # Link 1: prior PUBLISHED -> SUPERSEDED
    superseded = []
    for other in db["guides"].values():
        if other["id"] != g["id"] and other["status"] == "PUBLISHED":
            other["status"] = "SUPERSEDED"
            touch(other)
            superseded.append(other["id"])
    g["status"] = "PUBLISHED"
    touch(g)
    # Link 2: GUIDE_TOOL valuations pinned to superseded guide, APPROVED -> STALE
    for val in db["valuations"].values():
        if val["status"] == "APPROVED" and val.get("guide_id") in superseded \
                and val["method"] == "GUIDE_TOOL":
            val["status"] = "STALE"
            val["is_stale"] = True
            touch(val)
    # Link 3: ACTIVE policies pinned to newly STALE valuations -> UNDER_REVIEW
    for pol in db["policies"].values():
        if pol["status"] == "ACTIVE":
            val = db["valuations"].get(pol["valuation_id"])
            if val and val["status"] == "STALE":
                pol["status"] = "UNDER_REVIEW"
                touch(pol)
    for v in db["vehicles"].values():
        before = (v.get("current_valuation_id"), v.get("current_agreed_value_cents"))
        sync_vehicle_current_valuation(v)
        if before != (v.get("current_valuation_id"), v.get("current_agreed_value_cents")):
            touch(v)
    return respond(dict(g))


# ---------------------------------------------------------------------------
# Appraisals
# ---------------------------------------------------------------------------

@app.post("/vehicles/<vid>/appraisals")
def submit_appraisal(vid):
    require_role("Appraiser")
    v = get_or_404("vehicles", vid)
    data = body()
    value = req_int(data, "appraised_value_cents")
    appraised_at = req_dt(data, "appraised_at")
    a = new_entity()
    a.update({
        "vehicle_id": v["id"],
        "appraiser_user_id": user_id(),
        "appraised_value_cents": value,
        "appraised_at": iso_of(appraised_at),
        "status": "SUBMITTED",
    })
    db["appraisals"][a["id"]] = a
    return respond(dict(a), 201)


@app.get("/vehicles/<vid>/appraisals")
def list_appraisals(vid):
    v = get_or_404("vehicles", vid)
    require_role("PlatformAdmin", "Underwriter", "Appraiser", "Member")
    if role() == "Member":
        member_owns_via_vehicle(v)
    items = [a for a in db["appraisals"].values() if a["vehicle_id"] == v["id"]]
    return respond_list(items)


@app.post("/appraisals/<aid>/certify")
def certify_appraisal(aid):
    require_role("Underwriter")
    a = get_or_404("appraisals", aid)
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Appraisal is not in SUBMITTED status", 409)
    if user_id() == a["appraiser_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION",
                       "Appraiser cannot certify their own appraisal", 403)
    data = body()
    decision = req_enum(data, "decision", ["CERTIFY", "REJECT"])
    a["status"] = "CERTIFIED" if decision == "CERTIFY" else "REJECTED"
    touch(a)
    return respond(dict(a))


# ---------------------------------------------------------------------------
# Auction results
# ---------------------------------------------------------------------------

@app.post("/auction-results")
def create_auction_result():
    require_role("PlatformAdmin")
    data = body()
    r = new_entity()
    r.update({
        "vehicle_class": req_enum(data, "vehicle_class", VEHICLE_CLASSES),
        "make": req_str(data, "make"),
        "model": req_str(data, "model"),
        "year": req_int(data, "year"),
        "sale_price_cents": req_int(data, "sale_price_cents"),
        "sale_date": iso_of(req_dt(data, "sale_date")),
        "source_name": req_str(data, "source_name"),
    })
    db["auction_results"][r["id"]] = r
    return respond(dict(r), 201)


@app.get("/auction-results")
def list_auction_results():
    require_role("PlatformAdmin", "Underwriter")
    items = list(db["auction_results"].values())
    vc = request.args.get("vehicle_class")
    make = request.args.get("make")
    if vc:
        items = [r for r in items if r["vehicle_class"] == vc]
    if make:
        items = [r for r in items if r["make"] == make]
    return respond_list(items)


# ---------------------------------------------------------------------------
# Valuations
# ---------------------------------------------------------------------------

def compute_valuation_value(v, method, appraisal_id):
    """Returns (computed_value_cents, guide_id or None). May raise."""
    if method == "GUIDE_TOOL":
        published = [g for g in db["guides"].values() if g["status"] == "PUBLISHED"]
        if not published:
            raise ApiError("ERR_NOT_FOUND", "No PUBLISHED valuation guide exists", 404)
        guide = sorted(published, key=lambda g: g["created_at"])[-1]
        matches = [e for e in db["guide_entries"].values()
                   if e["guide_id"] == guide["id"]
                   and e["vehicle_class"] == v["vehicle_class"]
                   and e["make"] == v["make"]
                   and e["year_min"] <= v["year"] <= e["year_max"]]
        if not matches:
            raise ApiError("ERR_NOT_FOUND", "No guide entry matches this vehicle", 404)
        matches.sort(key=lambda e: (e["year_max"] - e["year_min"], e["created_at"]))
        entry = matches[0]
        value = round_half_up(entry["base_value_cents"] * CONDITION_MULT[v["condition_grade"]])
        return value, guide["id"]
    if method == "CERTIFIED_APPRAISAL":
        appraisal = ref_or_422("appraisals", appraisal_id, "appraisal_id")
        if appraisal["vehicle_id"] != v["id"]:
            raise ApiError("ERR_REFERENCED_NOT_FOUND",
                           "Referenced appraisal does not belong to this vehicle", 422)
        if appraisal["status"] != "CERTIFIED":
            raise ApiError("ERR_APPRAISAL_NOT_CERTIFIED",
                           "Referenced appraisal is not CERTIFIED", 409)
        return appraisal["appraised_value_cents"], None
    if method == "AUCTION_COMPOSITE":
        now = clock_now()
        window_start = now - timedelta(days=730)
        comps = [r for r in db["auction_results"].values()
                 if r["vehicle_class"] == v["vehicle_class"] and r["make"] == v["make"]
                 and window_start <= parse_dt(r["sale_date"]) <= now]
        comps.sort(key=lambda r: (r["sale_date"], r["created_at"]), reverse=True)
        comps = comps[:5]
        if len(comps) < 3:
            raise ApiError("ERR_AUCTION_COMPS_INSUFFICIENT",
                           "Fewer than 3 auction comps within the 730-day window", 422)
        prices = [r["sale_price_cents"] for r in comps]
        if len(prices) >= 4:
            prices.remove(max(prices))
            prices.remove(min(prices))
        mean = Decimal(sum(prices)) / Decimal(len(prices))
        return int(mean.quantize(Decimal("1"), rounding=ROUND_HALF_UP)), None
    raise ApiError("ERR_VALIDATION", "Unknown valuation method", 400)


def valuation_view(val):
    return dict(val)


@app.post("/vehicles/<vid>/valuations")
def create_valuation(vid):
    require_role("Underwriter")
    v = get_or_404("vehicles", vid)
    data = body()
    method = req_enum(data, "method", VALUATION_METHODS)
    proposed = req_int(data, "proposed_agreed_value_cents")
    band_override = opt_bool(data, "band_override", False)
    appraisal_id = opt_str(data, "appraisal_id")
    if method == "CERTIFIED_APPRAISAL" and not appraisal_id:
        raise ApiError("ERR_REFERENCED_NOT_FOUND",
                       "appraisal_id is required for CERTIFIED_APPRAISAL", 422)
    # OCC check
    expected = data.get("expected_vehicle_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise ApiError("ERR_VALIDATION", "expected_vehicle_version must be an integer", 400)
        if expected != v["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_vehicle_version does not match the vehicle's current version",
                           412)
    computed, guide_id = compute_valuation_value(v, method, appraisal_id)
    val = new_entity()
    val.update({
        "vehicle_id": v["id"],
        "method": method,
        "appraisal_id": appraisal_id,
        "guide_id": guide_id,
        "computed_value_cents": computed,
        "proposed_agreed_value_cents": proposed,
        "final_agreed_value_cents": None,
        "band_override": band_override,
        "status": "DRAFT",
        "approved_by_user_id": None,
        "approved_at": None,
        "is_stale": False,
    })
    db["valuations"][val["id"]] = val
    touch(v)
    return respond(valuation_view(val), 201)


@app.get("/vehicles/<vid>/valuations")
def list_vehicle_valuations(vid):
    v = get_or_404("vehicles", vid)
    require_role("PlatformAdmin", "Underwriter", "Member")
    if role() == "Member":
        member_owns_via_vehicle(v)
    items = [x for x in db["valuations"].values() if x["vehicle_id"] == v["id"]]
    return respond_list(items)


@app.get("/valuations/<val_id>")
def get_valuation(val_id):
    val = get_or_404("valuations", val_id)
    require_role("PlatformAdmin", "Underwriter", "Member")
    if role() == "Member":
        v = db["vehicles"][val["vehicle_id"]]
        member_owns_via_vehicle(v)
    return respond(valuation_view(val))


@app.get("/valuations")
def list_valuations():
    require_role("PlatformAdmin", "Underwriter")
    items = list(db["valuations"].values())
    for key in ("vehicle_id", "appraisal_id", "guide_id"):
        q = request.args.get(key)
        if q:
            items = [x for x in items if x.get(key) == q]
    return respond_list(items)


@app.post("/valuations/<val_id>/propose")
def propose_valuation(val_id):
    require_role("Underwriter")
    val = get_or_404("valuations", val_id)
    if val["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only DRAFT valuations can be proposed", 409)
    if val["computed_value_cents"] is None:
        raise ApiError("ERR_AUCTION_COMPS_INSUFFICIENT",
                       "computed_value_cents has not been derived", 422)
    val["status"] = "PROPOSED"
    touch(val)
    return respond(valuation_view(val))


@app.post("/valuations/<val_id>/revise")
def revise_valuation(val_id):
    require_role("Underwriter")
    val = get_or_404("valuations", val_id)
    if val["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "Only PROPOSED valuations can be revised", 409)
    data = body()
    new_prop = opt_int(data, "proposed_agreed_value_cents")
    if new_prop is not None:
        val["proposed_agreed_value_cents"] = new_prop
    val["status"] = "DRAFT"
    touch(val)
    return respond(valuation_view(val))


@app.post("/valuations/<val_id>/approve")
def approve_valuation(val_id):
    require_role("Underwriter")
    val = get_or_404("valuations", val_id)
    if val["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "Only PROPOSED valuations can be approved", 409)
    data = body()
    if "band_override" in data:
        bo = opt_bool(data, "band_override")
        if bo is not None:
            val["band_override"] = bo
    # SoD (priority 6) precedes certified linkage (priority 9) and the band (17)
    appraisal = None
    if val["method"] == "CERTIFIED_APPRAISAL":
        appraisal = db["appraisals"].get(val["appraisal_id"])
        if appraisal and user_id() == appraisal["appraiser_user_id"]:
            raise ApiError("ERR_SOD_VIOLATION",
                           "Appraiser cannot approve their own appraisal valuation", 403)
    if val["method"] == "CERTIFIED_APPRAISAL":
        if appraisal is None or appraisal["status"] != "CERTIFIED":
            raise ApiError("ERR_APPRAISAL_NOT_CERTIFIED",
                           "Linked appraisal is not CERTIFIED", 409)
    # sanity band
    computed = val["computed_value_cents"]
    band = round_half_up(Decimal(computed) * Decimal("0.20"))
    if not val["band_override"]:
        if abs(val["proposed_agreed_value_cents"] - computed) > band:
            raise ApiError("ERR_APPRAISAL_OUT_OF_BAND",
                           "Proposed agreed value outside the +/-20% sanity band", 422)
    val["status"] = "APPROVED"
    val["final_agreed_value_cents"] = val["proposed_agreed_value_cents"]
    val["approved_by_user_id"] = user_id()
    val["approved_at"] = iso_of(clock_now())
    val["is_stale"] = valuation_stale(val)
    touch(val)
    v = db["vehicles"][val["vehicle_id"]]
    for other in db["valuations"].values():
        if other["vehicle_id"] == v["id"] and other["id"] != val["id"] \
                and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            touch(other)
    sync_vehicle_current_valuation(v)
    touch(v)
    return respond(valuation_view(val))


@app.post("/valuations/<val_id>/reject")
def reject_valuation(val_id):
    require_role("Underwriter")
    val = get_or_404("valuations", val_id)
    if val["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "Only PROPOSED valuations can be rejected", 409)
    val["status"] = "REJECTED"
    touch(val)
    return respond(valuation_view(val))


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

def policy_view(p):
    return dict(p)


def check_period_overlap(vehicle_id, start, end):
    for pol in db["policies"].values():
        if pol["vehicle_id"] != vehicle_id or pol["status"] == "CANCELLED":
            continue
        ps = parse_dt(pol["period_start"])
        pe = parse_dt(pol["period_end"])
        if ps < end and start < pe:
            raise ApiError("ERR_POLICY_PERIOD_OVERLAP",
                           "Vehicle already covered by a non-CANCELLED policy with an overlapping period",
                           409)


@app.post("/policies")
def create_policy():
    require_role("Underwriter")
    data = body()
    member_id = req_str(data, "member_id")
    vehicle_id = req_str(data, "vehicle_id")
    valuation_id = req_str(data, "valuation_id")
    usage_tier = req_enum(data, "usage_tier", USAGE_TIERS)
    allowance = opt_int(data, "annual_mileage_allowance", 3000)
    period_start = req_dt(data, "period_start")
    period_end = req_dt(data, "period_end")
    member = ref_or_422("members", member_id, "member_id")
    vehicle = ref_or_422("vehicles", vehicle_id, "vehicle_id")
    val = ref_or_422("valuations", valuation_id, "valuation_id")
    if val["vehicle_id"] != vehicle["id"]:
        raise ApiError("ERR_REFERENCED_NOT_FOUND",
                       "Referenced valuation does not belong to this vehicle", 422)
    if val["status"] != "APPROVED":
        raise ApiError("ERR_VALUATION_NOT_APPROVED", "Pinned valuation is not APPROVED", 409)
    check_period_overlap(vehicle["id"], period_start, period_end)
    p = new_entity()
    p.update({
        "member_id": member["id"],
        "vehicle_id": vehicle["id"],
        "valuation_id": val["id"],
        "usage_tier": usage_tier,
        "annual_mileage_allowance": allowance,
        "period_start": iso_of(period_start),
        "period_end": iso_of(period_end),
        "agreed_value_cents": val["final_agreed_value_cents"],
        "endorsement_limit_cents": 0,
        "coverage_limit_cents": val["final_agreed_value_cents"],
        "premium_cents": 0,
        "billable_miles_used": 0,
        "overage_charge_cents": 0,
        "remaining_allowance_miles": allowance,
        "status": "QUOTED",
    })
    if vehicle["documentation_status"] != "COMPLETE":
        p["status"] = "PENDING_DOCUMENTS"
    db["policies"][p["id"]] = p
    recompute_premium(p)
    return respond(policy_view(p), 201)


@app.get("/policies")
def list_policies():
    require_role("PlatformAdmin", "Underwriter", "ClaimsAdjuster", "Member")
    items = list(db["policies"].values())
    for key in ("member_id", "vehicle_id", "valuation_id", "status"):
        q = request.args.get(key)
        if q:
            items = [x for x in items if x.get(key) == q]
    if role() == "Member":
        items = [x for x in items if x["member_id"] == user_id()]
    return respond_list(items)


@app.get("/policies/<pid>")
def get_policy(pid):
    p = get_or_404("policies", pid)
    require_role("PlatformAdmin", "Underwriter", "ClaimsAdjuster", "Member")
    if role() == "Member":
        member_owns_via_policy(p)
    return respond(policy_view(p))


@app.patch("/policies/<pid>")
def repin_policy(pid):
    require_role("Underwriter")
    p = get_or_404("policies", pid)
    data = body()
    valuation_id = req_str(data, "valuation_id")
    val = ref_or_422("valuations", valuation_id, "valuation_id")
    if val["vehicle_id"] != p["vehicle_id"]:
        raise ApiError("ERR_REFERENCED_NOT_FOUND",
                       "Referenced valuation does not belong to this vehicle", 422)
    if val["status"] != "APPROVED":
        raise ApiError("ERR_VALUATION_NOT_APPROVED", "Pinned valuation is not APPROVED", 409)
    if val["is_stale"] or valuation_stale(val):
        raise ApiError("ERR_VALUATION_STALE", "Pinned valuation is STALE", 409)
    p["valuation_id"] = val["id"]
    p["agreed_value_cents"] = val["final_agreed_value_cents"]
    rp = active_restoration_for_policy(p["id"])
    p["endorsement_limit_cents"] = rp["endorsement_limit_cents"] if rp else 0
    p["coverage_limit_cents"] = p["agreed_value_cents"] + p["endorsement_limit_cents"]
    recompute_premium(p)
    touch(p)
    return respond(policy_view(p))


def activation_gates(p):
    vehicle = db["vehicles"][p["vehicle_id"]]
    member = db["members"][p["member_id"]]
    if vehicle["eligibility_status"] != "ELIGIBLE":
        raise ApiError("ERR_VEHICLE_INELIGIBLE", "Vehicle is not ELIGIBLE", 409)
    if vehicle["documentation_status"] != "COMPLETE":
        raise ApiError("ERR_DOCUMENTATION_INCOMPLETE",
                       "Vehicle documentation is not COMPLETE", 409)
    val = db["valuations"].get(p["valuation_id"])
    if val is None or val["status"] != "APPROVED":
        raise ApiError("ERR_VALUATION_NOT_APPROVED", "Pinned valuation is not APPROVED", 409)
    if val["is_stale"] or valuation_stale(val):
        raise ApiError("ERR_VALUATION_STALE", "Pinned valuation is STALE", 409)
    if not member["has_daily_driver"]:
        raise ApiError("ERR_NO_DAILY_DRIVER",
                       "Member must own or lease a separate daily driver", 422)
    if member["driving_record_status"] != "CLEAN":
        raise ApiError("ERR_RECORD_NOT_CLEAN", "Member driving record is not CLEAN", 422)
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", "Member is not ACTIVE", 409)
    listed = [d for d in db["drivers"].values()
              if d["policy_id"] == p["id"] and d["status"] == "LISTED"]
    if not listed:
        raise ApiError("ERR_DRIVER_INELIGIBLE",
                       "At least one driver must be LISTED on the policy", 422)
    return vehicle


@app.post("/policies/<pid>/activate")
def activate_policy(pid):
    require_role("Underwriter")
    p = get_or_404("policies", pid)
    if p["status"] not in ("QUOTED", "PENDING_DOCUMENTS"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only QUOTED or PENDING_DOCUMENTS policies can be activated", 409)
    vehicle = activation_gates(p)
    p["status"] = "ACTIVE"
    if vehicle["status"] == "REGISTERED":
        vehicle["status"] = "INSURED"
        touch(vehicle)
    recompute_premium(p)
    touch(p)
    return respond(policy_view(p))


@app.post("/policies/<pid>/begin-review")
def begin_review(pid):
    require_role("Underwriter")
    p = get_or_404("policies", pid)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only ACTIVE policies can enter review", 409)
    p["status"] = "UNDER_REVIEW"
    touch(p)
    return respond(policy_view(p))


@app.post("/policies/<pid>/resolve-review")
def resolve_review(pid):
    require_role("Underwriter")
    p = get_or_404("policies", pid)
    if p["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only UNDER_REVIEW policies can resolve review", 409)
    val = db["valuations"].get(p["valuation_id"])
    if val is None or val["status"] != "APPROVED":
        raise ApiError("ERR_VALUATION_NOT_APPROVED", "Pinned valuation is not APPROVED", 409)
    if val["is_stale"] or valuation_stale(val):
        raise ApiError("ERR_VALUATION_STALE", "Pinned valuation is STALE", 409)
    p["status"] = "ACTIVE"
    touch(p)
    return respond(policy_view(p))


@app.post("/policies/<pid>/suspend")
def suspend_policy(pid):
    require_role("Underwriter")
    p = get_or_404("policies", pid)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only ACTIVE policies can be suspended", 409)
    p["status"] = "SUSPENDED"
    touch(p)
    return respond(policy_view(p))


@app.post("/policies/<pid>/resume")
def resume_policy(pid):
    require_role("Underwriter")
    p = get_or_404("policies", pid)
    if p["status"] not in ("SUSPENDED", "LAPSED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only SUSPENDED or LAPSED policies can be resumed", 409)
    val = db["valuations"].get(p["valuation_id"])
    if val is None or val["status"] != "APPROVED" or val["is_stale"] or valuation_stale(val):
        raise ApiError("ERR_VALUATION_STALE", "Pinned valuation is STALE", 409)
    if p["status"] == "LAPSED":
        if clock_now() >= parse_dt(p["period_end"]) + timedelta(days=30):
            raise ApiError("ERR_INVALID_STATE",
                           "Reinstatement beyond the 30-day grace period", 409)
    p["status"] = "ACTIVE"
    touch(p)
    return respond(policy_view(p))


@app.post("/policies/<pid>/lapse")
def lapse_policy(pid):
    require_role("Underwriter")
    p = get_or_404("policies", pid)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only ACTIVE policies can be lapsed", 409)
    p["status"] = "LAPSED"
    touch(p)
    return respond(policy_view(p))


@app.post("/policies/<pid>/cancel")
def cancel_policy(pid):
    require_role("Underwriter", "Member")
    p = get_or_404("policies", pid)
    if role() == "Member":
        member_owns_via_policy(p)
    if p["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", "Policy is already CANCELLED", 409)
    was_active = p["status"] == "ACTIVE"
    p["status"] = "CANCELLED"
    if was_active:
        rp = active_restoration_for_policy(p["id"])
        if rp:
            rp["status"] = "SUSPENDED"
            recompute_endorsement(rp)
    touch(p)
    return respond(policy_view(p))


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------

@app.post("/policies/<pid>/drivers")
def add_driver(pid):
    require_role("Member")
    p = get_or_404("policies", pid)
    member_owns_via_policy(p)
    if p["status"] not in ("QUOTED", "PENDING_DOCUMENTS", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE",
                       "Drivers may be listed only while the policy is QUOTED, PENDING_DOCUMENTS, or ACTIVE",
                       409)
    data = body()
    years = req_int(data, "years_licensed")
    violations = req_int(data, "violations_last_3y")
    if years < 5 or violations != 0:
        raise ApiError("ERR_DRIVER_INELIGIBLE",
                       "Driver must have >= 5 years licensed and 0 violations in the last 3 years",
                       422)
    d = new_entity()
    d.update({
        "policy_id": p["id"],
        "full_name": req_str(data, "full_name"),
        "license_number": req_str(data, "license_number"),
        "years_licensed": years,
        "violations_last_3y": violations,
        "is_primary": opt_bool(data, "is_primary", False),
        "status": "LISTED",
    })
    db["drivers"][d["id"]] = d
    return respond(dict(d), 201)


@app.get("/policies/<pid>/drivers")
def list_drivers(pid):
    p = get_or_404("policies", pid)
    require_role("PlatformAdmin", "Underwriter", "Member")
    if role() == "Member":
        member_owns_via_policy(p)
    items = [d for d in db["drivers"].values() if d["policy_id"] == p["id"]]
    return respond_list(items)


@app.post("/policies/<pid>/drivers/<did>/remove")
def remove_driver(pid, did):
    require_role("Member")
    p = get_or_404("policies", pid)
    member_owns_via_policy(p)
    d = get_or_404("drivers", did)
    if d["policy_id"] != p["id"]:
        raise ApiError("ERR_NOT_FOUND", "Driver not found under this policy", 404)
    if d["status"] != "LISTED":
        raise ApiError("ERR_INVALID_STATE", "Driver is not LISTED", 409)
    if p["status"] not in ("QUOTED", "PENDING_DOCUMENTS", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE",
                       "Drivers may be removed only while the policy is QUOTED, PENDING_DOCUMENTS, or ACTIVE",
                       409)
    d["status"] = "REMOVED"
    touch(d)
    return respond(dict(d))


# ---------------------------------------------------------------------------
# Usage events
# ---------------------------------------------------------------------------

@app.post("/policies/<pid>/usage-events")
def record_usage_event(pid):
    require_role("Member")
    p = get_or_404("policies", pid)
    member_owns_via_policy(p)
    data = body()
    reported = req_int(data, "reported_miles")
    if reported <= 0:
        raise ApiError("ERR_VALIDATION", "reported_miles must be > 0", 400)
    event_date = req_dt(data, "event_date")
    event_kind = req_enum(data, "event_kind", EVENT_KINDS)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", "Policy is not ACTIVE", 409)
    expected = data.get("expected_policy_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise ApiError("ERR_VALIDATION", "expected_policy_version must be an integer", 400)
        if expected != p["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_policy_version does not match the policy's current version",
                           412)
    if not (parse_dt(p["period_start"]) <= event_date < parse_dt(p["period_end"])):
        raise ApiError("ERR_USAGE_OUT_OF_PERIOD",
                       "event_date is outside the policy coverage window", 422)
    allowance = p["annual_mileage_allowance"]
    prospective = p["billable_miles_used"] + (reported if event_kind == "ORDINARY" else 0)
    cap = round_half_up(Decimal(allowance) * Decimal("1.5"))
    if prospective > cap:
        raise ApiError("ERR_MILEAGE_ALLOWANCE_EXCEEDED",
                       "Cumulative billable miles would exceed 150% of the allowance", 422)
    e = new_entity()
    e.update({
        "policy_id": p["id"],
        "reported_miles": reported,
        "event_date": iso_of(event_date),
        "event_kind": event_kind,
        "billable_miles": 0,
        "overage_charge_cents": 0,
        "status": "RECORDED",
    })
    db["usage_events"][e["id"]] = e
    recompute_ledger(p)
    touch(p)
    return respond(dict(e), 201)


@app.get("/policies/<pid>/usage-events")
def list_usage_events(pid):
    p = get_or_404("policies", pid)
    require_role("PlatformAdmin", "Underwriter", "Member")
    if role() == "Member":
        member_owns_via_policy(p)
    items = [e for e in db["usage_events"].values() if e["policy_id"] == p["id"]]
    return respond_list(items)


@app.post("/usage-events/<eid>/reverse")
def reverse_usage_event(eid):
    require_role("Member")
    e = get_or_404("usage_events", eid)
    p = db["policies"][e["policy_id"]]
    member_owns_via_policy(p)
    if e["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", "Usage event is not RECORDED", 409)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", "Policy is not ACTIVE", 409)
    e["status"] = "REVERSED"
    touch(e)
    recompute_ledger(p)
    touch(p)
    return respond(dict(e))


# ---------------------------------------------------------------------------
# Repair shops
# ---------------------------------------------------------------------------

@app.post("/repair-shops")
def create_shop():
    require_role("PlatformAdmin")
    data = body()
    s = new_entity()
    s.update({
        "name": req_str(data, "name"),
        "specialty": req_str(data, "specialty"),
        "hourly_rate_cents": req_int(data, "hourly_rate_cents"),
        "status": "PROVISIONAL",
    })
    db["repair_shops"][s["id"]] = s
    return respond(dict(s), 201)


@app.get("/repair-shops")
def list_shops():
    require_role("PlatformAdmin", "Underwriter", "ClaimsAdjuster", "Member")
    items = list(db["repair_shops"].values())
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    return respond_list(items)


@app.post("/repair-shops/<sid>/certify")
def certify_shop(sid):
    require_role("PlatformAdmin")
    s = get_or_404("repair_shops", sid)
    if s["status"] not in ("PROVISIONAL", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only PROVISIONAL or SUSPENDED shops can be certified", 409)
    s["status"] = "CERTIFIED"
    touch(s)
    return respond(dict(s))


@app.post("/repair-shops/<sid>/suspend")
def suspend_shop(sid):
    require_role("PlatformAdmin")
    s = get_or_404("repair_shops", sid)
    if s["status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_STATE", "Only CERTIFIED shops can be suspended", 409)
    s["status"] = "SUSPENDED"
    touch(s)
    return respond(dict(s))


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

@app.post("/policies/<pid>/claims")
def open_claim(pid):
    require_role("Member")
    p = get_or_404("policies", pid)
    member_owns_via_policy(p)
    data = body()
    incident = req_dt(data, "incident_date")
    loss_type = req_enum(data, "loss_type", LOSS_TYPES)
    description = req_str(data, "description")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", "Policy is not ACTIVE", 409)
    if not (parse_dt(p["period_start"]) <= incident < parse_dt(p["period_end"])):
        raise ApiError("ERR_INCIDENT_OUT_OF_PERIOD",
                       "incident_date is outside the policy coverage window", 422)
    c = new_entity()
    c.update({
        "policy_id": p["id"],
        "incident_date": iso_of(incident),
        "loss_type": loss_type,
        "description": description,
        "repair_shop_id": None,
        "estimate_cents": None,
        "salvage_retained": False,
        "salvage_value_cents": 0,
        "settlement_variant": "NONE",
        "payout_cents": None,
        "declared_by_user_id": None,
        "settled_by_user_id": None,
        "status": "OPEN",
    })
    db["claims"][c["id"]] = c
    return respond(dict(c), 201)


@app.get("/policies/<pid>/claims")
def list_policy_claims(pid):
    p = get_or_404("policies", pid)
    require_role("PlatformAdmin", "Underwriter", "ClaimsAdjuster", "Member")
    if role() == "Member":
        member_owns_via_policy(p)
    items = [c for c in db["claims"].values() if c["policy_id"] == p["id"]]
    return respond_list(items)


@app.get("/claims")
def list_claims():
    require_role("PlatformAdmin", "Underwriter", "ClaimsAdjuster")
    items = list(db["claims"].values())
    for key in ("policy_id", "repair_shop_id"):
        q = request.args.get(key)
        if q:
            items = [c for c in items if c.get(key) == q]
    return respond_list(items)


@app.get("/claims/<cid>")
def get_claim(cid):
    c = get_or_404("claims", cid)
    require_role("PlatformAdmin", "Underwriter", "ClaimsAdjuster", "Member")
    if role() == "Member":
        member_owns_via_policy(db["policies"][c["policy_id"]])
    return respond(dict(c))


@app.post("/claims/<cid>/assign-shop")
def assign_shop(cid):
    require_role("ClaimsAdjuster")
    c = get_or_404("claims", cid)
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only OPEN claims can be assigned a shop", 409)
    data = body()
    shop_id = req_str(data, "repair_shop_id")
    ref_or_422("repair_shops", shop_id, "repair_shop_id")
    c["repair_shop_id"] = shop_id
    c["status"] = "UNDER_INVESTIGATION"
    touch(c)
    return respond(dict(c))


@app.post("/claims/<cid>/submit-estimate")
def submit_estimate(cid):
    require_role("ClaimsAdjuster")
    c = get_or_404("claims", cid)
    if c["status"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_INVALID_STATE",
                       "Estimates may be recorded only while UNDER_INVESTIGATION", 409)
    data = body()
    c["estimate_cents"] = req_int(data, "estimate_cents")
    touch(c)
    return respond(dict(c))


@app.post("/claims/<cid>/authorize-repair")
def authorize_repair(cid):
    require_role("ClaimsAdjuster")
    c = get_or_404("claims", cid)
    if c["status"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_INVALID_STATE",
                       "Only claims UNDER_INVESTIGATION can be authorized for repair", 409)
    if c["estimate_cents"] is None:
        raise ApiError("ERR_CLAIM_NOT_SETTLABLE", "A repair estimate is required", 409)
    shop = db["repair_shops"].get(c["repair_shop_id"])
    if shop is None or shop["status"] != "CERTIFIED":
        raise ApiError("ERR_SHOP_NOT_CERTIFIED",
                       "Repair authorization requires a CERTIFIED specialty shop", 409)
    policy = db["policies"][c["policy_id"]]
    threshold = round_half_up(Decimal(policy["coverage_limit_cents"]) * Decimal("0.75"))
    if c["estimate_cents"] > threshold:
        raise ApiError("ERR_INVALID_STATE",
                       "Estimate above 75% of the coverage limit must go the total-loss path", 409)
    c["status"] = "REPAIR_AUTHORIZED"
    c["settlement_variant"] = "REPAIR"
    touch(c)
    return respond(dict(c))


@app.post("/claims/<cid>/declare-total-loss")
def declare_total_loss(cid):
    require_role("ClaimsAdjuster")
    c = get_or_404("claims", cid)
    if c["status"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_INVALID_STATE",
                       "Only claims UNDER_INVESTIGATION can be declared a total loss", 409)
    data = body()
    salvage_retained = opt_bool(data, "salvage_retained", False)
    salvage_value = opt_int(data, "salvage_value_cents", 0)
    policy = db["policies"][c["policy_id"]]
    val = db["valuations"].get(policy["valuation_id"])
    if val is None or val["status"] != "APPROVED" or val["is_stale"] or valuation_stale(val):
        raise ApiError("ERR_VALUATION_STALE", "Pinned valuation is STALE", 409)
    c["salvage_retained"] = salvage_retained
    c["salvage_value_cents"] = salvage_value
    c["settlement_variant"] = "TOTAL_LOSS"
    c["declared_by_user_id"] = user_id()
    c["status"] = "TOTAL_LOSS_DECLARED"
    touch(c)
    return respond(dict(c))


@app.post("/claims/<cid>/settle")
def settle_claim(cid):
    require_role("ClaimsAdjuster")
    c = get_or_404("claims", cid)
    if c["status"] not in ("REPAIR_AUTHORIZED", "TOTAL_LOSS_DECLARED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only REPAIR_AUTHORIZED or TOTAL_LOSS_DECLARED claims can be settled", 409)
    policy = db["policies"][c["policy_id"]]
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", "Policy is not ACTIVE", 409)
    if c["settlement_variant"] == "TOTAL_LOSS":
        if user_id() == c["declared_by_user_id"]:
            raise ApiError("ERR_SOD_VIOLATION",
                           "The declaring adjuster cannot settle the same total loss", 403)
    if c["settlement_variant"] == "REPAIR":
        c["payout_cents"] = min(c["estimate_cents"], policy["coverage_limit_cents"])
    else:
        payout = policy["agreed_value_cents"]
        if c["salvage_retained"]:
            payout -= c["salvage_value_cents"]
        c["payout_cents"] = payout
    c["settled_by_user_id"] = user_id()
    c["status"] = "PAID"
    touch(c)
    if c["settlement_variant"] == "TOTAL_LOSS":
        policy["status"] = "CANCELLED"
        rp = active_restoration_for_policy(policy["id"])
        if rp:
            rp["status"] = "SUSPENDED"
            recompute_endorsement(rp)
        touch(policy)
        vehicle = db["vehicles"][policy["vehicle_id"]]
        if vehicle["status"] == "INSURED":
            vehicle["status"] = "RETIRED"
            touch(vehicle)
    return respond(dict(c))


@app.post("/claims/<cid>/reopen")
def reopen_claim(cid):
    require_role("Member")
    c = get_or_404("claims", cid)
    policy = db["policies"][c["policy_id"]]
    member_owns_via_policy(policy)
    if c["status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", "Only PAID claims can be reopened", 409)
    if c["settlement_variant"] != "REPAIR":
        raise ApiError("ERR_INVALID_STATE",
                       "Only repair settlements can be reopened; total loss is final", 409)
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", "Policy is not ACTIVE", 409)
    c["status"] = "UNDER_INVESTIGATION"
    c["settlement_variant"] = "NONE"
    c["payout_cents"] = None
    touch(c)
    return respond(dict(c))


@app.post("/claims/<cid>/close")
def close_claim(cid):
    require_role("ClaimsAdjuster")
    c = get_or_404("claims", cid)
    if c["status"] not in ("OPEN", "PAID"):
        raise ApiError("ERR_INVALID_STATE", "Only OPEN or PAID claims can be closed", 409)
    c["status"] = "CLOSED"
    touch(c)
    return respond(dict(c))


# ---------------------------------------------------------------------------
# Restoration projects
# ---------------------------------------------------------------------------

@app.post("/vehicles/<vid>/restoration-projects")
def create_restoration_project(vid):
    require_role("Member")
    v = get_or_404("vehicles", vid)
    member_owns_via_vehicle(v)
    data = body()
    policy_id = req_str(data, "policy_id")
    policy = ref_or_422("policies", policy_id, "policy_id")
    if policy["vehicle_id"] != v["id"]:
        raise ApiError("ERR_REFERENCED_NOT_FOUND",
                       "Referenced policy does not cover this vehicle", 422)
    if policy["member_id"] != v["member_id"]:
        raise ApiError("ERR_FORBIDDEN", "Referenced policy belongs to another member", 403)
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", "Policy is not ACTIVE", 409)
    if v["status"] != "INSURED":
        raise ApiError("ERR_INVALID_STATE",
                       "Restoration coverage requires a vehicle in INSURED status", 409)
    rp = new_entity()
    rp.update({
        "vehicle_id": v["id"],
        "policy_id": policy["id"],
        "stage": "DISASSEMBLY",
        "receipts_total_cents": 0,
        "endorsement_limit_cents": 0,
        "status": "ACTIVE",
    })
    db["restoration_projects"][rp["id"]] = rp
    v["status"] = "UNDER_RESTORATION"
    touch(v)
    return respond(dict(rp), 201)


@app.get("/vehicles/<vid>/restoration-projects")
def list_vehicle_projects(vid):
    v = get_or_404("vehicles", vid)
    require_role("PlatformAdmin", "Underwriter", "Member")
    if role() == "Member":
        member_owns_via_vehicle(v)
    items = [r for r in db["restoration_projects"].values() if r["vehicle_id"] == v["id"]]
    return respond_list(items)


@app.get("/restoration-projects")
def list_projects():
    require_role("PlatformAdmin", "Underwriter")
    items = list(db["restoration_projects"].values())
    for key in ("policy_id", "vehicle_id"):
        q = request.args.get(key)
        if q:
            items = [r for r in items if r.get(key) == q]
    return respond_list(items)


@app.get("/restoration-projects/<rid>")
def get_project(rid):
    rp = get_or_404("restoration_projects", rid)
    require_role("PlatformAdmin", "Underwriter", "Member")
    if role() == "Member":
        member_owns_via_vehicle(db["vehicles"][rp["vehicle_id"]])
    return respond(dict(rp))


@app.post("/restoration-projects/<rid>/receipts")
def submit_receipt(rid):
    require_role("Member")
    rp = get_or_404("restoration_projects", rid)
    member_owns_via_vehicle(db["vehicles"][rp["vehicle_id"]])
    data = body()
    amount = req_int(data, "amount_cents")
    receipt_ref = req_str(data, "receipt_ref")
    r = new_entity()
    r.update({"project_id": rp["id"], "amount_cents": amount, "receipt_ref": receipt_ref})
    db["receipts"][r["id"]] = r
    recompute_endorsement(rp)
    return respond(dict(rp), 200)


@app.post("/restoration-projects/<rid>/advance-stage")
def advance_stage(rid):
    require_role("Underwriter")
    rp = get_or_404("restoration_projects", rid)
    if rp["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only ACTIVE projects can advance stage", 409)
    if rp["stage"] == "FINISH":
        raise ApiError("ERR_RESTORE_STAGE_INVALID",
                       "FINISH advances via complete", 409)
    if rp["stage"] not in STAGE_ORDER[:-1]:
        raise ApiError("ERR_RESTORE_STAGE_INVALID", "Stage cannot be advanced", 409)
    if rp["receipts_total_cents"] <= 0:
        raise ApiError("ERR_INVALID_STATE",
                       "Cannot advance with zero documented spend", 409)
    rp["stage"] = STAGE_ORDER[STAGE_ORDER.index(rp["stage"]) + 1]
    recompute_endorsement(rp)
    return respond(dict(rp))


@app.post("/restoration-projects/<rid>/suspend")
def suspend_project(rid):
    require_role("Underwriter")
    rp = get_or_404("restoration_projects", rid)
    if rp["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only ACTIVE projects can be suspended", 409)
    rp["status"] = "SUSPENDED"
    recompute_endorsement(rp)
    return respond(dict(rp))


@app.post("/restoration-projects/<rid>/resume")
def resume_project(rid):
    require_role("Underwriter")
    rp = get_or_404("restoration_projects", rid)
    if rp["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Only SUSPENDED projects can be resumed", 409)
    policy = db["policies"][rp["policy_id"]]
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", "Policy is not ACTIVE", 409)
    rp["status"] = "ACTIVE"
    recompute_endorsement(rp)
    return respond(dict(rp))


@app.post("/restoration-projects/<rid>/complete")
def complete_project(rid):
    require_role("Underwriter")
    rp = get_or_404("restoration_projects", rid)
    if rp["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only ACTIVE projects can be completed", 409)
    if rp["stage"] != "FINISH":
        raise ApiError("ERR_RESTORE_STAGE_INVALID",
                       "Completion is reserved for a project at FINISH", 409)
    rp["stage"] = "COMPLETE"
    rp["status"] = "COMPLETED"
    recompute_endorsement(rp)
    v = db["vehicles"][rp["vehicle_id"]]
    if v["status"] == "UNDER_RESTORATION":
        v["status"] = "INSURED"
        touch(v)
    return respond(dict(rp))


# ---------------------------------------------------------------------------
# Club memberships
# ---------------------------------------------------------------------------

@app.post("/club-memberships")
def create_membership():
    require_role("PlatformAdmin")
    data = body()
    member_id = req_str(data, "member_id")
    tier = req_enum(data, "tier", CLUB_TIERS)
    ref_or_422("members", member_id, "member_id")
    m = new_entity()
    m.update({
        "member_id": member_id,
        "tier": tier,
        "roadside_calls_limit": ROADSIDE_LIMIT[tier],
        "roadside_calls_used": 0,
        "status": "ACTIVE",
    })
    db["club_memberships"][m["id"]] = m
    return respond(dict(m), 201)


@app.get("/club-memberships")
def list_memberships():
    require_role("PlatformAdmin", "ClubCoordinator")
    items = list(db["club_memberships"].values())
    member_id = request.args.get("member_id")
    if member_id:
        items = [m for m in items if m["member_id"] == member_id]
    return respond_list(items)


@app.get("/club-memberships/<mid>")
def get_membership(mid):
    m = get_or_404("club_memberships", mid)
    require_role("PlatformAdmin", "ClubCoordinator", "Member")
    if role() == "Member":
        member_check(m["member_id"])
    return respond(dict(m))


@app.post("/club-memberships/<mid>/lapse")
def lapse_membership(mid):
    require_role("ClubCoordinator")
    m = get_or_404("club_memberships", mid)
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only ACTIVE memberships can lapse", 409)
    m["status"] = "LAPSED"
    touch(m)
    return respond(dict(m))


@app.post("/club-memberships/<mid>/reactivate")
def reactivate_membership(mid):
    require_role("ClubCoordinator")
    m = get_or_404("club_memberships", mid)
    if m["status"] != "LAPSED":
        raise ApiError("ERR_INVALID_STATE", "Only LAPSED memberships can be reactivated", 409)
    member = db["members"][m["member_id"]]
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", "Member is not ACTIVE", 409)
    m["status"] = "ACTIVE"
    touch(m)
    return respond(dict(m))


# --- Roadside events ---

@app.post("/club-memberships/<mid>/roadside-events")
def dispatch_roadside(mid):
    require_role("Member")
    m = get_or_404("club_memberships", mid)
    member_check(m["member_id"])
    data = body()
    vehicle_id = req_str(data, "vehicle_id")
    service_type = req_enum(data, "service_type", SERVICE_TYPES)
    event_date = req_dt(data, "event_date")
    vehicle = ref_or_422("vehicles", vehicle_id, "vehicle_id")
    if vehicle["member_id"] != m["member_id"]:
        raise ApiError("ERR_FORBIDDEN", "Vehicle belongs to another member", 403)
    if vehicle["status"] != "INSURED":
        raise ApiError("ERR_INVALID_STATE",
                       "Roadside dispatch requires a covered classic (vehicle status INSURED)", 409)
    if service_type != "FLATBED_TOW":
        raise ApiError("ERR_ROADSIDE_FLATBED_REQUIRED",
                       "Classic roadside service requires FLATBED_TOW", 422)
    used = sum(1 for e in db["roadside_events"].values()
               if e["membership_id"] == m["id"] and e["status"] in ("DISPATCHED", "COMPLETED"))
    if used >= m["roadside_calls_limit"]:
        raise ApiError("ERR_ROADSIDE_LIMIT_REACHED",
                       "Membership roadside call limit reached", 409)
    e = new_entity()
    e.update({
        "membership_id": m["id"],
        "vehicle_id": vehicle["id"],
        "service_type": service_type,
        "event_date": iso_of(event_date),
        "status": "DISPATCHED",
    })
    db["roadside_events"][e["id"]] = e
    recompute_roadside_used(m)
    return respond(dict(e), 201)


@app.get("/club-memberships/<mid>/roadside-events")
def list_membership_roadside(mid):
    m = get_or_404("club_memberships", mid)
    require_role("PlatformAdmin", "ClubCoordinator", "Member")
    if role() == "Member":
        member_check(m["member_id"])
    items = [e for e in db["roadside_events"].values() if e["membership_id"] == m["id"]]
    return respond_list(items)


@app.get("/roadside-events/<eid>")
def get_roadside(eid):
    e = get_or_404("roadside_events", eid)
    require_role("PlatformAdmin", "ClubCoordinator", "Member")
    if role() == "Member":
        member_check(db["club_memberships"][e["membership_id"]]["member_id"])
    return respond(dict(e))


@app.get("/roadside-events")
def list_roadside():
    require_role("PlatformAdmin", "ClubCoordinator")
    items = list(db["roadside_events"].values())
    vehicle_id = request.args.get("vehicle_id")
    if vehicle_id:
        items = [e for e in items if e["vehicle_id"] == vehicle_id]
    return respond_list(items)


@app.post("/roadside-events/<eid>/complete")
def complete_roadside(eid):
    require_role("ClubCoordinator")
    e = get_or_404("roadside_events", eid)
    if e["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", "Only DISPATCHED events can be completed", 409)
    e["status"] = "COMPLETED"
    touch(e)
    return respond(dict(e))


@app.post("/roadside-events/<eid>/cancel")
def cancel_roadside(eid):
    require_role("Member")
    e = get_or_404("roadside_events", eid)
    m = db["club_memberships"][e["membership_id"]]
    member_check(m["member_id"])
    if e["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", "Only DISPATCHED events can be cancelled", 409)
    e["status"] = "CANCELLED"
    touch(e)
    recompute_roadside_used(m)
    return respond(dict(e))


# ---------------------------------------------------------------------------
# Club events & registrations
# ---------------------------------------------------------------------------

@app.post("/club-events")
def create_event():
    require_role("ClubCoordinator")
    data = body()
    name = req_str(data, "name")
    venue = req_str(data, "venue")
    start = req_dt(data, "start_date")
    end = req_dt(data, "end_date")
    capacity = req_int(data, "capacity")
    day = timedelta(days=1)
    for other in db["club_events"].values():
        if other["venue"] != venue or other["status"] != "SCHEDULED":
            continue
        os_ = parse_dt(other["start_date"]) - day
        oe = parse_dt(other["end_date"]) + day
        if (start - day) <= oe and os_ <= (end + day):
            raise ApiError("ERR_EVENT_VENUE_CONFLICT",
                           "Venue has a SCHEDULED event whose buffered interval intersects", 409)
    e = new_entity()
    e.update({
        "name": name,
        "venue": venue,
        "start_date": iso_of(start),
        "end_date": iso_of(end),
        "capacity": capacity,
        "registered_count": 0,
        "status": "SCHEDULED",
    })
    db["club_events"][e["id"]] = e
    return respond(dict(e), 201)


@app.get("/club-events/<eid>")
def get_event(eid):
    e = get_or_404("club_events", eid)
    require_role("PlatformAdmin", "ClubCoordinator", "Member")
    return respond(dict(e))


@app.post("/club-events/<eid>/cancel")
def cancel_event(eid):
    require_role("ClubCoordinator")
    e = get_or_404("club_events", eid)
    if e["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only SCHEDULED events can be cancelled", 409)
    e["status"] = "CANCELLED"
    touch(e)
    for r in db["event_registrations"].values():
        if r["event_id"] == e["id"] and r["status"] == "REGISTERED":
            r["status"] = "CANCELLED"
            touch(r)
    recompute_event_count(e)
    return respond(dict(e))


@app.post("/club-events/<eid>/register")
def register_event(eid):
    require_role("Member")
    e = get_or_404("club_events", eid)
    data = body()
    member_id = req_str(data, "member_id")
    if member_id != user_id():
        raise ApiError("ERR_FORBIDDEN",
                       "member_id must match the acting member", 403)
    ref_or_422("members", member_id, "member_id")
    if e["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Event is not SCHEDULED", 409)
    registered = sum(1 for r in db["event_registrations"].values()
                     if r["event_id"] == e["id"] and r["status"] == "REGISTERED")
    if registered >= e["capacity"]:
        raise ApiError("ERR_EVENT_FULL", "Event has reached capacity", 409)
    r = new_entity()
    r.update({"event_id": e["id"], "member_id": member_id, "status": "REGISTERED"})
    db["event_registrations"][r["id"]] = r
    recompute_event_count(e)
    return respond(dict(r), 201)


@app.get("/club-events/<eid>/registrations")
def list_registrations(eid):
    e = get_or_404("club_events", eid)
    require_role("PlatformAdmin", "ClubCoordinator", "Member")
    items = [r for r in db["event_registrations"].values() if r["event_id"] == e["id"]]
    return respond_list(items)


@app.post("/club-events/<eid>/registrations/<rid>/cancel")
def cancel_registration(eid, rid):
    require_role("Member")
    e = get_or_404("club_events", eid)
    r = get_or_404("event_registrations", rid)
    if r["event_id"] != e["id"]:
        raise ApiError("ERR_NOT_FOUND", "Registration not found under this event", 404)
    if r["member_id"] != user_id():
        raise ApiError("ERR_FORBIDDEN", "Member may cancel only their own registration", 403)
    if r["status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", "Registration is not REGISTERED", 409)
    r["status"] = "CANCELLED"
    touch(r)
    recompute_event_count(e)
    return respond(dict(r))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
