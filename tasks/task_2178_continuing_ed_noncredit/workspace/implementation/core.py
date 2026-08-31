"""Core infrastructure: logical clock, in-memory store, response envelope,
error catalog, auth/RBAC and request-shape validation helpers.

Every structural name in this module (header names, envelope field names,
pagination parameter names, OCC field names, error ids) is taken verbatim
from SCAFFOLD.yaml / PRD.md.
"""
import math
import random
import string
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_COURSE_NOT_FOUND": 404,
    "ERR_OFFERING_NOT_FOUND": 404,
    "ERR_LEARNER_NOT_FOUND": 404,
    "ERR_INSTRUCTOR_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_VOUCHER_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_COMPLETION_RECORD_NOT_FOUND": 404,
    "ERR_PETITION_NOT_FOUND": 404,
    "ERR_REQUEST_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_OFFERING_NOT_OPEN": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_COURSE_RETIRED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_PREREQUISITE_NOT_MET": 422,
    "ERR_ATTENDANCE_BELOW_THRESHOLD": 422,
    "ERR_CENSUS_TOO_EARLY": 409,
    "ERR_OFFERING_NOT_ENDED": 409,
    "ERR_REFUND_WINDOW_CLOSED": 422,
    "ERR_INSTRUCTOR_SCHEDULE_CONFLICT": 409,
    "ERR_LEARNER_LOAD_EXCEEDED": 409,
    "ERR_TRANSFER_TARGET_INCOMPATIBLE": 422,
    "ERR_CITATION_NOT_ELIGIBLE": 422,
    "ERR_DUPLICATE_REGISTRATION": 409,
    "ERR_CPL_DUPLICATE_AWARD": 409,
    "ERR_CPL_REVISION_LIMIT": 409,
    "ERR_OFFERING_FULL": 409,
    "ERR_VOUCHER_NOT_USABLE": 422,
    "ERR_ACCOUNT_FUNDS_INSUFFICIENT": 402,
    "ERR_VOUCHER_INSUFFICIENT_BALANCE": 402,
    "ERR_TRANSFER_CREDIT_INSUFFICIENT": 402,
    "ERR_CPL_AWARD_ZERO": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Time helpers + logical clock
# ---------------------------------------------------------------------------

INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock(object):
    def __init__(self):
        self.now = INITIAL_CLOCK

    def set(self, dt):
        self.now = dt


CLOCK = Clock()


def now():
    return CLOCK.now


def parse_dt(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------

def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places=0):
    """round half up to `places` decimal places -> Decimal"""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def num(value, places):
    """Serialize a Decimal to a JSON number carrying exactly `places` dp."""
    if value is None:
        return None
    return float(rhu(value, places))


# ---------------------------------------------------------------------------
# In-memory store (empty on every boot; nothing is ever seeded)
# ---------------------------------------------------------------------------

class Store(object):
    def __init__(self):
        self.courses = {}
        self.offerings = {}
        self.learners = {}
        self.instructors = {}
        self.corporate_accounts = {}
        self.vouchers = {}
        self.registrations = {}
        self.instructor_contracts = {}
        self.completion_records = {}
        self.cpl_petitions = {}
        self.cpl_citations = {}
        self.refund_transfer_requests = {}
        self.marketing_memberships = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()
LOCK = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    ts = now()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": DB.next_seq(),
    }
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Register one mutation of a resource: bump version, refresh updated_at."""
    if rec is None:
        return
    if "version" in rec:
        rec["version"] = rec["version"] + 1
    if "updated_at" in rec:
        rec["updated_at"] = now()


def ordered(values):
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def envelope_object(data):
    return {"meta": _meta(), "response_type": "object", "data": data}


def envelope_array(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return {"meta": meta, "response_type": "array", "data": items}


def envelope_error(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

ROLES = ("ProgramAdmin", "Registrar", "Learner", "Instructor",
         "CorporateSponsor", "Anonymous")


class Actor(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id


def authenticate(allowed_roles):
    """Validation priority 1 then 2."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role missing or not a declared role")
    if role != "Anonymous" and (user_id is None or user_id == ""):
        fail("ERR_UNAUTHENTICATED", "X-User-ID is required for role %s" % role)
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint" % role)
    return Actor(role, user_id)


def own(condition):
    if not condition:
        fail("ERR_NOT_RESOURCE_OWNER", "Caller does not own the addressed resource")


# ---------------------------------------------------------------------------
# Request body / shape validation (priority 3)
# ---------------------------------------------------------------------------

def body():
    if request.data:
        payload = request.get_json(silent=True)
        if payload is None:
            fail("ERR_INVALID_REQUEST", "Request body is not valid JSON")
        if not isinstance(payload, dict):
            fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
        return payload
    return {}


