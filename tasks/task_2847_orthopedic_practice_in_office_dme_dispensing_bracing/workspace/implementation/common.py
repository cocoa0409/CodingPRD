"""Shared foundation: logical clock, response envelope, errors, auth, validation."""
import math
import re
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# ---------------------------------------------------------------- logical clock

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": CLOCK_EPOCH}


def now() -> datetime:
    return _clock["now"]


def set_clock(value: datetime) -> datetime:
    previous = _clock["now"]
    _clock["now"] = value
    return previous


def today() -> date:
    return _clock["now"].date()


# ------------------------------------------------------------ time formatting

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fmt_instant(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_instant(value):
    """Tolerant ISO-8601 instant parser; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _DATE_RE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def whole_days(start, end):
    """Floored whole days between two instants (may be negative)."""
    if start is None or end is None:
        return 0
    return math.floor((end - start).total_seconds() / 86400.0)


def ceil_minutes(start, end):
    """Ceiling minutes between two instants, never below 1."""
    seconds = (end - start).total_seconds()
    minutes = math.ceil(seconds / 60.0)
    if minutes < 1:
        minutes = 1
    return int(minutes)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


# ---------------------------------------------------------------------- money

def round_half_up(value) -> int:
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ------------------------------------------------------------- error catalog

ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ACTOR_NOT_FOUND": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CLINIC_NOT_FOUND": 404,
    "ERR_SUPPLIER_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_PHYSICIAN_NOT_FOUND": 404,
    "ERR_FITTER_NOT_FOUND": 404,
    "ERR_PAR_LEVEL_NOT_FOUND": 404,
    "ERR_ENCOUNTER_NOT_FOUND": 404,
    "ERR_PRIOR_AUTH_NOT_FOUND": 404,
    "ERR_ABN_NOTICE_NOT_FOUND": 404,
    "ERR_FAB_ORDER_NOT_FOUND": 404,
    "ERR_RETURN_NOT_FOUND": 404,
    "ERR_FITTING_RECORD_NOT_FOUND": 404,
    "ERR_CLINIC_SCOPE_MISMATCH": 403,
    "ERR_INVALID_CLINICAL_STATE": 409,
    "ERR_INVALID_FINANCIAL_STATE": 409,
    "ERR_INVALID_PRIOR_AUTH_STATE": 409,
    "ERR_INVALID_ABN_STATE": 409,
    "ERR_INVALID_FAB_ORDER_STATE": 409,
    "ERR_INVALID_RETURN_STATE": 409,
    "ERR_STALE_PAR_LEVEL_VERSION": 412,
    "ERR_STALE_ENCOUNTER_VERSION": 412,
    "ERR_CLINIC_ACCREDITATION_EXPIRED": 422,
    "ERR_SUPPLIER_STANDARDS_NOT_ATTESTED": 422,
    "ERR_SUPPLIER_QUALITY_HOLD": 422,
    "ERR_COMPLIANCE_HOLD_ACTIVE": 409,
    "ERR_IOAS_SUPERVISION_MISSING": 422,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_STARK_DISCLOSURE_MISSING": 422,
    "ERR_MEDICAL_NECESSITY_MISSING": 422,
    "ERR_FITTER_CREDENTIAL_EXPIRED": 422,
    "ERR_FITTER_PRIVILEGE_SCOPE": 403,
    "ERR_REFIT_SAME_FITTER": 409,
    "ERR_DELIVERY_SIGNATURE_MISSING": 422,
    "ERR_COVERAGE_VERIFICATION_MISSING": 422,
    "ERR_COVERAGE_VERIFICATION_EXPIRED": 422,
    "ERR_SAME_OR_SIMILAR_CONFLICT": 409,
    "ERR_PRIOR_AUTH_REQUIRED": 422,
    "ERR_PRIOR_AUTH_ALREADY_EXISTS": 409,
    "ERR_APPEAL_LIMIT_REACHED": 422,
    "ERR_APPROVED_UNITS_EXCEED_REQUEST": 422,
    "ERR_ABN_REQUIRED_FOR_EXCESS_UNITS": 422,
    "ERR_ABN_NOT_SIGNED": 422,
    "ERR_ABN_SUPERSEDED": 409,
    "ERR_DUPLICATE_NPI": 409,
    "ERR_DUPLICATE_PAR_LEVEL": 409,
    "ERR_FITTING_SLOT_CONFLICT": 409,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_RETURN_WINDOW_EXPIRED": 422,
    "ERR_RETURN_ALREADY_EXISTS": 409,
    "ERR_REFIT_REASON_NOT_ELIGIBLE": 422,
    "ERR_ADJUSTMENT_LIMIT_REACHED": 422,
    "ERR_CUSTOM_FAB_NOT_SUPPORTED": 422,
    "ERR_PRODUCT_CATEGORY_MISMATCH": 422,
    "ERR_CLINIC_DISPENSING_SUSPENDED": 409,
    "ERR_INSUFFICIENT_PAR_STOCK": 422,
    "ERR_PAR_MAX_EXCEEDED": 422,
}

ERROR_MESSAGES = {
    "ERR_MISSING_AUTH_HEADERS": "Both X-User-Id and X-User-Role headers are required.",
    "ERR_UNKNOWN_ROLE": "The supplied X-User-Role is not a recognised role.",
    "ERR_UNAUTHORIZED": "The supplied role is not authorized for this operation.",
    "ERR_ACTOR_NOT_FOUND": "The acting user does not resolve to a known actor.",
    "ERR_INVALID_REQUEST": "The request body or query is malformed.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or ERROR_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ------------------------------------------------------------------- envelope

def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_instant(datetime.now(timezone.utc)),
    }


def respond_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_list(items, pagination, status=200):
    meta = _meta()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def read_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < PAGE_OFFSET_MIN:
            fail("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def paginate(rows):
    limit, offset = read_pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


def bool_arg(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)


def enum_arg(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST", "%s is not a recognised value." % name)
    return raw


# ----------------------------------------------------------------------- auth

ROLES = (
    "PracticeAdmin",
    "ComplianceOfficer",
    "OrthoPhysician",
    "DmeFitter",
    "InsuranceCoordinator",
    "InventoryManager",
)

ALL_ROLES = list(ROLES)

# Entity-backed roles: their X-User-Id must resolve to a stored actor row.
ENTITY_BACKED_ROLES = ("OrthoPhysician", "DmeFitter")


def authorize(allowed_roles, actor_check=True):
    """Priorities 1-4 of the rejection ladder.

    Returns (user_id, role). ``actor_check=False`` implements the carve-out for
    the two endpoints on which an unknown DmeFitter is reported as
    ERR_FITTER_NOT_FOUND at priority 11 instead of ERR_ACTOR_NOT_FOUND.
    """
    from store import db  # local import: avoids a module cycle

    user_id = request.headers.get("X-User-Id")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_MISSING_AUTH_HEADERS")
    if role is None or str(role).strip() == "":
        fail("ERR_MISSING_AUTH_HEADERS")
    user_id = str(user_id)
    role = str(role)
    if role not in ROLES:
        fail("ERR_UNKNOWN_ROLE")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    if actor_check and role in ENTITY_BACKED_ROLES:
        if role == "OrthoPhysician":
            if user_id not in db["physicians"]:
                fail("ERR_ACTOR_NOT_FOUND")
        elif role == "DmeFitter":
            if user_id not in db["fitters"]:
                fail("ERR_ACTOR_NOT_FOUND")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


# ----------------------------------------------------------- body validation

_MISSING = object()


def body_json():
    """Parsed JSON body; ERR_INVALID_REQUEST when present but not an object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _present(body, name):
    return name in body and body[name] is not None


def need_str(body, name, min_len=1, max_len=None, pattern=None, upper=False):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % name)
    if len(value.strip()) < max(min_len, 1) and min_len >= 1:
        fail("ERR_INVALID_REQUEST", "%s must be non-blank." % name)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s is too short." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s is too long." % name)
    if pattern is not None and not re.match(pattern, value):
        fail("ERR_INVALID_REQUEST", "%s is malformed." % name)
    if upper and value != value.upper():
        fail("ERR_INVALID_REQUEST", "%s must be uppercase." % name)
    return value


