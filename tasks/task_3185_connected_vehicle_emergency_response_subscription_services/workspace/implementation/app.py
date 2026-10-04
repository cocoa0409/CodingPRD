"""Connected Vehicle Emergency Services API — Flask implementation.

Reads PRD.md for behavior; uses an in-memory store and a logical clock.
"""
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

DB = {
    "plan_tiers": {},          # id -> PlanTier
    "accounts": {},            # id -> Account
    "vehicles": {},            # id -> Vehicle
    "subscriptions": {},       # id -> Subscription
    "coverage_zones": {},      # id -> CoverageZone
    "crash_events": {},        # id -> CrashEvent
    "dispatch_requests": {},   # id -> DispatchRequest
    "psaps": {},               # id -> PSAP
    "stolen_cases": {},        # id -> StolenVehicleCase
    "remote_commands": {},     # id -> RemoteCommand
    "diagnostic_reports": {},  # id -> DiagnosticReport
    "dealers": {},             # id -> Dealer
    "appointments": {},        # id -> ServiceAppointment
    "consents": {},            # id -> DataConsent
}

# Logical clock — initialized at import time per process; PRD §2.6 says it
# starts at 2026-09-01T00:00:00Z before any clock-setting call.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


def _parse_iso(s):
    if isinstance(s, datetime):
        return s
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def _iso(dt):
    """Render an aware UTC datetime as ISO 8601 with milliseconds + Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.astimezone(timezone.utc).microsecond // 1000:03d}Z"


class Clock:
    def __init__(self):
        self._current = _parse_iso(DEFAULT_CLOCK)

    def now(self):
        return self._current

    def set(self, dt):
        self._current = dt.astimezone(timezone.utc)


CLOCK = Clock()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_SLOWDOWN_NOT_VERIFIED": 409,
    "ERR_SLOWDOWN_UNSUPPORTED_HARDWARE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_RETENTION_WINDOW_EXPIRED": 409,
    "ERR_APPOINTMENT_IN_PAST": 409,
    "ERR_ODOMETER_REGRESSION": 409,
    "ERR_REMOTE_COMMAND_CAP_REACHED": 409,
    "ERR_PSAP_UNAVAILABLE": 409,
    "ERR_DEALER_CAPACITY_REACHED": 409,
    "ERR_CONSENT_DEPENDENCY_MISSING": 409,
    "ERR_DUPLICATE": 409,
    "ERR_NO_CELLULAR_COVERAGE": 422,
    "ERR_EMERGENCY_ENTITLEMENT_MISSING": 422,
    "ERR_TIER_CAPABILITY_MISSING": 422,
    "ERR_EMERGENCY_ONLY_COMMAND": 422,
    "ERR_CRASH_THRESHOLD_NOT_MET": 422,
    "ERR_BILLING_TRANSITION_INVALID": 409,
}


def err(error_id, message):
    return ApiError(error_id, message, ERR[error_id])


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _request_id():
    return "req_" + uuid.uuid4().hex[:24]


def _meta_now():
    return _iso(datetime.now(timezone.utc))


def success_envelope(data, response_type="object", status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _meta_now(),
    }
    if pagination is not None:
        meta.update(pagination)
    return jsonify({
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }), status


def error_envelope(error_id, message, http_status):
    return jsonify({
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _meta_now(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }), http_status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_envelope(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_envelope("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_envelope("ERR_NOT_FOUND", "method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_envelope("ERR_INVALID_REQUEST", f"unexpected error: {e}", 400)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

VALID_ROLES = {
    "PlatformAdmin", "Account", "Advisor", "PSAPOperator", "LawEnforcement",
    "EmergencyOperator", "DealerService", "BillingAdmin", "SystemIngestion",
}


def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized auth headers")
    return {"user_id": uid, "role": role}


def require_roles(*roles):
    auth = get_auth()
    if auth["role"] not in roles:
        raise err("ERR_UNAUTHORIZED", f"role {auth['role']} not permitted")
    return auth


def check_account_ownership(auth, account_id):
    """For Account role, X-User-ID must equal the path account id."""
    if auth["role"] == "Account" and auth["user_id"] != account_id:
        raise err("ERR_UNAUTHORIZED", "Account role can only act on own resources")


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------

def _new_common():
    now = CLOCK.now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": _iso(now),
        "updated_at": _iso(now),
        "version": 1,
    }


def _bump(entity):
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = _iso(CLOCK.now())


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def paginate(items):
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    items = sorted(items, key=lambda e: (e.get("created_at") or "", e.get("id") or ""))
    total = len(items)
    page = items[offset: offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


def list_response(items, status=200):
    page, meta = paginate(items)
    return success_envelope(page, response_type="array", status=status, pagination=meta)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def require_field(body, name, kind=None):
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    val = body[name]
    if kind == "str" and not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    if kind == "int" and (not isinstance(val, int) or isinstance(val, bool)):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if kind == "num" and (not isinstance(val, (int, float)) or isinstance(val, bool)):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a number")
    if kind == "bool" and not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    if kind == "list" and not isinstance(val, list):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a list")
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name, "str")
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(allowed)}")
    return val


_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def validate_vin(vin):
    if not isinstance(vin, str) or len(vin) != 17 or not _VIN_RE.match(vin):
        raise err("ERR_INVALID_REQUEST", "vin must be exactly 17 chars, uppercase alnum minus I/O/Q")


def validate_region_code(rc):
    if not isinstance(rc, str) or len(rc) != 2:
        raise err("ERR_INVALID_REQUEST", "region_code must be a 2-letter code")


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_or_404(store_key, entity_id, what=None):
    e = DB[store_key].get(entity_id)
    if e is None:
        raise err("ERR_NOT_FOUND", f"{what or store_key} {entity_id} not found")
    return e


def find_subscription_for_vehicle(vehicle_id):
    """The vehicle's subscription, if any.

    PRD §3.2: only one non-terminal subscription may exist per vehicle.
    Terminal (CANCELLED) subscriptions linger in storage and must still be
    resolvable: PRD §3.3 requires the entitlement step to resolve the
    vehicle's subscription and snapshot it into the event's subscription_id
    even when that subscription is LAPSED or CANCELLED (the event is then
    persisted as REJECTED_NO_ENTITLEMENT). If several subscriptions exist,
    the most recently created one is current.
    """
    candidates = [
        s for s in DB["subscriptions"].values()
        if s["vehicle_id"] == vehicle_id
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda s: s["created_at"])
    return candidates[-1]


def find_tier_by_code(code):
    for t in DB["plan_tiers"].values():
        if t["code"] == code:
            return t
    return None


def find_zone_by_region(region_code):
    for z in DB["coverage_zones"].values():
        if z["region_code"] == region_code:
            return z
    return None


# ---------------------------------------------------------------------------
# Time-driven transitions (fired on clock set AND on read of state)
# ---------------------------------------------------------------------------

def fire_time_transitions():
    now = CLOCK.now()
    # Subscriptions: PAST_DUE -> LAPSED after 10 days from past_due_entry
    for sub in DB["subscriptions"].values():
        if sub["status"] == "PAST_DUE":
            entry = sub.get("_past_due_entered_at")
            if entry is not None and now >= entry + timedelta(days=10):
                sub["status"] = "LAPSED"
                sub["lapse_date"] = _iso(now)
                sub["next_renewal_date"] = None
                sub["_past_due_entered_at"] = None
                _bump(sub)
    # Subscriptions: LAPSED -> CANCELLED after retention window
    for sub in DB["subscriptions"].values():
        if sub["status"] == "LAPSED":
            lapse = _parse_iso(sub["lapse_date"]) if sub.get("lapse_date") else None
            if lapse is not None and now > lapse + timedelta(days=30):
                sub["status"] = "CANCELLED"
                sub["emergency_only_flag"] = False
                _bump(sub)
    # Remote commands: PENDING/SENT -> EXPIRED at expires_at
    for cmd in DB["remote_commands"].values():
        if cmd["status"] in {"PENDING", "SENT"}:
            exp = _parse_iso(cmd["expires_at"]) if cmd.get("expires_at") else None
            if exp is not None and now >= exp:
                cmd["status"] = "EXPIRED"
                _bump(cmd)


# ---------------------------------------------------------------------------
# Computed subscription fields
# ---------------------------------------------------------------------------

def compute_period_remote_commands_used(sub):
    """PRD §3.5: count ACK/FAILED commands in [period_start, period_start+30d).
    For EMERGENCY_RETAINED: only is_emergency_command rows in [lapse, lapse+30d).
    """
    if sub["status"] == "EMERGENCY_RETAINED":
        if not sub.get("lapse_date"):
            return 0
        start = _parse_iso(sub["lapse_date"])
        end = start + timedelta(days=30)
        n = 0
        for c in DB["remote_commands"].values():
            if c.get("subscription_id") != sub["id"]:
                continue
            if not c.get("is_emergency_command"):
                continue
            if c["status"] not in {"ACKNOWLEDGED", "FAILED"}:
                continue
            created = _parse_iso(c["created_at"])
            if start <= created < end:
                n += 1
        return n
    # Standard billing period
    if not sub.get("current_period_start"):
        return 0
    start = _parse_iso(sub["current_period_start"])
    end = start + timedelta(days=30)
    n = 0
    for c in DB["remote_commands"].values():
        if c.get("subscription_id") != sub["id"]:
            continue
        if c["status"] not in {"ACKNOWLEDGED", "FAILED"}:
            continue
        created = _parse_iso(c["created_at"])
        if start <= created < end:
            n += 1
    return n


def recompute_subscription_derived(sub):
    """Update computed fields prior to read/return."""
    tier = find_tier_by_code(sub["tier_code"])
    if sub["status"] == "EMERGENCY_RETAINED":
        sub["emergency_only_flag"] = True
    elif sub["status"] == "ACTIVE" and tier is not None \
            and tier.get("allows_emergency") \
            and not tier.get("allows_remote_commands") \
            and not tier.get("allows_navigation") \
            and (tier.get("allows_data_gb") or 0) == 0:
        sub["emergency_only_flag"] = True
    else:
        sub["emergency_only_flag"] = False
    sub["period_remote_commands_used"] = compute_period_remote_commands_used(sub)


def render_subscription(sub):
    recompute_subscription_derived(sub)
    return {
        "id": sub["id"],
        "account_id": sub["account_id"],
        "vehicle_id": sub["vehicle_id"],
        "tier_code": sub["tier_code"],
        "status": sub["status"],
        "trial_start_date": sub["trial_start_date"],
        "trial_end_date": sub["trial_end_date"],
        "current_period_start": sub["current_period_start"],
        "next_renewal_date": sub.get("next_renewal_date"),
        "lapse_date": sub.get("lapse_date"),
        "emergency_only_flag": sub.get("emergency_only_flag", False),
        "period_remote_commands_used": sub.get("period_remote_commands_used", 0),
        "conversion_fee_paid_cents": sub.get("conversion_fee_paid_cents", 0),
        "created_at": sub["created_at"],
        "updated_at": sub["updated_at"],
        "version": sub["version"],
    }


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

CRASH_SCORE_THRESHOLD = Decimal("35")
DELTA_V_CAP_KPH = Decimal("80")
WEIGHT_DELTA_V = Decimal("0.6")
WEIGHT_AIRBAG = Decimal("25")
WEIGHT_ROLLOVER = Decimal("20")
LATE_CONVERSION_FEE_PCT = Decimal("0.20")

REMOTE_COMMAND_CAP = {
    "EMERGENCY_ONLY": 0,
    "SAFETY": 0,
    "SAFETY_REMOTE": 10,
    "PREMIUM": 50,
}
EMERGENCY_RETAINED_LOCATE_CAP = 2


def compute_severity_score(delta_v_kph, airbag_deployed, rollover_detected):
    dv = Decimal(str(delta_v_kph))
    if dv > DELTA_V_CAP_KPH:
        dv = DELTA_V_CAP_KPH
    score = WEIGHT_DELTA_V * dv
    if airbag_deployed:
        score += WEIGHT_AIRBAG
    if rollover_detected:
        score += WEIGHT_ROLLOVER
    return score.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def compute_severity_band(score):
    if score >= Decimal("60"):
        return "SEVERE"
    if score >= Decimal("35"):
        return "MODERATE"
    return "MINOR"


def compute_health_score(dtc_codes, oil_life_pct):
    base = 100
    base -= 8 * len(dtc_codes)
    base -= (100 - oil_life_pct) // 5
    if base < 0:
        base = 0
    if base > 100:
        base = 100
    return base


def compute_insurance_score(account_id):
    now = CLOCK.now()
    window_start = now - timedelta(days=90)
    vehicle_ids = {v["id"] for v in DB["vehicles"].values() if v["account_id"] == account_id}
    qualifying = []
    for r in DB["diagnostic_reports"].values():
        if r["vehicle_id"] not in vehicle_ids:
            continue
        if r["status"] not in {"GENERATED", "SERVICE_SCHEDULED"}:
            continue
        created = _parse_iso(r["created_at"])
        if window_start <= created <= now:
            qualifying.append(r)
    if not qualifying:
        return 50.00
    total = sum(r["health_score"] for r in qualifying)
    n = len(qualifying)
    score = (Decimal(total) / Decimal(n)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(score)


def resolve_entitlements_for_vehicle(vehicle_id):
    """Return (subscription, tier_dict_or_none, allows_emergency, allows_remote_commands,
    emergency_only_locate_only)."""
    sub = find_subscription_for_vehicle(vehicle_id)
    if sub is None:
        return None, None, False, False, False
    if sub["status"] in {"LAPSED", "CANCELLED"}:
        return sub, None, False, False, False
    if sub["status"] == "EMERGENCY_RETAINED":
        return sub, None, True, False, True
    tier = find_tier_by_code(sub["tier_code"])
    if tier is None:
        return sub, None, False, False, False
    return (
        sub,
        tier,
        bool(tier.get("allows_emergency")),
        bool(tier.get("allows_remote_commands")),
        False,
    )


# ---------------------------------------------------------------------------
# Clock endpoint (exempt from auth)
# ---------------------------------------------------------------------------

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        return error_envelope("ERR_INVALID_REQUEST", "to_iso8601 required", 400)
    try:
        dt = _parse_iso(to_iso)
    except Exception:
        return error_envelope("ERR_INVALID_REQUEST", "invalid to_iso8601", 400)
    CLOCK.set(dt)
    fire_time_transitions()
    return success_envelope({"current_utc": _iso(CLOCK.now())}, status=200)


# ---------------------------------------------------------------------------
# Plan tiers
# ---------------------------------------------------------------------------

TIER_CODES = {"EMERGENCY_ONLY", "SAFETY", "SAFETY_REMOTE", "PREMIUM"}


def render_plan_tier(t):
    return {
        "id": t["id"], "code": t["code"], "monthly_fee_cents": t["monthly_fee_cents"],
        "allows_emergency": t["allows_emergency"],
        "allows_remote_commands": t["allows_remote_commands"],
        "allows_navigation": t["allows_navigation"],
        "allows_data_gb": t["allows_data_gb"],
        "status": t["status"],
        "created_at": t["created_at"], "updated_at": t["updated_at"], "version": t["version"],
    }


@app.route("/plan-tiers", methods=["POST"])
def create_plan_tier():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    code = require_enum(body, "code", TIER_CODES)
    monthly_fee_cents = require_field(body, "monthly_fee_cents", "int")
    if monthly_fee_cents < 0:
        raise err("ERR_INVALID_REQUEST", "monthly_fee_cents must be >= 0")
    allows_emergency = require_field(body, "allows_emergency", "bool")
    allows_remote_commands = require_field(body, "allows_remote_commands", "bool")
    allows_navigation = require_field(body, "allows_navigation", "bool")
    allows_data_gb = require_field(body, "allows_data_gb", "num")
    if allows_data_gb < 0:
        raise err("ERR_INVALID_REQUEST", "allows_data_gb must be >= 0")
    if find_tier_by_code(code) is not None:
        raise err("ERR_DUPLICATE", f"tier code {code} already exists")
    tier = _new_common()
    tier.update({
        "code": code,
        "monthly_fee_cents": monthly_fee_cents,
        "allows_emergency": allows_emergency,
        "allows_remote_commands": allows_remote_commands,
        "allows_navigation": allows_navigation,
        "allows_data_gb": allows_data_gb,
        "status": "ACTIVE",
    })
    DB["plan_tiers"][tier["id"]] = tier
    return success_envelope(render_plan_tier(tier), status=201)


@app.route("/plan-tiers", methods=["GET"])
def list_plan_tiers():
    require_roles("PlatformAdmin", "Account", "EmergencyOperator")
    return list_response([render_plan_tier(t) for t in DB["plan_tiers"].values()])


@app.route("/plan-tiers/<tier_id>", methods=["GET"])
def get_plan_tier(tier_id):
    require_roles("PlatformAdmin", "Account", "EmergencyOperator")
    t = get_or_404("plan_tiers", tier_id)
    return success_envelope(render_plan_tier(t))


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def render_account(a):
    return {
        "id": a["id"], "full_name": a["full_name"], "email": a["email"],
        "phone": a["phone"], "home_region_code": a["home_region_code"],
        "status": a["status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"],
    }


@app.route("/accounts", methods=["POST"])
def create_account():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    full_name = require_field(body, "full_name", "str")
    email = require_field(body, "email", "str")
    phone = require_field(body, "phone", "str")
    home_region_code = require_field(body, "home_region_code", "str")
    validate_region_code(home_region_code)
    for existing in DB["accounts"].values():
        if existing["email"] == email:
            raise err("ERR_DUPLICATE", f"email {email} already registered")
    a = _new_common()
    a.update({
        "full_name": full_name, "email": email, "phone": phone,
        "home_region_code": home_region_code, "status": "ACTIVE",
    })
    DB["accounts"][a["id"]] = a
    return success_envelope(render_account(a), status=201)


@app.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    auth = require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator")
    check_account_ownership(auth, account_id)
    a = get_or_404("accounts", account_id)
    return success_envelope(render_account(a))


# ---------------------------------------------------------------------------
# Coverage zones
# ---------------------------------------------------------------------------

def render_zone(z):
    return {
        "id": z["id"], "region_code": z["region_code"],
        "has_cellular": z["has_cellular"],
        "supports_data": z["supports_data"],
        "supports_navigation": z["supports_navigation"],
        "created_at": z["created_at"], "updated_at": z["updated_at"], "version": z["version"],
    }


@app.route("/coverage-zones", methods=["POST"])
def create_zone():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    region_code = require_field(body, "region_code", "str")
    validate_region_code(region_code)
    has_cellular = require_field(body, "has_cellular", "bool")
    supports_data = require_field(body, "supports_data", "bool")
    supports_navigation = require_field(body, "supports_navigation", "bool")
    if find_zone_by_region(region_code) is not None:
        raise err("ERR_DUPLICATE", f"coverage zone for {region_code} already exists")
    z = _new_common()
    z.update({
        "region_code": region_code,
        "has_cellular": has_cellular,
        "supports_data": supports_data,
        "supports_navigation": supports_navigation,
    })
    DB["coverage_zones"][z["id"]] = z
    return success_envelope(render_zone(z), status=201)


@app.route("/coverage-zones", methods=["GET"])
def list_zones():
    require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator")
    return list_response([render_zone(z) for z in DB["coverage_zones"].values()])


@app.route("/coverage-zones/<zone_id>", methods=["GET"])
def get_zone(zone_id):
    require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator")
    z = get_or_404("coverage_zones", zone_id)
    return success_envelope(render_zone(z))


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------

def render_vehicle(v):
    return {
        "id": v["id"], "account_id": v["account_id"], "vin": v["vin"],
        "make": v["make"], "model": v["model"], "model_year": v["model_year"],
        "region_code": v["region_code"], "hardware_generation": v["hardware_generation"],
        "status": v["status"],
        "created_at": v["created_at"], "updated_at": v["updated_at"], "version": v["version"],
    }


@app.route("/accounts/<account_id>/vehicles", methods=["POST"])
def create_vehicle(account_id):
    auth = require_roles("Account")
    check_account_ownership(auth, account_id)
    account = get_or_404("accounts", account_id)
    body = request.get_json(silent=True) or {}
    vin = require_field(body, "vin", "str")
    validate_vin(vin)
    make = require_field(body, "make", "str")
    model = require_field(body, "model", "str")
    model_year = require_field(body, "model_year", "int")
    if model_year < 2015:
        raise err("ERR_INVALID_REQUEST", "model_year must be >= 2015")
    region_code = require_field(body, "region_code", "str")
    validate_region_code(region_code)
    hardware_generation = require_field(body, "hardware_generation", "int")
    if hardware_generation not in (4, 5):
        raise err("ERR_INVALID_REQUEST", "hardware_generation must be 4 or 5")
    # Region must map to a coverage zone
    if find_zone_by_region(region_code) is None:
        raise err("ERR_INVALID_REQUEST", f"region {region_code} has no coverage zone")
    for v in DB["vehicles"].values():
        if v["vin"] == vin:
            raise err("ERR_DUPLICATE", f"vin {vin} already registered")
    veh = _new_common()
    veh.update({
        "account_id": account_id, "vin": vin, "make": make, "model": model,
        "model_year": model_year, "region_code": region_code,
        "hardware_generation": hardware_generation, "status": "ACTIVE",
    })
    DB["vehicles"][veh["id"]] = veh
    return success_envelope(render_vehicle(veh), status=201)


@app.route("/accounts/<account_id>/vehicles", methods=["GET"])
def list_account_vehicles(account_id):
    auth = require_roles("PlatformAdmin", "Account", "Advisor")
    check_account_ownership(auth, account_id)
    get_or_404("accounts", account_id)
    rows = [v for v in DB["vehicles"].values() if v["account_id"] == account_id]
    return list_response([render_vehicle(v) for v in rows])


@app.route("/accounts/vehicles/<vehicle_id>", methods=["GET"])
def get_vehicle_aliased(vehicle_id):
    auth = require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator",
                         "LawEnforcement", "DealerService")
    v = get_or_404("vehicles", vehicle_id)
    if auth["role"] == "Account" and v["account_id"] != auth["user_id"]:
        raise err("ERR_UNAUTHORIZED", "Account role can only access own vehicles")
    return success_envelope(render_vehicle(v))


@app.route("/accounts/vehicles", methods=["GET"])
def list_vehicles_flat():
    auth = require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator",
                         "LawEnforcement", "DealerService")
    rows = list(DB["vehicles"].values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id:
        rows = [v for v in rows if v["account_id"] == account_id]
    if status:
        rows = [v for v in rows if v["status"] == status]
    if auth["role"] == "Account":
        rows = [v for v in rows if v["account_id"] == auth["user_id"]]
    return list_response([render_vehicle(v) for v in rows])


@app.route("/vehicles/<vehicle_id>", methods=["GET"])
def get_vehicle(vehicle_id):
    auth = require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator",
                         "LawEnforcement", "DealerService")
    v = get_or_404("vehicles", vehicle_id)
    if auth["role"] == "Account" and v["account_id"] != auth["user_id"]:
        raise err("ERR_UNAUTHORIZED", "Account role can only access own vehicles")
    return success_envelope(render_vehicle(v))


@app.route("/vehicles/<vehicle_id>", methods=["PATCH"])
def update_vehicle(vehicle_id):
    auth = require_roles("Account", "PlatformAdmin")
    v = get_or_404("vehicles", vehicle_id)
    if auth["role"] == "Account" and v["account_id"] != auth["user_id"]:
        raise err("ERR_UNAUTHORIZED", "Account role can only modify own vehicles")
    body = request.get_json(silent=True) or {}
    new_status = require_field(body, "status", "str")
    allowed_targets = {"ACTIVE", "DECOMMISSIONED"}
    if new_status not in allowed_targets:
        raise err("ERR_INVALID_STATE", f"vehicle cannot be set to {new_status}")
    if new_status == "ACTIVE":
        if v["status"] != "RECOVERED":
            raise err("ERR_INVALID_STATE", "only RECOVERED -> ACTIVE allowed")
    elif new_status == "DECOMMISSIONED":
        if v["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "only ACTIVE -> DECOMMISSIONED allowed")
        # Blocked while live subscription exists
        for s in DB["subscriptions"].values():
            if s["vehicle_id"] == vehicle_id and s["status"] in {
                "TRIAL", "ACTIVE", "PAST_DUE", "EMERGENCY_RETAINED",
            }:
                raise err("ERR_INVALID_STATE",
                          "vehicle has non-terminal subscription; cannot decommission")
    v["status"] = new_status
    _bump(v)
    return success_envelope(render_vehicle(v))


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------

def get_subscription_or_404(account_id, subscription_id):
    account = get_or_404("accounts", account_id)
    sub = DB["subscriptions"].get(subscription_id)
    if sub is None or sub["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", f"subscription {subscription_id} not found")
    return sub


@app.route("/accounts/<account_id>/subscriptions", methods=["POST"])
def create_subscription(account_id):
    auth = require_roles("Account")
    check_account_ownership(auth, account_id)
    account = get_or_404("accounts", account_id)
    body = request.get_json(silent=True) or {}
    vehicle_id = require_field(body, "vehicle_id", "str")
    tier_code = require_field(body, "tier_code", "str")
    veh = DB["vehicles"].get(vehicle_id)
    if veh is None:
        raise err("ERR_NOT_FOUND", f"vehicle {vehicle_id} not found")
    if veh["account_id"] != account_id:
        raise err("ERR_UNAUTHORIZED", "vehicle does not belong to this account")
    tier = find_tier_by_code(tier_code)
    if tier is None:
        raise err("ERR_INVALID_REQUEST", f"unknown tier_code {tier_code}")
    # One non-terminal subscription per vehicle
    for s in DB["subscriptions"].values():
        if s["vehicle_id"] == vehicle_id and s["status"] in {
            "TRIAL", "ACTIVE", "PAST_DUE", "EMERGENCY_RETAINED",
        }:
            raise err("ERR_INVALID_STATE", "vehicle already has a non-terminal subscription")
    now = CLOCK.now()
    sub = _new_common()
    sub.update({
        "account_id": account_id,
        "vehicle_id": vehicle_id,
        "tier_code": tier_code,
        "status": "TRIAL",
        "trial_start_date": _iso(now),
        "trial_end_date": _iso(now + timedelta(days=30)),
        "current_period_start": _iso(now),
        "next_renewal_date": None,
        "lapse_date": None,
        "emergency_only_flag": False,
        "period_remote_commands_used": 0,
        "conversion_fee_paid_cents": 0,
        "_past_due_entered_at": None,
    })
    DB["subscriptions"][sub["id"]] = sub
    return success_envelope(render_subscription(sub), status=201)


@app.route("/accounts/<account_id>/subscriptions", methods=["GET"])
def list_account_subscriptions(account_id):
    auth = require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator")
    check_account_ownership(auth, account_id)
    get_or_404("accounts", account_id)
    fire_time_transitions()
    rows = [s for s in DB["subscriptions"].values() if s["account_id"] == account_id]
    vehicle_id = request.args.get("vehicle_id")
    status = request.args.get("status")
    if vehicle_id:
        rows = [s for s in rows if s["vehicle_id"] == vehicle_id]
    if status:
        rows = [s for s in rows if s["status"] == status]
    return list_response([render_subscription(s) for s in rows])


@app.route("/accounts/subscriptions", methods=["GET"])
def list_subscriptions_flat():
    auth = require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator", "BillingAdmin")
    fire_time_transitions()
    rows = list(DB["subscriptions"].values())
    account_id = request.args.get("account_id")
    vehicle_id = request.args.get("vehicle_id")
    status = request.args.get("status")
    if account_id:
        rows = [s for s in rows if s["account_id"] == account_id]
    if vehicle_id:
        rows = [s for s in rows if s["vehicle_id"] == vehicle_id]
    if status:
        rows = [s for s in rows if s["status"] == status]
    if auth["role"] == "Account":
        rows = [s for s in rows if s["account_id"] == auth["user_id"]]
    return list_response([render_subscription(s) for s in rows])


@app.route("/accounts/subscriptions/<subscription_id>", methods=["GET"])
def get_subscription_aliased(subscription_id):
    auth = require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator", "BillingAdmin")
    fire_time_transitions()
    sub = get_or_404("subscriptions", subscription_id)
    if auth["role"] == "Account" and sub["account_id"] != auth["user_id"]:
        raise err("ERR_UNAUTHORIZED", "Account role can only access own subscriptions")
    return success_envelope(render_subscription(sub))


@app.route("/accounts/<account_id>/subscriptions/<subscription_id>", methods=["GET"])
def get_subscription(account_id, subscription_id):
    auth = require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator")
    check_account_ownership(auth, account_id)
    fire_time_transitions()
    sub = get_subscription_or_404(account_id, subscription_id)
    return success_envelope(render_subscription(sub))


@app.route("/accounts/<account_id>/subscriptions/<subscription_id>/convert", methods=["POST"])
def convert_subscription(account_id, subscription_id):
    auth = require_roles("Account")
    check_account_ownership(auth, account_id)
    fire_time_transitions()
    sub = get_subscription_or_404(account_id, subscription_id)
    body = request.get_json(silent=True) or {}
    expected = require_field(body, "expected_subscription_version", "int")
    if expected != sub["version"]:
        raise err("ERR_STALE_VERSION",
                  f"expected_subscription_version {expected} != current {sub['version']}")
    if sub["status"] != "TRIAL":
        raise err("ERR_INVALID_STATE", f"cannot convert from {sub['status']}")
    # Conversion fee
    tier = find_tier_by_code(sub["tier_code"])
    trial_end = _parse_iso(sub["trial_end_date"])
    now = CLOCK.now()
    if now < trial_end:
        fee = 0
    else:
        fee_decimal = (Decimal(tier["monthly_fee_cents"]) * LATE_CONVERSION_FEE_PCT).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        fee = int(max(Decimal("0"), fee_decimal))
    sub["conversion_fee_paid_cents"] = fee
    sub["current_period_start"] = _iso(now)
    sub["next_renewal_date"] = _iso(now + timedelta(days=30))
    sub["status"] = "ACTIVE"
    _bump(sub)
    return success_envelope(render_subscription(sub))


@app.route("/accounts/<account_id>/subscriptions/<subscription_id>/billing-events",
           methods=["POST"])
def record_billing_event(account_id, subscription_id):
    auth = require_roles("BillingAdmin")
    fire_time_transitions()
    sub = get_subscription_or_404(account_id, subscription_id)
    body = request.get_json(silent=True) or {}
    outcome = require_enum(body, "outcome", {"PAYMENT_SUCCEEDED", "PAYMENT_FAILED"})
    now = CLOCK.now()
    if outcome == "PAYMENT_FAILED":
        if sub["status"] != "ACTIVE":
            raise err("ERR_BILLING_TRANSITION_INVALID",
                      f"PAYMENT_FAILED not valid from {sub['status']}")
        sub["status"] = "PAST_DUE"
        sub["_past_due_entered_at"] = now
        # next_renewal_date unchanged
    else:  # PAYMENT_SUCCEEDED
        if sub["status"] == "PAST_DUE":
            sub["status"] = "ACTIVE"
            sub["_past_due_entered_at"] = None
            sub["current_period_start"] = _iso(now)
            sub["next_renewal_date"] = _iso(now + timedelta(days=30))
        elif sub["status"] == "ACTIVE":
            sub["current_period_start"] = _iso(now)
            sub["next_renewal_date"] = _iso(now + timedelta(days=30))
        else:
            raise err("ERR_BILLING_TRANSITION_INVALID",
                      f"PAYMENT_SUCCEEDED not valid from {sub['status']}")
    _bump(sub)
    return success_envelope(render_subscription(sub))


@app.route("/accounts/<account_id>/subscriptions/<subscription_id>/retain-emergency",
           methods=["POST"])
def retain_emergency(account_id, subscription_id):
    auth = require_roles("Account")
    check_account_ownership(auth, account_id)
    fire_time_transitions()
    sub = get_subscription_or_404(account_id, subscription_id)
    if sub["status"] != "LAPSED":
        raise err("ERR_INVALID_STATE", f"cannot retain-emergency from {sub['status']}")
    lapse = _parse_iso(sub["lapse_date"])
    now = CLOCK.now()
    if now > lapse + timedelta(days=30):
        raise err("ERR_RETENTION_WINDOW_EXPIRED", "retention window closed")
    veh = DB["vehicles"].get(sub["vehicle_id"])
    if veh is None or veh["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "vehicle not ACTIVE")
    sub["status"] = "EMERGENCY_RETAINED"
    sub["emergency_only_flag"] = True
    _bump(sub)
    return success_envelope(render_subscription(sub))


@app.route("/accounts/<account_id>/subscriptions/<subscription_id>/reactivate",
           methods=["POST"])
def reactivate_subscription(account_id, subscription_id):
    auth = require_roles("Account")
    check_account_ownership(auth, account_id)
    fire_time_transitions()
    sub = get_subscription_or_404(account_id, subscription_id)
    body = request.get_json(silent=True) or {}
    expected = require_field(body, "expected_subscription_version", "int")
    if expected != sub["version"]:
        raise err("ERR_STALE_VERSION", "stale version")
    if sub["status"] != "EMERGENCY_RETAINED":
        raise err("ERR_INVALID_STATE", f"cannot reactivate from {sub['status']}")
    now = CLOCK.now()
    sub["status"] = "ACTIVE"
    sub["current_period_start"] = _iso(now)
    sub["next_renewal_date"] = _iso(now + timedelta(days=30))
    sub["lapse_date"] = None
    _bump(sub)
    return success_envelope(render_subscription(sub))


@app.route("/accounts/<account_id>/subscriptions/<subscription_id>/cancel", methods=["POST"])
def cancel_subscription(account_id, subscription_id):
    auth = require_roles("Account")
    check_account_ownership(auth, account_id)
    fire_time_transitions()
    sub = get_subscription_or_404(account_id, subscription_id)
    if sub["status"] not in {"TRIAL", "ACTIVE", "EMERGENCY_RETAINED"}:
        raise err("ERR_INVALID_STATE", f"cannot cancel from {sub['status']}")
    if sub["status"] == "ACTIVE":
        sub["next_renewal_date"] = None
    if sub["status"] == "EMERGENCY_RETAINED":
        sub["emergency_only_flag"] = False
    sub["status"] = "CANCELLED"
    _bump(sub)
    return success_envelope(render_subscription(sub))


# ---------------------------------------------------------------------------
# Crash events
# ---------------------------------------------------------------------------

def render_crash_event(e):
    return {
        "id": e["id"], "vehicle_id": e["vehicle_id"],
        "subscription_id": e.get("subscription_id"),
        "delta_v_kph": e["delta_v_kph"],
        "rollover_detected": e["rollover_detected"],
        "airbag_deployed": e["airbag_deployed"],
        "location_region_code": e["location_region_code"],
        "severity_score": e["severity_score"],
        "severity_band": e["severity_band"],
        "status": e["status"],
        "created_at": e["created_at"], "updated_at": e["updated_at"], "version": e["version"],
    }


@app.route("/vehicles/<vehicle_id>/crash-events", methods=["POST"])
def create_crash_event(vehicle_id):
    # SystemIngestion endpoints are exempt from auth header presence but role-restricted.
    auth = get_auth() if (request.headers.get("X-User-ID") or request.headers.get("X-User-Role")) else None
    if auth is not None and auth["role"] != "SystemIngestion":
        raise err("ERR_UNAUTHORIZED", "only SystemIngestion may report crash events")
    veh = get_or_404("vehicles", vehicle_id)
    body = request.get_json(silent=True) or {}
    delta_v_kph = require_field(body, "delta_v_kph", "num")
    if delta_v_kph < 0:
        raise err("ERR_INVALID_REQUEST", "delta_v_kph must be >= 0")
    rollover = body.get("rollover_detected", False)
    if not isinstance(rollover, bool):
        raise err("ERR_INVALID_REQUEST", "rollover_detected must be bool")
    airbag = body.get("airbag_deployed", False)
    if not isinstance(airbag, bool):
        raise err("ERR_INVALID_REQUEST", "airbag_deployed must be bool")
    location = require_field(body, "location_region_code", "str")
    score = compute_severity_score(delta_v_kph, airbag, rollover)
    if score < CRASH_SCORE_THRESHOLD:
        raise err("ERR_CRASH_THRESHOLD_NOT_MET",
                  f"severity_score {score} below threshold {CRASH_SCORE_THRESHOLD}")
    band = compute_severity_band(score)
    # Coverage gate
    zone = find_zone_by_region(location)
    if zone is None or not zone["has_cellular"]:
        status = "REJECTED_NO_COVERAGE"
        subscription_id = None
    else:
        sub, tier, allows_emergency, _, _ = resolve_entitlements_for_vehicle(vehicle_id)
        subscription_id = sub["id"] if sub is not None else None
        if allows_emergency:
            status = "RECEIVED"
        else:
            status = "REJECTED_NO_ENTITLEMENT"
    ev = _new_common()
    ev.update({
        "vehicle_id": vehicle_id,
        "subscription_id": subscription_id,
        "delta_v_kph": delta_v_kph,
        "rollover_detected": rollover,
        "airbag_deployed": airbag,
        "location_region_code": location,
        "severity_score": float(score),
        "severity_band": band,
        "status": status,
    })
    DB["crash_events"][ev["id"]] = ev
    return success_envelope(render_crash_event(ev), status=201)


def _get_event_for_vehicle(vehicle_id, event_id):
    veh = get_or_404("vehicles", vehicle_id)
    ev = DB["crash_events"].get(event_id)
    if ev is None or ev["vehicle_id"] != vehicle_id:
        raise err("ERR_NOT_FOUND", f"crash event {event_id} not found")
    return ev


@app.route("/vehicles/<vehicle_id>/crash-events", methods=["GET"])
def list_vehicle_crash_events(vehicle_id):
    auth = require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator")
    veh = get_or_404("vehicles", vehicle_id)
    if auth["role"] == "Account" and veh["account_id"] != auth["user_id"]:
        raise err("ERR_UNAUTHORIZED", "not your vehicle")
    rows = [e for e in DB["crash_events"].values() if e["vehicle_id"] == vehicle_id]
    status = request.args.get("status")
    if status:
        rows = [e for e in rows if e["status"] == status]
    return list_response([render_crash_event(e) for e in rows])


@app.route("/vehicles/<vehicle_id>/crash-events/<event_id>", methods=["GET"])
def get_crash_event(vehicle_id, event_id):
    auth = require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator")
    ev = _get_event_for_vehicle(vehicle_id, event_id)
    if auth["role"] == "Account":
        veh = DB["vehicles"][vehicle_id]
        if veh["account_id"] != auth["user_id"]:
            raise err("ERR_UNAUTHORIZED", "not your vehicle")
    return success_envelope(render_crash_event(ev))


@app.route("/accounts/crash-events", methods=["GET"])
def list_crash_events_flat():
    auth = require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator")
    rows = list(DB["crash_events"].values())
    vehicle_id = request.args.get("vehicle_id")
    subscription_id = request.args.get("subscription_id")
    status = request.args.get("status")
    if vehicle_id:
        rows = [e for e in rows if e["vehicle_id"] == vehicle_id]
    if subscription_id:
        rows = [e for e in rows if e.get("subscription_id") == subscription_id]
    if status:
        rows = [e for e in rows if e["status"] == status]
    if auth["role"] == "Account":
        own_vehicles = {v["id"] for v in DB["vehicles"].values() if v["account_id"] == auth["user_id"]}
        rows = [e for e in rows if e["vehicle_id"] in own_vehicles]
    return list_response([render_crash_event(e) for e in rows])


@app.route("/accounts/crash-events/<event_id>", methods=["GET"])
def get_crash_event_aliased(event_id):
    auth = require_roles("PlatformAdmin", "Account", "Advisor", "EmergencyOperator")
    ev = get_or_404("crash_events", event_id)
    if auth["role"] == "Account":
        veh = DB["vehicles"].get(ev["vehicle_id"])
        if veh is None or veh["account_id"] != auth["user_id"]:
            raise err("ERR_UNAUTHORIZED", "not your event")
    return success_envelope(render_crash_event(ev))


@app.route("/vehicles/<vehicle_id>/crash-events/<event_id>/connect-advisor", methods=["POST"])
def connect_advisor(vehicle_id, event_id):
    require_roles("Advisor")
    ev = _get_event_for_vehicle(vehicle_id, event_id)
    if ev["status"] != "RECEIVED":
        raise err("ERR_INVALID_STATE", f"cannot connect advisor from {ev['status']}")
    ev["status"] = "ADVISOR_CONNECTED"
    _bump(ev)
    return success_envelope(render_crash_event(ev))


@app.route("/vehicles/<vehicle_id>/crash-events/<event_id>/close", methods=["POST"])
def close_crash_event(vehicle_id, event_id):
    require_roles("Advisor")
    ev = _get_event_for_vehicle(vehicle_id, event_id)
    if ev["status"] != "ADVISOR_CONNECTED":
        raise err("ERR_INVALID_STATE", f"cannot close from {ev['status']}")
    ev["status"] = "CLOSED_NO_INJURY"
    _bump(ev)
    return success_envelope(render_crash_event(ev))


@app.route("/vehicles/<vehicle_id>/crash-events/<event_id>/dispatch-requests", methods=["POST"])
def create_dispatch_request(vehicle_id, event_id):
    require_roles("Advisor")
    ev = _get_event_for_vehicle(vehicle_id, event_id)
    body = request.get_json(silent=True) or {}
    psap_id = require_field(body, "psap_id", "str")
    if ev["status"] != "ADVISOR_CONNECTED":
        raise err("ERR_INVALID_STATE", f"cannot dispatch from {ev['status']}")
    psap = DB["psaps"].get(psap_id)
    if psap is None:
        raise err("ERR_NOT_FOUND", f"psap {psap_id} not found")
    if psap["status"] != "ACTIVE" or not psap["accepts_location_transfer"] \
            or psap["region_code"] != ev["location_region_code"]:
        raise err("ERR_PSAP_UNAVAILABLE", "PSAP not available for dispatch")
    veh = DB["vehicles"].get(vehicle_id)
    location_payload = {
        "vehicle_id": vehicle_id,
        "region_code": ev["location_region_code"],
        "severity_band": ev["severity_band"],
        "severity_score": ev["severity_score"],
        "airbag_deployed": ev["airbag_deployed"],
        "rollover_detected": ev["rollover_detected"],
    }
    dr = _new_common()
    dr.update({
        "crash_event_id": event_id,
        "vehicle_id": vehicle_id,
        "psap_id": psap_id,
        "status": "LOCATION_SENT",
        "location_payload": location_payload,
        "acknowledged_at": None,
    })
    DB["dispatch_requests"][dr["id"]] = dr
    ev["status"] = "DISPATCH_COORDINATED"
    _bump(ev)
    return success_envelope(render_dispatch(dr), status=201)


# ---------------------------------------------------------------------------
# Dispatch requests
# ---------------------------------------------------------------------------

def render_dispatch(d):
    return {
        "id": d["id"], "crash_event_id": d["crash_event_id"], "psap_id": d["psap_id"],
        "vehicle_id": d.get("vehicle_id"),
        "status": d["status"],
        "location_payload": d.get("location_payload"),
        "acknowledged_at": d.get("acknowledged_at"),
        "created_at": d["created_at"], "updated_at": d["updated_at"], "version": d["version"],
    }


@app.route("/accounts/dispatch-requests", methods=["GET"])
def list_dispatch_requests_flat():
    require_roles("PlatformAdmin", "Advisor", "PSAPOperator", "EmergencyOperator")
    rows = list(DB["dispatch_requests"].values())
    ce = request.args.get("crash_event_id")
    psap = request.args.get("psap_id")
    status = request.args.get("status")
    if ce:
        rows = [d for d in rows if d["crash_event_id"] == ce]
    if psap:
        rows = [d for d in rows if d["psap_id"] == psap]
    if status:
        rows = [d for d in rows if d["status"] == status]
    return list_response([render_dispatch(d) for d in rows])


@app.route("/accounts/dispatch-requests/<dispatch_id>", methods=["GET"])
def get_dispatch_aliased(dispatch_id):
    require_roles("PlatformAdmin", "Advisor", "PSAPOperator", "EmergencyOperator")
    d = get_or_404("dispatch_requests", dispatch_id)
    return success_envelope(render_dispatch(d))


@app.route("/dispatch-requests/<dispatch_id>", methods=["GET"])
def get_dispatch(dispatch_id):
    require_roles("PlatformAdmin", "Advisor", "PSAPOperator", "EmergencyOperator")
    d = get_or_404("dispatch_requests", dispatch_id)
    return success_envelope(render_dispatch(d))


@app.route("/vehicles/<vehicle_id>/dispatch-requests", methods=["GET"])
def list_vehicle_dispatch_requests(vehicle_id):
    require_roles("PlatformAdmin", "Advisor", "EmergencyOperator")
    get_or_404("vehicles", vehicle_id)
    rows = [d for d in DB["dispatch_requests"].values() if d.get("vehicle_id") == vehicle_id]
    return list_response([render_dispatch(d) for d in rows])


@app.route("/dispatch-requests/<dispatch_id>/acknowledge", methods=["POST"])
def acknowledge_dispatch(dispatch_id):
    require_roles("PSAPOperator")
    d = get_or_404("dispatch_requests", dispatch_id)
    if d["status"] != "LOCATION_SENT":
        raise err("ERR_INVALID_STATE", f"cannot acknowledge from {d['status']}")
    d["status"] = "ACKNOWLEDGED"
    d["acknowledged_at"] = _iso(CLOCK.now())
    _bump(d)
    # Bubble up: CrashEvent DISPATCH_COORDINATED -> CLOSED_DISPATCHED
    ev = DB["crash_events"].get(d["crash_event_id"])
    if ev is not None and ev["status"] == "DISPATCH_COORDINATED":
        ev["status"] = "CLOSED_DISPATCHED"
        _bump(ev)
    return success_envelope(render_dispatch(d))


@app.route("/dispatch-requests/<dispatch_id>/cancel", methods=["POST"])
def cancel_dispatch(dispatch_id):
    require_roles("Advisor")
    d = get_or_404("dispatch_requests", dispatch_id)
    if d["status"] != "LOCATION_SENT":
        raise err("ERR_INVALID_STATE", f"cannot cancel from {d['status']}")
    d["status"] = "CANCELLED"
    _bump(d)
    return success_envelope(render_dispatch(d))


@app.route("/accounts/psaps/<psap_id>/dispatch-requests", methods=["GET"])
def list_psap_dispatch_requests(psap_id):
    require_roles("PlatformAdmin", "PSAPOperator", "Advisor")
    get_or_404("psaps", psap_id)
    rows = [d for d in DB["dispatch_requests"].values() if d["psap_id"] == psap_id]
    return list_response([render_dispatch(d) for d in rows])


# ---------------------------------------------------------------------------
# PSAPs
# ---------------------------------------------------------------------------

def render_psap(p):
    return {
        "id": p["id"], "name": p["name"], "region_code": p["region_code"],
        "accepts_location_transfer": p["accepts_location_transfer"],
        "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


@app.route("/psaps", methods=["POST"])
def create_psap():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    name = require_field(body, "name", "str")
    region_code = require_field(body, "region_code", "str")
    validate_region_code(region_code)
    accepts = body.get("accepts_location_transfer", True)
    if not isinstance(accepts, bool):
        raise err("ERR_INVALID_REQUEST", "accepts_location_transfer must be bool")
    p = _new_common()
    p.update({
        "name": name, "region_code": region_code,
        "accepts_location_transfer": accepts, "status": "ACTIVE",
    })
    DB["psaps"][p["id"]] = p
    return success_envelope(render_psap(p), status=201)


@app.route("/psaps", methods=["GET"])
def list_psaps():
    require_roles("PlatformAdmin", "Advisor", "EmergencyOperator", "PSAPOperator")
    rows = list(DB["psaps"].values())
    region = request.args.get("region_code")
    if region:
        rows = [p for p in rows if p["region_code"] == region]
    return list_response([render_psap(p) for p in rows])


@app.route("/psaps/<psap_id>", methods=["GET"])
def get_psap(psap_id):
    require_roles("PlatformAdmin", "Advisor", "EmergencyOperator", "PSAPOperator")
    p = get_or_404("psaps", psap_id)
    return success_envelope(render_psap(p))


@app.route("/accounts/psaps/<psap_id>", methods=["GET"])
def get_psap_aliased(psap_id):
    require_roles("PlatformAdmin", "Advisor", "EmergencyOperator", "PSAPOperator")
    p = get_or_404("psaps", psap_id)
    return success_envelope(render_psap(p))


# ---------------------------------------------------------------------------
# Stolen vehicle cases
# ---------------------------------------------------------------------------

def render_case(c):
    return {
        "id": c["id"], "vehicle_id": c["vehicle_id"],
        "police_report_number": c["police_report_number"],
        "reporting_agency": c["reporting_agency"],
        "status": c["status"],
        "verified_by_user_id": c.get("verified_by_user_id"),
        "slowdown_executed_at": c.get("slowdown_executed_at"),
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


@app.route("/vehicles/<vehicle_id>/stolen-cases", methods=["POST"])
def create_stolen_case(vehicle_id):
    auth = require_roles("LawEnforcement")
    veh = get_or_404("vehicles", vehicle_id)
    body = request.get_json(silent=True) or {}
    police_report_number = require_field(body, "police_report_number", "str")
    reporting_agency = require_field(body, "reporting_agency", "str")
    if veh["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", f"vehicle must be ACTIVE to report stolen, got {veh['status']}")
    # One open case per vehicle
    for c in DB["stolen_cases"].values():
        if c["vehicle_id"] == vehicle_id and c["status"] in {
            "REPORTED", "VERIFIED", "SLOWDOWN_ARMED", "SLOWDOWN_EXECUTED",
        }:
            raise err("ERR_INVALID_STATE", "vehicle already has an open stolen case")
    for c in DB["stolen_cases"].values():
        if c["police_report_number"] == police_report_number:
            raise err("ERR_DUPLICATE", f"police_report_number {police_report_number} already used")
    case = _new_common()
    case.update({
        "vehicle_id": vehicle_id,
        "police_report_number": police_report_number,
        "reporting_agency": reporting_agency,
        "status": "REPORTED",
        "reporter_user_id": auth["user_id"],
        "verified_by_user_id": None,
        "slowdown_executed_at": None,
    })
    DB["stolen_cases"][case["id"]] = case
    return success_envelope(render_case(case), status=201)


def _get_case_for_vehicle(vehicle_id, case_id):
    get_or_404("vehicles", vehicle_id)
    c = DB["stolen_cases"].get(case_id)
    if c is None or c["vehicle_id"] != vehicle_id:
        raise err("ERR_NOT_FOUND", f"stolen case {case_id} not found")
    return c


@app.route("/vehicles/<vehicle_id>/stolen-cases", methods=["GET"])
def list_vehicle_stolen_cases(vehicle_id):
    require_roles("PlatformAdmin", "LawEnforcement", "EmergencyOperator", "Account")
    get_or_404("vehicles", vehicle_id)
    rows = [c for c in DB["stolen_cases"].values() if c["vehicle_id"] == vehicle_id]
    return list_response([render_case(c) for c in rows])


@app.route("/vehicles/<vehicle_id>/stolen-cases/<case_id>", methods=["GET"])
def get_stolen_case(vehicle_id, case_id):
    require_roles("PlatformAdmin", "LawEnforcement", "EmergencyOperator", "Account")
    c = _get_case_for_vehicle(vehicle_id, case_id)
    return success_envelope(render_case(c))


@app.route("/accounts/stolen-cases", methods=["GET"])
def list_stolen_cases_flat():
    require_roles("PlatformAdmin", "LawEnforcement", "EmergencyOperator", "Account")
    rows = list(DB["stolen_cases"].values())
    vehicle_id = request.args.get("vehicle_id")
    status = request.args.get("status")
    if vehicle_id:
        rows = [c for c in rows if c["vehicle_id"] == vehicle_id]
    if status:
        rows = [c for c in rows if c["status"] == status]
    return list_response([render_case(c) for c in rows])


@app.route("/accounts/stolen-cases/<case_id>", methods=["GET"])
def get_stolen_case_aliased(case_id):
    require_roles("PlatformAdmin", "LawEnforcement", "EmergencyOperator", "Account")
    c = get_or_404("stolen_cases", case_id)
    return success_envelope(render_case(c))


@app.route("/vehicles/<vehicle_id>/stolen-cases/<case_id>/verify", methods=["POST"])
def verify_stolen_case(vehicle_id, case_id):
    auth = require_roles("LawEnforcement")
    case = _get_case_for_vehicle(vehicle_id, case_id)
    if case["status"] != "REPORTED":
        raise err("ERR_INVALID_STATE", f"cannot verify from {case['status']}")
    if auth["user_id"] == case["reporter_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "verifier must differ from reporter")
    case["status"] = "VERIFIED"
    case["verified_by_user_id"] = auth["user_id"]
    _bump(case)
    # Cascade: vehicle ACTIVE -> STOLEN_REPORTED
    veh = DB["vehicles"].get(vehicle_id)
    if veh is not None and veh["status"] == "ACTIVE":
        veh["status"] = "STOLEN_REPORTED"
        _bump(veh)
    return success_envelope(render_case(case))


@app.route("/vehicles/<vehicle_id>/stolen-cases/<case_id>/arm-slowdown", methods=["POST"])
def arm_slowdown(vehicle_id, case_id):
    auth = require_roles("EmergencyOperator")
    case = _get_case_for_vehicle(vehicle_id, case_id)
    # Safety gate 1: verification precedes arming
    if case["status"] != "VERIFIED":
        raise err("ERR_SLOWDOWN_NOT_VERIFIED", "case must be VERIFIED before arming")
    # Safety gate 2: hardware generation 5
    veh = DB["vehicles"].get(vehicle_id)
    if veh is None or veh["hardware_generation"] != 5:
        raise err("ERR_SLOWDOWN_UNSUPPORTED_HARDWARE", "hardware_generation must be 5")
    # Safety gate 3: cellular coverage
    zone = find_zone_by_region(veh["region_code"])
    if zone is None or not zone["has_cellular"]:
        raise err("ERR_NO_CELLULAR_COVERAGE", "no cellular coverage in vehicle region")
    case["status"] = "SLOWDOWN_ARMED"
    _bump(case)
    return success_envelope(render_case(case))


@app.route("/vehicles/<vehicle_id>/stolen-cases/<case_id>/execute-slowdown", methods=["POST"])
def execute_slowdown(vehicle_id, case_id):
    require_roles("EmergencyOperator")
    case = _get_case_for_vehicle(vehicle_id, case_id)
    if case["status"] != "SLOWDOWN_ARMED":
        raise err("ERR_INVALID_STATE", f"cannot execute slowdown from {case['status']}")
    veh = DB["vehicles"].get(vehicle_id)
    if veh is None or veh["status"] != "STOLEN_REPORTED":
        raise err("ERR_INVALID_STATE", "vehicle not in STOLEN_REPORTED")
    case["status"] = "SLOWDOWN_EXECUTED"
    case["slowdown_executed_at"] = _iso(CLOCK.now())
    _bump(case)
    return success_envelope(render_case(case))


@app.route("/vehicles/<vehicle_id>/stolen-cases/<case_id>/close-recovered", methods=["POST"])
def close_case_recovered(vehicle_id, case_id):
    require_roles("LawEnforcement")
    case = _get_case_for_vehicle(vehicle_id, case_id)
    if case["status"] not in {"VERIFIED", "SLOWDOWN_EXECUTED"}:
        raise err("ERR_INVALID_STATE", f"cannot close recovered from {case['status']}")
    case["status"] = "CLOSED_RECOVERED"
    _bump(case)
    veh = DB["vehicles"].get(vehicle_id)
    if veh is not None and veh["status"] == "STOLEN_REPORTED":
        veh["status"] = "RECOVERED"
        _bump(veh)
    return success_envelope(render_case(case))


@app.route("/vehicles/<vehicle_id>/stolen-cases/<case_id>/close-unverified", methods=["POST"])
def close_case_unverified(vehicle_id, case_id):
    require_roles("LawEnforcement")
    case = _get_case_for_vehicle(vehicle_id, case_id)
    if case["status"] != "REPORTED":
        raise err("ERR_INVALID_STATE", f"cannot close unverified from {case['status']}")
    case["status"] = "CLOSED_UNVERIFIED"
    _bump(case)
    return success_envelope(render_case(case))


# ---------------------------------------------------------------------------
# Remote commands
# ---------------------------------------------------------------------------

REMOTE_COMMAND_TYPES = {"LOCK", "UNLOCK", "HORN_LIGHTS", "LOCATE"}


def render_remote_command(c):
    return {
        "id": c["id"], "vehicle_id": c["vehicle_id"],
        "subscription_id": c.get("subscription_id"),
        "command_type": c["command_type"],
        "status": c["status"],
        "is_emergency_command": c.get("is_emergency_command", False),
        "expires_at": c.get("expires_at"),
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


@app.route("/vehicles/<vehicle_id>/remote-commands", methods=["POST"])
def create_remote_command(vehicle_id):
    auth = require_roles("Account")
    fire_time_transitions()
    veh = get_or_404("vehicles", vehicle_id)
    if veh["account_id"] != auth["user_id"]:
        raise err("ERR_UNAUTHORIZED", "Account role can only command own vehicles")
    body = request.get_json(silent=True) or {}
    command_type = require_enum(body, "command_type", REMOTE_COMMAND_TYPES)
    # Coverage gate first (priority 10, coverage dominates)
    zone = find_zone_by_region(veh["region_code"])
    if zone is None or not zone["has_cellular"]:
        raise err("ERR_NO_CELLULAR_COVERAGE", "no cellular coverage in vehicle region")
    # Entitlement
    sub, tier, allows_emergency, allows_remote, emergency_only = \
        resolve_entitlements_for_vehicle(vehicle_id)
    if emergency_only:
        if command_type != "LOCATE":
            raise err("ERR_EMERGENCY_ONLY_COMMAND",
                      "only LOCATE allowed under EMERGENCY_RETAINED")
    else:
        if not allows_remote:
            raise err("ERR_TIER_CAPABILITY_MISSING", "tier lacks remote commands")
    # Cap check
    if sub is not None:
        if sub["status"] == "EMERGENCY_RETAINED":
            used = compute_period_remote_commands_used(sub)
            if used >= EMERGENCY_RETAINED_LOCATE_CAP:
                raise err("ERR_REMOTE_COMMAND_CAP_REACHED",
                          "emergency locate cap reached (2 per 30-day window)")
        else:
            used = compute_period_remote_commands_used(sub)
            cap = REMOTE_COMMAND_CAP.get(sub["tier_code"], 0)
            if used >= cap:
                raise err("ERR_REMOTE_COMMAND_CAP_REACHED", f"period cap {cap} reached")
    now = CLOCK.now()
    cmd = _new_common()
    cmd.update({
        "vehicle_id": vehicle_id,
        "subscription_id": sub["id"] if sub is not None else None,
        "command_type": command_type,
        "status": "SENT",
        "is_emergency_command": bool(emergency_only),
        "expires_at": _iso(now + timedelta(minutes=10)),
    })
    DB["remote_commands"][cmd["id"]] = cmd
    return success_envelope(render_remote_command(cmd), status=201)


@app.route("/vehicles/<vehicle_id>/remote-commands", methods=["GET"])
def list_vehicle_remote_commands(vehicle_id):
    auth = require_roles("PlatformAdmin", "Account", "EmergencyOperator")
    fire_time_transitions()
    veh = get_or_404("vehicles", vehicle_id)
    if auth["role"] == "Account" and veh["account_id"] != auth["user_id"]:
        raise err("ERR_UNAUTHORIZED", "not your vehicle")
    rows = [c for c in DB["remote_commands"].values() if c["vehicle_id"] == vehicle_id]
    return list_response([render_remote_command(c) for c in rows])


@app.route("/accounts/remote-commands", methods=["GET"])
def list_remote_commands_flat():
    auth = require_roles("PlatformAdmin", "Account", "EmergencyOperator", "SystemIngestion")
    fire_time_transitions()
    rows = list(DB["remote_commands"].values())
    vehicle_id = request.args.get("vehicle_id")
    subscription_id = request.args.get("subscription_id")
    status = request.args.get("status")
    if vehicle_id:
        rows = [c for c in rows if c["vehicle_id"] == vehicle_id]
    if subscription_id:
        rows = [c for c in rows if c.get("subscription_id") == subscription_id]
    if status:
        rows = [c for c in rows if c["status"] == status]
    if auth["role"] == "Account":
        own_vehicles = {v["id"] for v in DB["vehicles"].values() if v["account_id"] == auth["user_id"]}
        rows = [c for c in rows if c["vehicle_id"] in own_vehicles]
    return list_response([render_remote_command(c) for c in rows])


@app.route("/accounts/remote-commands/<command_id>", methods=["GET"])
def get_remote_command_aliased(command_id):
    auth = require_roles("PlatformAdmin", "Account", "EmergencyOperator", "SystemIngestion")
    fire_time_transitions()
    c = get_or_404("remote_commands", command_id)
    if auth["role"] == "Account":
        veh = DB["vehicles"].get(c["vehicle_id"])
        if veh is None or veh["account_id"] != auth["user_id"]:
            raise err("ERR_UNAUTHORIZED", "not your command")
    return success_envelope(render_remote_command(c))


@app.route("/remote-commands/<command_id>", methods=["GET"])
def get_remote_command(command_id):
    auth = require_roles("PlatformAdmin", "Account", "EmergencyOperator", "SystemIngestion")
    fire_time_transitions()
    c = get_or_404("remote_commands", command_id)
    if auth["role"] == "Account":
        veh = DB["vehicles"].get(c["vehicle_id"])
        if veh is None or veh["account_id"] != auth["user_id"]:
            raise err("ERR_UNAUTHORIZED", "not your command")
    return success_envelope(render_remote_command(c))


@app.route("/remote-commands/<command_id>/acknowledge", methods=["POST"])
def acknowledge_remote_command(command_id):
    auth = get_auth() if (request.headers.get("X-User-ID") or request.headers.get("X-User-Role")) else None
    if auth is not None and auth["role"] != "SystemIngestion":
        raise err("ERR_UNAUTHORIZED", "only SystemIngestion may acknowledge")
    fire_time_transitions()
    c = get_or_404("remote_commands", command_id)
    if c["status"] != "SENT":
        raise err("ERR_INVALID_STATE", f"cannot acknowledge from {c['status']}")
    c["status"] = "ACKNOWLEDGED"
    _bump(c)
    return success_envelope(render_remote_command(c))


@app.route("/remote-commands/<command_id>/fail", methods=["POST"])
def fail_remote_command(command_id):
    auth = get_auth() if (request.headers.get("X-User-ID") or request.headers.get("X-User-Role")) else None
    if auth is not None and auth["role"] != "SystemIngestion":
        raise err("ERR_UNAUTHORIZED", "only SystemIngestion may fail commands")
    fire_time_transitions()
    c = get_or_404("remote_commands", command_id)
    if c["status"] != "SENT":
        raise err("ERR_INVALID_STATE", f"cannot fail from {c['status']}")
    c["status"] = "FAILED"
    _bump(c)
    return success_envelope(render_remote_command(c))


# ---------------------------------------------------------------------------
# Diagnostic reports
# ---------------------------------------------------------------------------

def render_report(r):
    return {
        "id": r["id"], "vehicle_id": r["vehicle_id"],
        "odometer_km": r["odometer_km"],
        "engine_hours": r["engine_hours"],
        "dtc_codes": r["dtc_codes"],
        "oil_life_pct": r["oil_life_pct"],
        "health_score": r["health_score"],
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


@app.route("/vehicles/<vehicle_id>/diagnostic-reports", methods=["POST"])
def create_diagnostic_report(vehicle_id):
    auth = get_auth() if (request.headers.get("X-User-ID") or request.headers.get("X-User-Role")) else None
    if auth is not None and auth["role"] != "SystemIngestion":
        raise err("ERR_UNAUTHORIZED", "only SystemIngestion may upload reports")
    veh = get_or_404("vehicles", vehicle_id)
    body = request.get_json(silent=True) or {}
    odometer_km = require_field(body, "odometer_km", "int")
    if odometer_km < 0:
        raise err("ERR_INVALID_REQUEST", "odometer_km must be >= 0")
    engine_hours = require_field(body, "engine_hours", "int")
    if engine_hours < 0:
        raise err("ERR_INVALID_REQUEST", "engine_hours must be >= 0")
    dtc_codes = body.get("dtc_codes", [])
    if not isinstance(dtc_codes, list):
        raise err("ERR_INVALID_REQUEST", "dtc_codes must be a list")
    oil_life_pct = require_field(body, "oil_life_pct", "int")
    if oil_life_pct < 0 or oil_life_pct > 100:
        raise err("ERR_INVALID_REQUEST", "oil_life_pct must be 0..100")
    # Odometer monotonicity
    existing = [r for r in DB["diagnostic_reports"].values() if r["vehicle_id"] == vehicle_id]
    if existing:
        latest = max(r["odometer_km"] for r in existing)
        if odometer_km < latest:
            raise err("ERR_ODOMETER_REGRESSION",
                      f"odometer {odometer_km} < latest {latest}")
    health = compute_health_score(dtc_codes, oil_life_pct)
    r = _new_common()
    r.update({
        "vehicle_id": vehicle_id,
        "odometer_km": odometer_km,
        "engine_hours": engine_hours,
        "dtc_codes": list(dtc_codes),
        "oil_life_pct": oil_life_pct,
        "health_score": health,
        "status": "GENERATED",
    })
    DB["diagnostic_reports"][r["id"]] = r
    return success_envelope(render_report(r), status=201)


@app.route("/vehicles/<vehicle_id>/diagnostic-reports", methods=["GET"])
def list_vehicle_diagnostic_reports(vehicle_id):
    auth = require_roles("PlatformAdmin", "Account", "DealerService")
    veh = get_or_404("vehicles", vehicle_id)
    if auth["role"] == "Account" and veh["account_id"] != auth["user_id"]:
        raise err("ERR_UNAUTHORIZED", "not your vehicle")
    rows = [r for r in DB["diagnostic_reports"].values() if r["vehicle_id"] == vehicle_id]
    return list_response([render_report(r) for r in rows])


@app.route("/vehicles/<vehicle_id>/diagnostic-reports/<report_id>", methods=["GET"])
def get_diagnostic_report(vehicle_id, report_id):
    auth = require_roles("PlatformAdmin", "Account", "DealerService")
    get_or_404("vehicles", vehicle_id)
    r = DB["diagnostic_reports"].get(report_id)
    if r is None or r["vehicle_id"] != vehicle_id:
        raise err("ERR_NOT_FOUND", f"report {report_id} not found")
    if auth["role"] == "Account":
        veh = DB["vehicles"][vehicle_id]
        if veh["account_id"] != auth["user_id"]:
            raise err("ERR_UNAUTHORIZED", "not your report")
    return success_envelope(render_report(r))


@app.route("/accounts/diagnostic-reports", methods=["GET"])
def list_diagnostic_reports_flat():
    auth = require_roles("PlatformAdmin", "Account", "DealerService")
    rows = list(DB["diagnostic_reports"].values())
    vehicle_id = request.args.get("vehicle_id")
    if vehicle_id:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    if auth["role"] == "Account":
        own_vehicles = {v["id"] for v in DB["vehicles"].values() if v["account_id"] == auth["user_id"]}
        rows = [r for r in rows if r["vehicle_id"] in own_vehicles]
    return list_response([render_report(r) for r in rows])


@app.route("/accounts/diagnostic-reports/<report_id>", methods=["GET"])
def get_diagnostic_report_aliased(report_id):
    auth = require_roles("PlatformAdmin", "Account", "DealerService")
    r = get_or_404("diagnostic_reports", report_id)
    if auth["role"] == "Account":
        veh = DB["vehicles"].get(r["vehicle_id"])
        if veh is None or veh["account_id"] != auth["user_id"]:
            raise err("ERR_UNAUTHORIZED", "not your report")
    return success_envelope(render_report(r))


# ---------------------------------------------------------------------------
# Dealers
# ---------------------------------------------------------------------------

def render_dealer(d):
    return {
        "id": d["id"], "name": d["name"], "region_code": d["region_code"],
        "service_capacity_per_day": d["service_capacity_per_day"],
        "status": d["status"],
        "created_at": d["created_at"], "updated_at": d["updated_at"], "version": d["version"],
    }


@app.route("/dealers", methods=["POST"])
def create_dealer():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    name = require_field(body, "name", "str")
    region_code = require_field(body, "region_code", "str")
    validate_region_code(region_code)
    capacity = require_field(body, "service_capacity_per_day", "int")
    if capacity < 1:
        raise err("ERR_INVALID_REQUEST", "service_capacity_per_day must be >= 1")
    d = _new_common()
    d.update({
        "name": name, "region_code": region_code,
        "service_capacity_per_day": capacity, "status": "ACTIVE",
    })
    DB["dealers"][d["id"]] = d
    return success_envelope(render_dealer(d), status=201)


@app.route("/dealers", methods=["GET"])
def list_dealers():
    require_roles("PlatformAdmin", "Account", "DealerService")
    rows = list(DB["dealers"].values())
    region = request.args.get("region_code")
    if region:
        rows = [d for d in rows if d["region_code"] == region]
    return list_response([render_dealer(d) for d in rows])


@app.route("/dealers/<dealer_id>", methods=["GET"])
def get_dealer(dealer_id):
    require_roles("PlatformAdmin", "Account", "DealerService")
    d = get_or_404("dealers", dealer_id)
    return success_envelope(render_dealer(d))


@app.route("/accounts/dealers/<dealer_id>", methods=["GET"])
def get_dealer_aliased(dealer_id):
    require_roles("PlatformAdmin", "Account", "DealerService")
    d = get_or_404("dealers", dealer_id)
    return success_envelope(render_dealer(d))


# ---------------------------------------------------------------------------
# Service appointments
# ---------------------------------------------------------------------------

def render_appointment(a):
    return {
        "id": a["id"], "dealer_id": a["dealer_id"], "vehicle_id": a["vehicle_id"],
        "diagnostic_report_id": a["diagnostic_report_id"],
        "scheduled_date": a["scheduled_date"],
        "status": a["status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"],
    }


@app.route("/dealers/<dealer_id>/appointments", methods=["POST"])
def create_appointment(dealer_id):
    auth = require_roles("Account", "DealerService")
    dealer = get_or_404("dealers", dealer_id)
    body = request.get_json(silent=True) or {}
    vehicle_id = require_field(body, "vehicle_id", "str")
    diagnostic_report_id = require_field(body, "diagnostic_report_id", "str")
    scheduled_date = require_field(body, "scheduled_date", "str")
    veh = DB["vehicles"].get(vehicle_id)
    if veh is None:
        raise err("ERR_NOT_FOUND", f"vehicle {vehicle_id} not found")
    rep = DB["diagnostic_reports"].get(diagnostic_report_id)
    if rep is None:
        raise err("ERR_NOT_FOUND", f"report {diagnostic_report_id} not found")
    if auth["role"] == "Account" and veh["account_id"] != auth["user_id"]:
        raise err("ERR_UNAUTHORIZED", "Account can only schedule own vehicles")
    # Strictly future
    try:
        sd = datetime.strptime(scheduled_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "scheduled_date must be ISO date YYYY-MM-DD")
    today = CLOCK.now().date()
    if sd.date() <= today:
        raise err("ERR_APPOINTMENT_IN_PAST", "scheduled_date must be strictly in the future")
    appt = _new_common()
    appt.update({
        "dealer_id": dealer_id,
        "vehicle_id": vehicle_id,
        "diagnostic_report_id": diagnostic_report_id,
        "scheduled_date": scheduled_date,
        "status": "REQUESTED",
    })
    DB["appointments"][appt["id"]] = appt
    return success_envelope(render_appointment(appt), status=201)


@app.route("/dealers/<dealer_id>/appointments", methods=["GET"])
def list_dealer_appointments(dealer_id):
    require_roles("PlatformAdmin", "Account", "DealerService")
    get_or_404("dealers", dealer_id)
    rows = [a for a in DB["appointments"].values() if a["dealer_id"] == dealer_id]
    vehicle_id = request.args.get("vehicle_id")
    report_id = request.args.get("diagnostic_report_id")
    status = request.args.get("status")
    if vehicle_id:
        rows = [a for a in rows if a["vehicle_id"] == vehicle_id]
    if report_id:
        rows = [a for a in rows if a["diagnostic_report_id"] == report_id]
    if status:
        rows = [a for a in rows if a["status"] == status]
    return list_response([render_appointment(a) for a in rows])


@app.route("/accounts/service-appointments", methods=["GET"])
def list_service_appointments_flat():
    auth = require_roles("PlatformAdmin", "Account", "DealerService")
    rows = list(DB["appointments"].values())
    dealer_id = request.args.get("dealer_id")
    vehicle_id = request.args.get("vehicle_id")
    report_id = request.args.get("diagnostic_report_id")
    status = request.args.get("status")
    if dealer_id:
        rows = [a for a in rows if a["dealer_id"] == dealer_id]
    if vehicle_id:
        rows = [a for a in rows if a["vehicle_id"] == vehicle_id]
    if report_id:
        rows = [a for a in rows if a["diagnostic_report_id"] == report_id]
    if status:
        rows = [a for a in rows if a["status"] == status]
    if auth["role"] == "Account":
        own_vehicles = {v["id"] for v in DB["vehicles"].values() if v["account_id"] == auth["user_id"]}
        rows = [a for a in rows if a["vehicle_id"] in own_vehicles]
    return list_response([render_appointment(a) for a in rows])


@app.route("/accounts/service-appointments/<appointment_id>", methods=["GET"])
def get_service_appointment(appointment_id):
    auth = require_roles("PlatformAdmin", "Account", "DealerService")
    a = get_or_404("appointments", appointment_id)
    if auth["role"] == "Account":
        veh = DB["vehicles"].get(a["vehicle_id"])
        if veh is None or veh["account_id"] != auth["user_id"]:
            raise err("ERR_UNAUTHORIZED", "not your appointment")
    return success_envelope(render_appointment(a))


def _get_appointment_for_dealer(dealer_id, appointment_id):
    get_or_404("dealers", dealer_id)
    a = DB["appointments"].get(appointment_id)
    if a is None or a["dealer_id"] != dealer_id:
        raise err("ERR_NOT_FOUND", f"appointment {appointment_id} not found")
    return a


@app.route("/dealers/<dealer_id>/appointments/<appointment_id>/confirm", methods=["POST"])
def confirm_appointment(dealer_id, appointment_id):
    require_roles("DealerService")
    dealer = get_or_404("dealers", dealer_id)
    a = _get_appointment_for_dealer(dealer_id, appointment_id)
    if a["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", f"cannot confirm from {a['status']}")
    if dealer["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "dealer not ACTIVE")
    confirmed_count = sum(
        1 for x in DB["appointments"].values()
        if x["dealer_id"] == dealer_id
        and x["status"] == "CONFIRMED"
        and x["scheduled_date"] == a["scheduled_date"]
    )
    if confirmed_count >= dealer["service_capacity_per_day"]:
        raise err("ERR_DEALER_CAPACITY_REACHED",
                  f"dealer at capacity {dealer['service_capacity_per_day']} for {a['scheduled_date']}")
    a["status"] = "CONFIRMED"
    _bump(a)
    rep = DB["diagnostic_reports"].get(a["diagnostic_report_id"])
    if rep is not None and rep["status"] == "GENERATED":
        rep["status"] = "SERVICE_SCHEDULED"
        _bump(rep)
    return success_envelope(render_appointment(a))


@app.route("/dealers/<dealer_id>/appointments/<appointment_id>/complete", methods=["POST"])
def complete_appointment(dealer_id, appointment_id):
    require_roles("DealerService")
    a = _get_appointment_for_dealer(dealer_id, appointment_id)
    if a["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", f"cannot complete from {a['status']}")
    a["status"] = "COMPLETED"
    _bump(a)
    return success_envelope(render_appointment(a))


@app.route("/dealers/<dealer_id>/appointments/<appointment_id>/cancel", methods=["POST"])
def cancel_appointment(dealer_id, appointment_id):
    auth = require_roles("Account", "DealerService")
    a = _get_appointment_for_dealer(dealer_id, appointment_id)
    if auth["role"] == "Account":
        veh = DB["vehicles"].get(a["vehicle_id"])
        if veh is None or veh["account_id"] != auth["user_id"]:
            raise err("ERR_UNAUTHORIZED", "not your appointment")
    if a["status"] not in {"REQUESTED", "CONFIRMED"}:
        raise err("ERR_INVALID_STATE", f"cannot cancel from {a['status']}")
    was_confirmed = a["status"] == "CONFIRMED"
    a["status"] = "CANCELLED"
    _bump(a)
    if was_confirmed:
        rep = DB["diagnostic_reports"].get(a["diagnostic_report_id"])
        if rep is not None and rep["status"] == "SERVICE_SCHEDULED":
            # Revert only if no other non-cancelled appointment references the report
            others = [
                x for x in DB["appointments"].values()
                if x["diagnostic_report_id"] == rep["id"]
                and x["id"] != a["id"]
                and x["status"] != "CANCELLED"
            ]
            if not others:
                rep["status"] = "GENERATED"
                _bump(rep)
    return success_envelope(render_appointment(a))


# ---------------------------------------------------------------------------
# Data consents
# ---------------------------------------------------------------------------

CONSENT_TYPES = {"DRIVING_DATA_COLLECTION", "INSURANCE_PROGRAM_SHARING"}


def render_consent(c):
    return {
        "id": c["id"], "account_id": c["account_id"], "consent_type": c["consent_type"],
        "status": c["status"],
        "granted_at": c.get("granted_at"),
        "revoked_at": c.get("revoked_at"),
        "effective_score": c.get("effective_score"),
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def _find_active_consent(account_id, consent_type):
    for c in DB["consents"].values():
        if c["account_id"] == account_id and c["consent_type"] == consent_type \
                and c["status"] != "SUPERSEDED":
            return c
    return None


@app.route("/accounts/<account_id>/consents", methods=["POST"])
def create_consent(account_id):
    auth = require_roles("Account")
    check_account_ownership(auth, account_id)
    account = get_or_404("accounts", account_id)
    body = request.get_json(silent=True) or {}
    consent_type = require_enum(body, "consent_type", CONSENT_TYPES)
    # Dependency: INSURANCE_PROGRAM_SHARING requires DRIVING_DATA_COLLECTION GRANTED
    if consent_type == "INSURANCE_PROGRAM_SHARING":
        dc = _find_active_consent(account_id, "DRIVING_DATA_COLLECTION")
        if dc is None or dc["status"] != "GRANTED":
            raise err("ERR_CONSENT_DEPENDENCY_MISSING",
                      "insurance sharing requires DRIVING_DATA_COLLECTION GRANTED")
    # Supersede prior same-type consent
    prior = _find_active_consent(account_id, consent_type)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        if prior["consent_type"] == "INSURANCE_PROGRAM_SHARING":
            prior["effective_score"] = None
        _bump(prior)
    now = CLOCK.now()
    c = _new_common()
    c.update({
        "account_id": account_id,
        "consent_type": consent_type,
        "status": "GRANTED",
        "granted_at": _iso(now),
        "revoked_at": None,
        "effective_score": None,
    })
    if consent_type == "INSURANCE_PROGRAM_SHARING":
        c["effective_score"] = compute_insurance_score(account_id)
    DB["consents"][c["id"]] = c
    return success_envelope(render_consent(c), status=201)


@app.route("/accounts/<account_id>/consents", methods=["GET"])
def list_account_consents(account_id):
    auth = require_roles("PlatformAdmin", "Account")
    check_account_ownership(auth, account_id)
    get_or_404("accounts", account_id)
    rows = [c for c in DB["consents"].values() if c["account_id"] == account_id]
    ct = request.args.get("consent_type")
    if ct:
        rows = [c for c in rows if c["consent_type"] == ct]
    return list_response([render_consent(c) for c in rows])


@app.route("/accounts/consents", methods=["GET"])
def list_consents_flat():
    auth = require_roles("PlatformAdmin", "Account")
    rows = list(DB["consents"].values())
    account_id = request.args.get("account_id")
    ct = request.args.get("consent_type")
    if account_id:
        rows = [c for c in rows if c["account_id"] == account_id]
    if ct:
        rows = [c for c in rows if c["consent_type"] == ct]
    if auth["role"] == "Account":
        rows = [c for c in rows if c["account_id"] == auth["user_id"]]
    return list_response([render_consent(c) for c in rows])


@app.route("/accounts/consents/<consent_id>", methods=["GET"])
def get_consent_aliased(consent_id):
    auth = require_roles("PlatformAdmin", "Account")
    c = get_or_404("consents", consent_id)
    if auth["role"] == "Account" and c["account_id"] != auth["user_id"]:
        raise err("ERR_UNAUTHORIZED", "not your consent")
    return success_envelope(render_consent(c))


def _get_consent_for_account(account_id, consent_id):
    get_or_404("accounts", account_id)
    c = DB["consents"].get(consent_id)
    if c is None or c["account_id"] != account_id:
        raise err("ERR_NOT_FOUND", f"consent {consent_id} not found")
    return c


@app.route("/accounts/<account_id>/consents/<consent_id>/revoke", methods=["POST"])
def revoke_consent(account_id, consent_id):
    auth = require_roles("Account")
    check_account_ownership(auth, account_id)
    c = _get_consent_for_account(account_id, consent_id)
    if c["status"] != "GRANTED":
        raise err("ERR_INVALID_STATE", f"cannot revoke from {c['status']}")
    c["status"] = "REVOKED"
    c["revoked_at"] = _iso(CLOCK.now())
    if c["consent_type"] == "INSURANCE_PROGRAM_SHARING":
        c["effective_score"] = None
    _bump(c)
    return success_envelope(render_consent(c))


@app.route("/accounts/<account_id>/consents/<consent_id>/grant", methods=["POST"])
def grant_consent(account_id, consent_id):
    auth = require_roles("Account")
    check_account_ownership(auth, account_id)
    c = _get_consent_for_account(account_id, consent_id)
    if c["status"] != "REVOKED":
        raise err("ERR_INVALID_STATE", f"cannot grant from {c['status']}")
    if c["consent_type"] == "INSURANCE_PROGRAM_SHARING":
        dc = _find_active_consent(account_id, "DRIVING_DATA_COLLECTION")
        if dc is None or dc["status"] != "GRANTED":
            raise err("ERR_CONSENT_DEPENDENCY_MISSING",
                      "insurance sharing requires DRIVING_DATA_COLLECTION GRANTED")
    c["status"] = "GRANTED"
    c["granted_at"] = _iso(CLOCK.now())
    c["revoked_at"] = None
    if c["consent_type"] == "INSURANCE_PROGRAM_SHARING":
        c["effective_score"] = compute_insurance_score(account_id)
    _bump(c)
    return success_envelope(render_consent(c))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
