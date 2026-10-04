"""Core runtime: logical clock, in-memory store, error catalog, response envelope,
auth middleware, pagination and numeric helpers.

Storage is process-local and in-memory only.  Nothing is seeded at import or
startup: every dict below starts empty so a fresh ``start.sh`` boot is a clean
slate.
"""

import hashlib
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

DECLARED_ROLES = [
    "PlatformAdmin",
    "ProjectManager",
    "ModelCoordinator",
    "ShopForeman",
    "LogisticsCoordinator",
    "ProcurementLead",
    "GeneralForeman",
    "InstallForeman",
]

ERROR_STATUS = {
    "ERR_UNAUTHORIZED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_MODEL_VERSION_NOT_FOUND": 404,
    "ERR_PREFAB_ORDER_NOT_FOUND": 404,
    "ERR_REFERENCED_ENTITY_NOT_FOUND": 404,
    "ERR_AFFECTED_REF_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_PREFAB_TRANSITION": 409,
    "ERR_ENGINEERING_HOLD_ACTIVE": 409,
    "ERR_MATERIAL_HOLD_ACTIVE": 409,
    "ERR_INSTALL_SEQUENCE_VIOLATION": 409,
    "ERR_APPRENTICE_RATIO_EXCEEDED": 409,
    "ERR_HOISTING_WINDOW_CONFLICT": 409,
    "ERR_LAYDOWN_SLOT_UNAVAILABLE": 409,
    "ERR_JURISDICTION_DISPATCH_BAND": 422,
    "ERR_DUPLICATE_TAKEOFF_LINE": 409,
    "ERR_APPRENTICE_PERIOD_INVALID": 422,
    "ERR_MODEL_QUANTITY_UNRESOLVED": 409,
    "ERR_CONDUIT_TYPE_NOT_PERMITTED": 422,
    "ERR_RACK_CAPACITY_EXCEEDED": 409,
    "ERR_LABEL_CODE_MISSING": 422,
    "ERR_REVISION_IMPACT_REQUIRED": 422,
    "ERR_MODEL_SUPERSEDED": 409,
    "ERR_CRAFT_HOURS_EXCEEDED": 409,
    "ERR_SERVICE_LIFECYCLE_INVALID": 422,
    "ERR_SHIFT_BAND_TOO_LONG": 422,
    "ERR_REVISION_SAFETY_BLOCKED": 409,
    "ERR_MATERIAL_RELEASE_DEADLINE": 409,
    "ERR_FABRICATION_WINDOW_LAPSED": 409,
    "ERR_WINDOW_ALREADY_FROZEN": 409,
}

ERROR_MESSAGES = {
    "ERR_UNAUTHORIZED": "X-User-ID and X-User-Role headers are required and the role must be declared.",
    "ERR_FORBIDDEN": "The acting role is not permitted for this operation.",
    "ERR_PROJECT_NOT_FOUND": "The project named in the path or body does not exist.",
    "ERR_MODEL_VERSION_NOT_FOUND": "The model version named in the path or body does not exist.",
    "ERR_PREFAB_ORDER_NOT_FOUND": "The work package named in the path does not exist.",
    "ERR_REFERENCED_ENTITY_NOT_FOUND": "A referenced entity id does not exist.",
    "ERR_AFFECTED_REF_NOT_FOUND": "An entry of impact_keys does not resolve to a declared artifact.",
    "ERR_STALE_VERSION": "The supplied expected version does not equal the parent entity's current version.",
    "ERR_INVALID_PREFAB_TRANSITION": "The target entity is not in the from-state its transaction requires.",
    "ERR_ENGINEERING_HOLD_ACTIVE": "A non-terminal revision names an artifact of this work package's assembly set.",
    "ERR_MATERIAL_HOLD_ACTIVE": "A project material gate commodity has no declared procurement release.",
    "ERR_INSTALL_SEQUENCE_VIOLATION": "A lower-indexed activity of another trade still holds the bay.",
    "ERR_APPRENTICE_RATIO_EXCEEDED": "Cumulative apprentice hours would exceed ratio_limit x journeyman hours.",
    "ERR_HOISTING_WINDOW_CONFLICT": "The proposed hoisting window conflicts with an already frozen window.",
    "ERR_LAYDOWN_SLOT_UNAVAILABLE": "No laydown slot is free for the requested window.",
    "ERR_JURISDICTION_DISPATCH_BAND": "The dispatched worker's home jurisdiction or apprentice band is invalid.",
    "ERR_DUPLICATE_TAKEOFF_LINE": "The stamped takeoff hash already exists on this model version.",
    "ERR_APPRENTICE_PERIOD_INVALID": "apprentice_period must be 1..5 exactly when the classification is APPRENTICE.",
    "ERR_MODEL_QUANTITY_UNRESOLVED": "The model version extraction set is empty or would drive the quantity total below 1.",
    "ERR_CONDUIT_TYPE_NOT_PERMITTED": "The conduit run type or conduit code is not permitted for this assembly.",
    "ERR_RACK_CAPACITY_EXCEEDED": "The rack's reserved stream and phase capacity would exceed 0.95 of its value capacity.",
    "ERR_LABEL_CODE_MISSING": "A fabricated-content label code was supplied without a positive label percentage.",
    "ERR_REVISION_IMPACT_REQUIRED": "A revision must carry at least one impact key.",
    "ERR_MODEL_SUPERSEDED": "The target model version is already superseded or already targeted by an approved revision.",
    "ERR_CRAFT_HOURS_EXCEEDED": "Tied shipment hours plus revised trade hours exceed the revision's adjusted flow hours.",
    "ERR_SERVICE_LIFECYCLE_INVALID": "replacement_lifecycle_percent is below prior_lifecycle_percent.",
    "ERR_SHIFT_BAND_TOO_LONG": "qualification_state_code exceeds 40 characters.",
    "ERR_REVISION_SAFETY_BLOCKED": "The revision's safety gate is BLOCKED and cannot be approved.",
    "ERR_MATERIAL_RELEASE_DEADLINE": "The release was declared after its planned release date.",
    "ERR_FABRICATION_WINDOW_LAPSED": "The derived hoisting window start already precedes the logical clock.",
    "ERR_WINDOW_ALREADY_FROZEN": "The hoisting window was already frozen by a prior release-to-shop record.",
}


