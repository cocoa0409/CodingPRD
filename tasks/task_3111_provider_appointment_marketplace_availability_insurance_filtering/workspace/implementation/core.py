"""Core infrastructure: logical clock, in-memory store, response envelope, errors, auth."""

import re
import secrets
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

INITIAL_CLOCK_ISO = "2026-09-01T00:00:00Z"
INITIAL_EPOCH = 1


def parse_iso(s):
    """Parse an ISO 8601 string (with optional Z suffix) to an aware datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now_iso():
    return fmt_iso(datetime.now(timezone.utc))


class Clock:
    def __init__(self):
        self._dt = parse_iso(INITIAL_CLOCK_ISO)

    def now(self):
        return self._dt

    def now_iso(self):
        return fmt_iso(self._dt)

    def set(self, iso):
        self._dt = parse_iso(iso)


class Store:
    """In-memory store. Fresh instance per process -> fresh state per boot."""

    def __init__(self):
        self.clock = Clock()
        self.epoch = INITIAL_EPOCH
        self.practices = {}
        self.providers = {}
        self.slots = {}
        self.appointment_types = {}
        self.plans = {}
        self.attestations = {}
        self.patients = {}
        self.contact_events = {}
        self.bookings = {}
        self.charges = {}
        self.invoices = {}
        self.ledger_entries = {}
        self.complaints = {}
        self.reviews = {}
        self.visit_records = {}
        self.audit_cases = {}
        # insertion-order counters for stable created_at ordering within a second
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


def new_id():
    return str(uuid.uuid4())


def round_half_up_cents(value_decimal):
    """Round a Decimal to integer cents using ROUND_HALF_UP."""
    return int(Decimal(value_decimal).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

ERR_HTTP = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN": 403,
    "ERR_OWNERSHIP_MISMATCH": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_PRACTICE_NOT_FOUND": 404,
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_ATTESTATION_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_CHARGE_NOT_FOUND": 404,
    "ERR_AUDIT_CASE_NOT_FOUND": 404,
    "ERR_TYPE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_PRACTICE_NOT_ACTIVE": 409,
    "ERR_PROVIDER_NOT_BOOKABLE": 409,
    "ERR_PLAN_NOT_ACTIVE": 409,
    "ERR_SLOT_NOT_OPEN": 409,
    "ERR_BOOKING_NOT_CANCELLABLE": 409,
    "ERR_COMPLAINT_NOT_OPEN": 409,
    "ERR_INVOICE_NOT_DISPUTABLE": 409,
    "ERR_INVOICE_NOT_PAYABLE": 409,
    "ERR_UNRESOLVED_FINDINGS": 409,
    "ERR_SLOT_IN_PAST": 422,
    "ERR_LEAD_TIME_VIOLATION": 422,
    "ERR_CANCELLATION_TOO_LATE": 422,
    "ERR_NO_SHOW_TOO_EARLY": 422,
    "ERR_PLAN_NOT_ACCEPTED": 422,
    "ERR_TYPE_MAPPING_MISSING": 422,
    "ERR_NEW_PATIENT_TYPE_BLOCKED": 422,
    "ERR_RELIABILITY_GATE": 403,
    "ERR_SLOT_OVERLAP": 409,
    "ERR_DUPLICATE_ATTESTATION": 409,
    "ERR_DUPLICATE_REVIEW": 409,
    "ERR_VISIT_NOT_VERIFIED": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_PENDING_CHARGES": 409,
    "ERR_BILLING_MODE_MISMATCH": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = ERR_HTTP[error_id]


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(22))


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": wall_now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return body, status


def success_list(items, total_count, limit, offset, status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": wall_now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return body, status


def error_body(err):
    return {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": wall_now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }, err.http_status


# ---------------------------------------------------------------------------
# Auth / roles
# ---------------------------------------------------------------------------

DECLARED_ROLES = {"Anonymous", "Patient", "Provider", "PracticeStaff", "OpsAdmin"}
ANY = "Any"


def get_actor():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in DECLARED_ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and X-User-Role must be a declared role",
        )
    return uid, role


def require_role(allowed):
    uid, role = get_actor()
    if ANY in allowed:
        return uid, role
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", "Role not authorized for this endpoint")
    return uid, role


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def get_json_body(required=False):
    if not request.data:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Request body required")
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be valid JSON")
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_bool(v):
    return isinstance(v, bool)


def req_str(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    return v


def req_int(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    if not is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    return v


def opt_int(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not is_bool(v):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def req_enum(body, field, values):
    v = req_str(body, field)
    if v not in values:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(values)}")
    return v


def req_datetime(body, field):
    v = req_str(body, field)
    try:
        return parse_iso(v)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 datetime")


def parse_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    try:
        limit = 10 if limit is None else int(limit)
    except Exception:
        limit = 10
    try:
        offset = 0 if offset is None else int(offset)
    except Exception:
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


def sort_by_created(records):
    return sorted(records, key=lambda r: (r["_created_at_dt"], r["_seq"]))


# ---------------------------------------------------------------------------
# Common-field resource factory
# ---------------------------------------------------------------------------

def new_resource(seq, common=True):
    now = DB.clock.now_iso()
    rec = {
        "id": new_id(),
        "created_at": now,
    }
    if common:
        rec["updated_at"] = now
        rec["version"] = 1
    rec["_created_at_dt"] = DB.clock.now()
    rec["_seq"] = seq
    return rec


def touch(rec):
    rec["updated_at"] = DB.clock.now_iso()
    rec["version"] += 1


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Reliability helpers
# ---------------------------------------------------------------------------

def compute_scores(patient):
    window_edge = DB.epoch - 3
    active = [s for s in patient["strikes"] if s["epoch"] >= window_edge]
    mag = sum(s["magnitude"] for s in active)
    provisional = max(0, min(100, 100 - mag))
    reliability = max(0, min(100, 100 - mag + 10 * patient["recovery_count"]))
    return reliability, provisional


def rescore(patient):
    rel, prov = compute_scores(patient)
    patient["reliability_score"] = rel
    patient["provisional_score"] = prov


# ---------------------------------------------------------------------------
# Bookability derivation
# ---------------------------------------------------------------------------

def recompute_bookable(provider):
    practice = DB.practices.get(provider["practice_id"])
    provider["bookable_in_directory"] = (
        provider["status"] == "ACTIVE" and practice is not None and practice["status"] == "ACTIVE"
    )


def recompute_practice_providers(practice_id):
    for p in DB.providers.values():
        if p["practice_id"] == practice_id:
            recompute_bookable(p)
