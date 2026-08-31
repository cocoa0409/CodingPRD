"""Core infrastructure: errors, logical clock, in-memory store, response envelope,
auth middleware and request-schema validation helpers.

Every structural name in here is taken literally from SCAFFOLD.yaml /
workspace/PRD.md (headers X-User-ID / X-User-Role, envelope meta/response_type/data,
pagination limit/offset/total_count/has_more, OCC fields expected_tract_version /
expected_haul_contractor_version).
"""

import random
import string
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from functools import wraps

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLES = (
    "PlatformAdmin",
    "OperationsManager",
    "HaulContractor",
    "MillScaler",
    "SafetyOfficer",
    "SettlementAccountant",
)

# ---------------------------------------------------------------------------
# Error catalogue (PRD section 5)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SCALER_MILL_MISMATCH": 403,
    "ERR_CONTRACTOR_NOT_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_MILL_NOT_FOUND": 404,
    "ERR_MILL_CONTRACT_NOT_FOUND": 404,
    "ERR_HAUL_CONTRACTOR_NOT_FOUND": 404,
    "ERR_INSURANCE_CERTIFICATE_NOT_FOUND": 404,
    "ERR_TRUCK_NOT_FOUND": 404,
    "ERR_TRACT_NOT_FOUND": 404,
    "ERR_PRODUCTION_PLAN_NOT_FOUND": 404,
    "ERR_CREW_NOT_FOUND": 404,
    "ERR_CREW_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_HAUL_ROUTE_NOT_FOUND": 404,
    "ERR_SHUTDOWN_ORDER_NOT_FOUND": 404,
    "ERR_LOAD_NOT_FOUND": 404,
    "ERR_DELIVERY_TICKET_NOT_FOUND": 404,
    "ERR_SETTLEMENT_STATEMENT_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_STALE_TRACT_VERSION": 412,
    "ERR_STALE_HAUL_CONTRACTOR_VERSION": 412,
    "ERR_INVALID_TRACT_STATE": 409,
    "ERR_INVALID_LOAD_STATE": 409,
    "ERR_INVALID_TICKET_STATE": 409,
    "ERR_INVALID_STATEMENT_STATE": 409,
    "ERR_INVALID_SHUTDOWN_ORDER_STATE": 409,
    "ERR_INVALID_PLAN_STATE": 409,
    "ERR_INVALID_MILL_CONTRACT_STATE": 409,
    "ERR_TRACT_NOT_ACTIVE": 409,
    "ERR_MILL_NOT_RECEIVING": 409,
    "ERR_ROUTE_NOT_OPEN": 409,
    "ERR_TRUCK_OUT_OF_SERVICE": 409,
    "ERR_NO_ELIGIBLE_CREW": 409,
    "ERR_PLAN_NOT_APPROVED": 409,
    "ERR_LOADS_STILL_OPEN": 409,
    "ERR_ACTIVE_SHUTDOWN_ORDER": 409,
    "ERR_CONTRACTOR_NOT_COMPLIANT": 422,
    "ERR_COMPLIANCE_SCORE_TOO_LOW": 422,
    "ERR_INSURANCE_COVERAGE_INCOMPLETE": 422,
    "ERR_WET_THRESHOLD_NOT_MET": 422,
    "ERR_WET_THRESHOLD_STILL_MET": 422,
    "ERR_SEASONAL_ACCESS_CLOSED": 422,
    "ERR_CREW_WINDOW_CONFLICT": 409,
    "ERR_TRUCK_WINDOW_CONFLICT": 409,
    "ERR_CONTRACT_PERIOD_CLOSED": 422,
    "ERR_PERIOD_OVERLAP": 409,
    "ERR_PERMIT_CLASS_INSUFFICIENT": 422,
    "ERR_ROUTE_TRACT_MILL_MISMATCH": 422,
    "ERR_SPECIES_GRADE_MISMATCH": 422,
    "ERR_OVERWEIGHT_LOAD": 422,
    "ERR_ZERO_NET_TONS": 422,
    "ERR_QUOTA_EXCEEDED": 422,
    "ERR_OVERRUN_TOLERANCE_EXCEEDED": 422,
    "ERR_NO_SETTLEABLE_LOADS": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Enumerations (PRD 2.10)