def bad(message):
    fail("ERR_INVALID_REQUEST", message)


def req_present(payload, field):
    if field not in payload or payload[field] is None:
        bad("Field '%s' is required" % field)
    return payload[field]


def as_str(payload, field, required=True, allow_null=False, min_len=1, max_len=None):
    if field not in payload or payload[field] is None:
        if required and not allow_null:
            bad("Field '%s' is required" % field)
        return None
    value = payload[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string" % field)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is too short" % field)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is too long" % field)
    return value


def as_int(payload, field, required=True, minimum=None, maximum=None, default=None):
    if field not in payload or payload[field] is None:
        if required:
            bad("Field '%s' is required" % field)
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer" % field)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s" % (field, maximum))
    return value


def as_bool(payload, field, required=True, default=None):
    if field not in payload or payload[field] is None:
        if required:
            bad("Field '%s' is required" % field)
        return default
    value = payload[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean" % field)
    return value


def as_decimal(payload, field, required=True, gt=None, gte=None, lte=None,
               max_places=None, default=None):
    if field not in payload or payload[field] is None:
        if required:
            bad("Field '%s' is required" % field)
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number" % field)
    try:
        dec = D(value)
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number" % field)
    if gt is not None and not dec > D(gt):
        bad("Field '%s' must be > %s" % (field, gt))
    if gte is not None and not dec >= D(gte):
        bad("Field '%s' must be >= %s" % (field, gte))
    if lte is not None and not dec <= D(lte):
        bad("Field '%s' must be <= %s" % (field, lte))
    if max_places is not None:
        normalized = dec.normalize()
        exponent = normalized.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_places:
            bad("Field '%s' carries too many decimal places" % field)
    return dec


def as_enum(payload, field, members, required=True, default=None):
    if field not in payload or payload[field] is None:
        if required:
            bad("Field '%s' is required" % field)
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in members:
        bad("Field '%s' must be one of %s" % (field, ", ".join(members)))
    return value


def as_dt(payload, field, required=True):
    if field not in payload or payload[field] is None:
        if required:
            bad("Field '%s' is required" % field)
        return None
    value = payload[field]
    parsed = parse_dt(value) if isinstance(value, str) else None
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC instant" % field)
    return parsed


def as_id(payload, field, required=True):
    if field not in payload or payload[field] is None:
        if required:
            bad("Field '%s' is required" % field)
        return None
    value = payload[field]
    if not isinstance(value, str) or not value:
        bad("Field '%s' must be a string identifier" % field)
    return value


# ---------------------------------------------------------------------------
# Pagination + filtering (priority 3 for the limit/offset shape)
# ---------------------------------------------------------------------------

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            bad("limit must be between %d and %d" % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset < 0:
            bad("offset must be >= 0")
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    return envelope_array([serializer(r) for r in page], limit, offset, total)


def qfilter(rows, field, param=None):
    param = param or field
    value = request.args.get(param)
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


# ---------------------------------------------------------------------------
# Path/body existence lookups (priorities 4 and 5)
# ---------------------------------------------------------------------------

def _lookup(table, key, error_id):
    rec = table.get(key)
    if rec is None:
        fail(error_id, "%s does not resolve" % error_id)
    return rec


def get_course(cid):
    return _lookup(DB.courses, cid, "ERR_COURSE_NOT_FOUND")


def get_offering(oid):
    return _lookup(DB.offerings, oid, "ERR_OFFERING_NOT_FOUND")


def get_learner(lid):
    return _lookup(DB.learners, lid, "ERR_LEARNER_NOT_FOUND")


def get_instructor(iid):
    return _lookup(DB.instructors, iid, "ERR_INSTRUCTOR_NOT_FOUND")


def get_account(aid):
    return _lookup(DB.corporate_accounts, aid, "ERR_ACCOUNT_NOT_FOUND")


def get_voucher(vid):
    return _lookup(DB.vouchers, vid, "ERR_VOUCHER_NOT_FOUND")


def get_registration(rid):
    return _lookup(DB.registrations, rid, "ERR_REGISTRATION_NOT_FOUND")


def get_contract(cid):
    return _lookup(DB.instructor_contracts, cid, "ERR_CONTRACT_NOT_FOUND")


def get_completion(crid):
    return _lookup(DB.completion_records, crid, "ERR_COMPLETION_RECORD_NOT_FOUND")


def get_petition(pid):
    return _lookup(DB.cpl_petitions, pid, "ERR_PETITION_NOT_FOUND")


def get_request(rid):
    return _lookup(DB.refund_transfer_requests, rid, "ERR_REQUEST_NOT_FOUND")


def days_between(later, earlier):
    return int(math.floor((later - earlier).total_seconds() / 86400.0))