def opt_str(body, name, min_len=1, max_len=None, default=None):
    if not _present(body, name):
        return default
    return need_str(body, name, min_len=min_len, max_len=max_len)


def need_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be at most %s." % (name, maximum))
    return value


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if not _present(body, name):
        return default
    return need_int(body, name, minimum=minimum, maximum=maximum)


def need_bool(body, name):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = body[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    return need_bool(body, name)


def need_enum(body, name, allowed):
    value = need_str(body, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s is not a recognised value." % name)
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return need_enum(body, name, allowed)


def need_date(body, name):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    parsed = parse_date(body[name])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO-8601 calendar date." % name)
    return parsed


def opt_date(body, name, default=None):
    if not _present(body, name):
        return default
    return need_date(body, name)


def need_instant(body, name):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    parsed = parse_instant(body[name])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO-8601 UTC instant." % name)
    return parsed


def need_rate(body, name, minimum, maximum, max_places=4):
    """Fractional rate: numeric, inside the closed range, bounded decimals."""
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % name)
    quantity = dec(value)
    if quantity < dec(minimum) or quantity > dec(maximum):
        fail("ERR_INVALID_REQUEST",
             "%s must be between %s and %s." % (name, minimum, maximum))
    exponent = quantity.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < -max_places:
        fail("ERR_INVALID_REQUEST",
             "%s carries more than %d decimal places." % (name, max_places))
    return quantity


def need_object(body, name):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = body[name]
    if not isinstance(value, dict) or len(value) == 0:
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty object." % name)
    return value


def need_str_list(body, name, allowed=None, max_items=None):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = body[name]
    if not isinstance(value, list) or len(value) == 0:
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty array." % name)
    if max_items is not None and len(value) > max_items:
        fail("ERR_INVALID_REQUEST", "%s carries too many entries." % name)
    seen = set()
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            fail("ERR_INVALID_REQUEST", "%s entries must be non-blank strings." % name)
        if allowed is not None and item not in allowed:
            fail("ERR_INVALID_REQUEST", "%s contains an unrecognised value." % name)
        if item in seen:
            fail("ERR_INVALID_REQUEST", "%s contains duplicate entries." % name)
        seen.add(item)
    return list(value)


def new_id():
    return str(uuid.uuid4())
