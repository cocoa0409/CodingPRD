"""Shared plumbing: error catalog, response envelope, auth context, payload
validation, pagination, and the two timestamp rendering families.

Timestamp doctrine (PRD section 2.5 / 2.6):
  * audit family  -- created_at / updated_at / api_request_timestamp render
    from the logical clock with exactly three fractional digits.
  * domain family -- published_at / expiration_date / fulfilled_at and
    clock echoes render exactly as the clock reads (second precision when the
    clock sits on a whole second).
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from db import get_clock

# ---------------------------------------------------------------------------
# Error catalog
# ---------------------------------------------------------------------------

ERR_MISSING_OR_INVALID_USER_CONTEXT = "ERR_MISSING_OR_INVALID_USER_CONTEXT"
ERR_UNAUTHORIZED_ROLE = "ERR_UNAUTHORIZED_ROLE"
ERR_FORBIDDEN_OWNERSHIP = "ERR_FORBIDDEN_OWNERSHIP"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_LOT_STATE = "ERR_INVALID_LOT_STATE"
ERR_INVALID_CERTIFICATE_STATE = "ERR_INVALID_CERTIFICATE_STATE"
ERR_INVALID_METHOD_STATE = "ERR_INVALID_METHOD_STATE"
ERR_INVALID_ORDER_STATE = "ERR_INVALID_ORDER_STATE"
ERR_INVALID_CALIBRATION_STATE = "ERR_INVALID_CALIBRATION_STATE"
ERR_INVALID_ROUND_STATE = "ERR_INVALID_ROUND_STATE"
ERR_LOT_NOT_DISTRIBUTABLE = "ERR_LOT_NOT_DISTRIBUTABLE"
ERR_NO_PUBLISHED_CERTIFICATE = "ERR_NO_PUBLISHED_CERTIFICATE"
ERR_NO_REFERENCE_CERTIFICATE = "ERR_NO_REFERENCE_CERTIFICATE"
ERR_INSUFFICIENT_INDEPENDENT_METHODS = "ERR_INSUFFICIENT_INDEPENDENT_METHODS"
ERR_DUPLICATE_ANALYST_METHOD = "ERR_DUPLICATE_ANALYST_METHOD"
ERR_SEGREGATION_OF_DUTIES_VIOLATION = "ERR_SEGREGATION_OF_DUTIES_VIOLATION"
ERR_INSUFFICIENT_UNITS = "ERR_INSUFFICIENT_UNITS"
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"
ERR_TRACEABILITY_CHAIN_BROKEN = "ERR_TRACEABILITY_CHAIN_BROKEN"
ERR_RESOURCE_WINDOW_CONFLICT = "ERR_RESOURCE_WINDOW_CONFLICT"
ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"
ERR_WINDOW_IN_PAST = "ERR_WINDOW_IN_PAST"
ERR_SERVICE_NOT_ACTIVE = "ERR_SERVICE_NOT_ACTIVE"
ERR_OPEN_ORDERS_EXIST = "ERR_OPEN_ORDERS_EXIST"
ERR_INSUFFICIENT_RESULTS = "ERR_INSUFFICIENT_RESULTS"
ERR_DUPLICATE_PARTICIPATION = "ERR_DUPLICATE_PARTICIPATION"
ERR_DUPLICATE_PROGRAM_CODE = "ERR_DUPLICATE_PROGRAM_CODE"
ERR_DUPLICATE_SERVICE_CODE = "ERR_DUPLICATE_SERVICE_CODE"

ALL_ROLES = [
    "ProgramAdmin",
    "Metrologist",
    "CertificationOfficer",
    "InventoryManager",
    "CalibrationCoordinator",
    "AccreditationOfficer",
    "Customer",
]


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def fail(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Decimal helpers (6dp / 3dp metrological quantities, integer cents)
# ---------------------------------------------------------------------------

Q6 = Decimal("0.000001")
Q3 = Decimal("0.001")
Q0 = Decimal("1")


def D(x):
    """Coerce an int/float/str to Decimal exactly (via str, never via float
    binary widening)."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def q6(x):
    return D(x).quantize(Q6, rounding=ROUND_HALF_UP)


def q3(x):
    return D(x).quantize(Q3, rounding=ROUND_HALF_UP)