# ---------------------------------------------------------------------------
SPECIES = ("DOUGLAS_FIR", "WESTERN_HEMLOCK", "RED_ALDER", "PONDEROSA_PINE")
GRADES = ("PEELER", "SAWLOG_1", "SAWLOG_2", "PULP")
PERMIT_CLASSES = ("STANDARD", "DIVISIBLE_LOAD_PERMIT", "LONGER_COMBINATION")
PERMIT_RANK = {"STANDARD": 1, "DIVISIBLE_LOAD_PERMIT": 2, "LONGER_COMBINATION": 3}
ACCESS_CLASSES = ("ALL_SEASON", "SUMMER_ONLY", "FROZEN_ONLY")
AXLE_CONFIGS = ("FIVE_AXLE", "SIX_AXLE", "SEVEN_AXLE")
CREW_TYPES = ("HAND_FALLING", "MECHANIZED_GROUND", "CABLE_YARDING")
COVERAGE_TYPES = ("GENERAL_LIABILITY", "AUTO_LIABILITY", "WORKERS_COMP")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
SHUTDOWN_REASONS = ("WET_WEATHER", "FROST_LAW", "FIRE_DANGER", "SAFETY_STAND_DOWN")
REJECT_REASONS = ("SPECIES_MISMATCH", "EXCESS_DEFECT", "CONTAMINATION", "OVERWEIGHT")
ROUTE_STATUSES = ("OPEN", "POSTED_RESTRICTED", "CLOSED")
RECEIVING_STATUSES = ("OPEN", "CLOSED")
RESERVING_STATUSES = ("DISPATCHED", "IN_TRANSIT", "AT_MILL")

SEASON_MONTHS = {
    "ALL_SEASON": None,
    "SUMMER_ONLY": {5, 6, 7, 8, 9},
    "FROZEN_ONLY": {12, 1, 2},
}


# ---------------------------------------------------------------------------
# Rounding helpers (PRD 2.5) -- always half-up, never banker's rounding
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def tons(value):
    return rhu(value, 2)


def num(value):
    """Serialise a Decimal tonnage/percentage as a JSON number."""
    if value is None:
        return None
    return float(value)


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4) -- startup default is exactly 2026-08-01T00:00:00Z
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = CLOCK_DEFAULT

    def reset(self):
        self.now = CLOCK_DEFAULT

    def iso(self):
        return iso_instant(self.now)

    def date(self):
        return self.now.date()

    def date_str(self):
        return self.now.date().isoformat()


clock = Clock()