class ApiError(Exception):
    """Carries the scaffold error id and the HTTP status it maps to."""

    def __init__(self, error_id, message=None, **extra):
        self.error_id = error_id
        self.message = message or ERROR_MESSAGES.get(error_id, error_id)
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.extra = extra
        super().__init__(self.message)


def fail(error_id, message=None, **extra):
    raise ApiError(error_id, message, **extra)


def abort_unauthorized():
    fail("ERR_UNAUTHORIZED")


# --------------------------------------------------------------------------
# Numeric helpers
# --------------------------------------------------------------------------

def rhu(value, places=0):
    """Round half up (away from zero at the .5 boundary) to ``places`` decimals."""
    if value is None:
        return 0 if places == 0 else 0.0
    d = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    rounded = d.quantize(quantum, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(rounded)
    return float(rounded)


def dec(value):
    return Decimal(str(value if value is not None else 0))


def num(value, default=0):
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def ceil_int(value):
    d = Decimal(str(value))
    return int(d.to_integral_value(rounding="ROUND_CEILING"))


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------

def to_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def wall_now_iso():
    return iso(datetime.now(timezone.utc))


def shift_days(dt, days):
    """cc_shift_days(d, n) = d + n days."""
    return dt + timedelta(days=days)


def whole_days_between(start, end):
    """Whole (floored) day count between two instants."""
    if start is None or end is None:
        return 0
    delta = end - start
    return int(delta.total_seconds() // 86400)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

class LogicalClock:
    def __init__(self):
        self._now = to_dt(DEFAULT_CLOCK_ISO)

    def now(self):
        return self._now

    def now_iso(self):
        return iso(self._now)

    def set(self, value):
        dt = to_dt(value)
        if dt is None:
            fail("ERR_INVALID_PREFAB_TRANSITION", "to_iso8601 is required")
        self._now = dt
        return self._now


CLOCK = LogicalClock()


# --------------------------------------------------------------------------
# In-memory store
# --------------------------------------------------------------------------

TABLES = [
    "projects",
    "workers",
    "trade_contract_rates",
    "trade_activities",
    "crew_days",
    "compliance_ledger",
    "model_versions",
    "takeoff_lines",
    "assemblies",
    "racks",
    "prefab_orders",
    "prefab_components",
    "revisions",
    "rework_jobs",
    "material_releases",
]


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for table in TABLES:
            setattr(self, table, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- generic helpers ---------------------------------------------------
    def all(self, table):
        return list(getattr(self, table).values())

    def find(self, table, ident):
        return getattr(self, table).get(ident)

    def put(self, table, record):
        getattr(self, table)[record["id"]] = record
        return record


DB = Store()


def new_record(**fields):
    """Mint a record carrying the mandatory common field set."""
    stamp = CLOCK.now_iso()
    record = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 0,
        "_seq": DB.next_seq(),
    }
    record.update(fields)
    return record


def touch(record):
    """Record a mutating operation: refresh updated_at and bump version."""
    record["updated_at"] = CLOCK.now_iso()
    record["version"] = int(record.get("version", 0)) + 1
    return record


def serialize(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def serialize_all(records):
    return [serialize(r) for r in records]


def sort_key(record):
    return (record.get("created_at") or "", record.get("_seq") or 0)


def takeoff_hash(model_version_id, zone_code, assembly_code, quantity):
    raw = "%s|%s|%s|%s" % (model_version_id, zone_code, assembly_code, quantity)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------

def _request_id():
    return "req_" + uuid.uuid4().hex[:16].upper()


def build_envelope(data, response_type="object", pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return {"meta": meta, "response_type": response_type, "data": data}


def envelope_error(error_id, message):
    return {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": wall_now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# --------------------------------------------------------------------------
# Auth / RBAC
# --------------------------------------------------------------------------

def require(roles):
    """Enforce the two auth validations, then the role matrix for the route."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        fail("ERR_UNAUTHORIZED")
    if roles and role not in roles:
        fail("ERR_FORBIDDEN")
    return user_id, role


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------

def page_records(records):
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = 10 if raw_limit in (None, "") else int(raw_limit)
        offset = 0 if raw_offset in (None, "") else int(raw_offset)
    except (TypeError, ValueError):
        fail("ERR_INVALID_PREFAB_TRANSITION", "limit and offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        fail("ERR_INVALID_PREFAB_TRANSITION", "limit must be 1..100 and offset must be >= 0")
    ordered = sorted(records, key=sort_key)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


def list_response(records):
    page, pagination = page_records(records)
    return build_envelope(serialize_all(page), "array", pagination)


def object_response(record, status_code=200):
    body = build_envelope(serialize(record), "object")
    return body, status_code


def empty_response():
    return build_envelope({}, "object"), 200