def round_cents(x):
    """Round half up to a whole cent -> int."""
    return int(D(x).quantize(Q0, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Datetime parsing and the two rendering families
# ---------------------------------------------------------------------------

def parse_dt(value):
    """Parse an ISO-8601 string to an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    t = value.strip()
    if not t:
        return None
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_audit(dt):
    """Audit family: exactly three fractional digits, Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(
        dt.microsecond // 1000
    )


def render_domain(dt):
    """Domain family: render exactly as the clock reads."""
    if dt is None:
        return None
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def num(x):
    """Render a stored Decimal as a JSON number; pass ints/None through."""
    if x is None:
        return None
    if isinstance(x, Decimal):
        return float(x)
    return x


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _meta_base():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": render_audit(get_clock()),
    }


def ok_object(data, code=200):
    body = {"meta": _meta_base(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth context (cascade stages 1-2)
# ---------------------------------------------------------------------------

def auth_context():
    """Stage 1: both headers present and non-empty."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or not role.strip():
        fail(
            ERR_MISSING_OR_INVALID_USER_CONTEXT,
            400,
            "X-User-ID and X-User-Role headers must both be present and non-empty",
        )
    return uid, role


def require_role(role, allowed):
    """Stage 2: role must be one of the endpoint's declared roles."""
    if role not in allowed:
        fail(
            ERR_UNAUTHORIZED_ROLE,
            403,
            "role {} is not permitted for this endpoint".format(role),
        )


def require_target_role(role, to_value, target_map):
    """Stage 2 (target-specific): when the request names a transition target
    that carries a declared role set, the caller's role must be in it."""
    if isinstance(to_value, str) and to_value in target_map:
        require_role(role, target_map[to_value])


# ---------------------------------------------------------------------------
# Request body + payload schema validation (cascade stage 3)
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return data


def _present(b, key):
    return key in b and b[key] is not None


def v_str(b, key, required=True, allow_empty=False):
    if not _present(b, key):
        if required:
            fail(ERR_INVALID_REQUEST, 400, "missing required field: " + key)
        return None
    val = b[key]
    if not isinstance(val, str) or (not allow_empty and val == ""):
        fail(ERR_INVALID_REQUEST, 400, "field {} must be a string".format(key))
    return val


def v_int(b, key, required=True, minv=None, maxv=None):
    if not _present(b, key):
        if required:
            fail(ERR_INVALID_REQUEST, 400, "missing required field: " + key)
        return None
    val = b[key]
    if isinstance(val, bool) or not isinstance(val, int):
        fail(ERR_INVALID_REQUEST, 400, "field {} must be an integer".format(key))
    if minv is not None and val < minv:
        fail(ERR_INVALID_REQUEST, 400, "field {} is below its minimum".format(key))
    if maxv is not None and val > maxv:
        fail(ERR_INVALID_REQUEST, 400, "field {} exceeds its maximum".format(key))
    return val


def v_num(b, key, required=True, positive=False):
    if not _present(b, key):
        if required:
            fail(ERR_INVALID_REQUEST, 400, "missing required field: " + key)
        return None
    val = b[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        fail(ERR_INVALID_REQUEST, 400, "field {} must be a number".format(key))
    if positive and not (val > 0):
        fail(
            ERR_INVALID_REQUEST,
            400,
            "field {} must be strictly positive".format(key),
        )
    return val


def v_bool(b, key, required=False, default=None):
    if not _present(b, key):
        if required:
            fail(ERR_INVALID_REQUEST, 400, "missing required field: " + key)
        return default
    val = b[key]
    if not isinstance(val, bool):
        fail(ERR_INVALID_REQUEST, 400, "field {} must be a boolean".format(key))
    return val


def v_enum(b, key, values, required=True, default=None):
    if not _present(b, key):
        if required:
            fail(ERR_INVALID_REQUEST, 400, "missing required field: " + key)
        return default
    val = b[key]
    if not isinstance(val, str) or val not in values:
        fail(
            ERR_INVALID_REQUEST,
            400,
            "field {} must be one of {}".format(key, sorted(values)),
        )
    return val


def v_dt(b, key, required=True):
    if not _present(b, key):
        if required:
            fail(ERR_INVALID_REQUEST, 400, "missing required field: " + key)
        return None
    dt = parse_dt(b[key])
    if dt is None:
        fail(
            ERR_INVALID_REQUEST,
            400,
            "field {} must be an ISO-8601 timestamp".format(key),
        )
    return dt


def v_num_list(b, key, required=True, min_len=None):
    if not _present(b, key):
        if required:
            fail(ERR_INVALID_REQUEST, 400, "missing required field: " + key)
        return None
    val = b[key]
    if not isinstance(val, list):
        fail(ERR_INVALID_REQUEST, 400, "field {} must be a list".format(key))
    if min_len is not None and len(val) < min_len:
        fail(
            ERR_INVALID_REQUEST,
            400,
            "field {} must contain at least {} entries".format(key, min_len),
        )
    for item in val:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            fail(
                ERR_INVALID_REQUEST,
                400,
                "field {} must contain only numbers".format(key),
            )
    return val


# ---------------------------------------------------------------------------
# Pagination (limit/offset per response_envelope.pagination_fields)
# ---------------------------------------------------------------------------

def page_params():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            fail(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            fail(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def sort_default(records):
    """Every list endpoint sorts by created_at ascending; insertion sequence
    breaks the (common, logical-clock) ties deterministically."""
    return sorted(records, key=lambda e: (e["created_at"], e["_seq"]))


def list_page(records, serializer):
    limit, offset = page_params()
    ordered = sort_default(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serializer(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Existence helpers (cascade stages 4 / 4.5)
# ---------------------------------------------------------------------------

def get_path(store, rid, label):
    rec = store.get(rid)
    if rec is None:
        fail(ERR_NOT_FOUND, 404, "{} not found: {}".format(label, rid))
    return rec


def get_ref(store, rid, label):
    rec = store.get(rid) if isinstance(rid, str) else None
    if rec is None:
        fail(
            ERR_REFERENCE_NOT_FOUND,
            404,
            "referenced {} does not exist".format(label),
        )
    return rec