def iso_instant(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# ---------------------------------------------------------------------------
# In-memory store.  Starts completely empty on every boot -- nothing is seeded.
# ---------------------------------------------------------------------------
class DB:
    COLLECTIONS = (
        "mills",
        "mill_contracts",
        "haul_contractors",
        "insurance_certificates",
        "trucks",
        "safety_findings",
        "tracts",
        "production_plans",
        "crews",
        "crew_assignments",
        "haul_routes",
        "shutdown_orders",
        "loads",
        "delivery_tickets",
        "settlement_statements",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_record(with_common=True):
    rec = {"id": str(uuid.uuid4()), "_seq": db.next_seq(), "created_at": clock.iso()}
    if with_common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version by exactly 1 (PRD 2.4 / 2.9)."""
    if rec is None:
        return
    rec["updated_at"] = clock.iso()
    rec["version"] = rec.get("version", 1) + 1


def ordered(records):
    """Default list ordering: created_at ascending (PRD 2.3).

    Insertion sequence is the deterministic tie-break; the logical clock is
    frozen unless an admin moves it, so many rows share created_at.  No rule
    anywhere in this system consults an id.
    """
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    now = datetime.now(timezone.utc)
    return {"api_request_id": _request_id(), "api_request_timestamp": iso_instant(now)}


def envelope(data, response_type="object", status=200, pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def ok(data):
    return envelope(data, "object", 200)


def created(data):
    return envelope(data, "object", 201)


def error_response(error_id, message):
    meta = _meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), ERROR_HTTP.get(error_id, 400)


def paginated(records, serializer):
    """Apply limit/offset over an already-ordered record list."""
    limit, offset = pagination_params()
    total = len(records)
    window = records[offset: offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return envelope([serializer(r) for r in window], "array", 200, pagination)


PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGINATION_DEFAULT_LIMIT
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_VALIDATION", "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            fail("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


# ---------------------------------------------------------------------------
# Auth middleware (PRD 2.1 / ladder rungs 1 and 2)
# ---------------------------------------------------------------------------
class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "valid X-User-ID and X-User-Role headers are required")
    return Caller(user_id, role)


def authorize(caller, roles):
    if caller.role not in roles:
        fail("ERR_UNAUTHORIZED", "role %s may not call this endpoint" % caller.role)


def endpoint(*roles):
    """Decorator running ladder rungs 1 (authentication) and 2 (authorisation)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            caller = authenticate()
            authorize(caller, roles)
            return fn(caller, *args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Request-schema validation helpers (ladder rung 3 -> ERR_VALIDATION 400)
# ---------------------------------------------------------------------------
def body():
    payload = request.get_json(silent=True)
    if payload is None:
        if request.data:
            fail("ERR_VALIDATION", "request body must be a JSON object")
        return {}
    if not isinstance(payload, dict):
        fail("ERR_VALIDATION", "request body must be a JSON object")
    return payload


def _present(payload, name):
    return name in payload and payload[name] is not None


def req_str(payload, name, min_len=1, max_len=None, required=True, default=None):
    if not _present(payload, name):
        if required:
            fail("ERR_VALIDATION", "%s is required" % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_VALIDATION", "%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_VALIDATION", "%s must be at most %d characters" % (name, max_len))
    return value


def req_enum(payload, name, allowed, required=True, default=None):
    if not _present(payload, name):
        if required:
            fail("ERR_VALIDATION", "%s is required" % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_VALIDATION", "%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def req_int(payload, name, minimum=None, maximum=None, required=True, default=None):
    if not _present(payload, name):
        if required:
            fail("ERR_VALIDATION", "%s is required" % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "%s must be <= %s" % (name, maximum))
    return value


def req_num(
    payload,
    name,
    minimum=None,
    maximum=None,
    exclusive_min=False,
    required=True,
    default=None,
    max_places=None,
):
    if not _present(payload, name):
        if required:
            fail("ERR_VALIDATION", "%s is required" % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        fail("ERR_VALIDATION", "%s must be a number" % name)
    if isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a number" % name)
    try:
        dec = D(value)
    except (InvalidOperation, ValueError):
        fail("ERR_VALIDATION", "%s must be a number" % name)
    if dec != dec or dec.is_infinite():
        fail("ERR_VALIDATION", "%s must be a finite number" % name)
    if minimum is not None:
        if exclusive_min:
            if dec <= D(minimum):
                fail("ERR_VALIDATION", "%s must be greater than %s" % (name, minimum))
        elif dec < D(minimum):
            fail("ERR_VALIDATION", "%s must be >= %s" % (name, minimum))
    if maximum is not None and dec > D(maximum):
        fail("ERR_VALIDATION", "%s must be <= %s" % (name, maximum))
    if max_places is not None:
        exponent = dec.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_places:
            fail("ERR_VALIDATION", "%s may carry at most %d decimal places" % (name, max_places))
    return dec


def req_date(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            fail("ERR_VALIDATION", "%s is required" % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a YYYY-MM-DD date string" % name)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        fail("ERR_VALIDATION", "%s must be a YYYY-MM-DD date string" % name)
    return parsed


def req_datetime(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            fail("ERR_VALIDATION", "%s is required" % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be an ISO 8601 timestamp" % name)
    parsed = parse_instant(value)
    if parsed is None:
        fail("ERR_VALIDATION", "%s must be an ISO 8601 timestamp" % name)
    return parsed


def parse_instant(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_date(value):
    """Parse a stored YYYY-MM-DD string into a date (None passes through)."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def date_str(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()
