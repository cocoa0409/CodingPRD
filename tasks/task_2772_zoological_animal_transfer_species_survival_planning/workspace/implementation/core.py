"""Core plumbing: logical clock, response envelope, errors, auth, validation helpers."""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, jsonify, request

UTC = timezone.utc

# ---------------------------------------------------------------- logical clock
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
_CLOCK = {"now": DEFAULT_CLOCK}


def clock_now():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt


def reset_clock():
    _CLOCK["now"] = DEFAULT_CLOCK


def fmt_instant(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def now_instant():
    return fmt_instant(clock_now())


def now_date():
    return clock_now().date()


def fmt_date(d):
    return None if d is None else "%04d-%02d-%02d" % (d.year, d.month, d.day)


# ---------------------------------------------------------------------- decimals
def rh(value, places):
    """round-half-up (half away from zero) to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def num(value):
    """Serialise a stored Decimal for JSON."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


# ------------------------------------------------------------------ error catalog
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_SPECIES_PROGRAM_NOT_FOUND": 404,
    "ERR_INSTITUTION_NOT_FOUND": 404,
    "ERR_VETERINARIAN_NOT_FOUND": 404,
    "ERR_ANIMAL_NOT_FOUND": 404,
    "ERR_RECOMMENDATION_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_DOCUMENT_NOT_FOUND": 404,
    "ERR_TEST_NOT_FOUND": 404,
    "ERR_OCCUPANCY_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_PROTOCOL_NOT_FOUND": 404,
    "ERR_SUBMISSION_NOT_FOUND": 404,
    "ERR_ACTOR_SCOPE_VIOLATION": 403,
    "ERR_NOT_A_PARTY_TO_AGREEMENT": 403,
    "ERR_VET_INSTITUTION_MISMATCH": 403,
    "ERR_WRONG_ISSUING_AUTHORITY": 403,
    "ERR_NOT_COUNTERPARTY_TURN": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_STALE_ANIMAL_VERSION": 412,
    "ERR_STALE_AGREEMENT_VERSION": 412,
    "ERR_PROGRAM_PLAN_NOT_PUBLISHED": 409,
    "ERR_RECOMMENDATION_ALREADY_ENDORSED": 409,
    "ERR_RECOMMENDATION_NOT_ENDORSED": 409,
    "ERR_AGREEMENT_INVALID_STATE": 409,
    "ERR_DOCUMENT_ALREADY_DECIDED": 409,
    "ERR_BOOKING_INVALID_STATE": 409,
    "ERR_QUARANTINE_NOT_CLEARED": 409,
    "ERR_PROTOCOL_STAGE_INVALID": 409,
    "ERR_SUBMISSION_ALREADY_REVIEWED": 409,
    "ERR_ANIMAL_LOCATION_CONFLICT": 409,
    "ERR_ANIMAL_HAS_ACTIVE_AGREEMENT": 409,
    "ERR_INSTITUTION_NOT_ACCREDITED": 422,
    "ERR_INTERNATIONAL_TRANSFER_NOT_PERMITTED": 422,
    "ERR_DISPOSITION_POLICY_MISSING": 422,
    "ERR_VET_LICENSE_INVALID": 422,
    "ERR_VET_NOT_ACCREDITED_FOR_SCOPE": 422,
    "ERR_ANIMAL_NOT_SURPLUS_APPROVED": 422,
    "ERR_POSITIVE_TEST_RESULT": 422,
    "ERR_TEST_PANEL_INCOMPLETE": 422,
    "ERR_CRATE_TRAINING_INCOMPLETE": 422,
    "ERR_CRATE_TRAINING_STALE": 422,
    "ERR_HEALTH_CERTIFICATE_MISSING": 422,
    "ERR_PERMIT_NOT_ISSUED": 422,
    "ERR_QUARANTINE_NOT_SCHEDULED": 422,
    "ERR_HEALTH_CERTIFICATE_EXPIRED": 422,
    "ERR_RECOMMENDATION_EXPIRED": 422,
    "ERR_INBREEDING_LIMIT_EXCEEDED": 422,
    "ERR_INVALID_PAIRING": 422,
    "ERR_DUPLICATE_ANIMAL_LOCAL_ID": 422,
    "ERR_QUARANTINE_ROOM_CONFLICT": 422,
    "ERR_CARRIER_CAPACITY_EXCEEDED": 422,
    "ERR_DUPLICATE_STUDBOOK_SUBMISSION": 422,
    "ERR_NEGOTIATION_ROUND_LIMIT": 422,
    "ERR_QUARANTINE_MINIMUM_NOT_MET": 422,
    "ERR_HOLDING_CAPACITY_EXCEEDED": 422,
    "ERR_ANIMAL_NOT_HELD_BY_SENDER": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = ERROR_STATUS.get(error_id, 400)


DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or empty.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation.",
    "ERR_INVALID_REQUEST": "The request payload failed schema validation.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------- envelope
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _wall_now():
    return fmt_instant(datetime.now(UTC))


def base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _wall_now()}


def ok(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ------------------------------------------------------------------------- auth
ROLES = ("AccreditationAdmin", "ProgramCoordinator", "Registrar", "Veterinarian")
ALL_ROLES = ROLES


def auth(*allowed):
    allowed_set = set(allowed) if allowed else set(ROLES)

    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if uid is None or str(uid).strip() == "" or role is None or str(role).strip() == "":
                fail("ERR_UNAUTHENTICATED")
            if role not in ROLES or role not in allowed_set:
                fail("ERR_UNAUTHORIZED")
            g.user_id = uid
            g.role = role
            return fn(*a, **kw)

        return wrapper

    return deco


def actor():
    return g.user_id


# ------------------------------------------------------------ payload validation
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:[Zz]|[+-]\d{2}:?\d{2})$"
)
JURISDICTION_RE = re.compile(r"^[A-Z]{2}-[A-Z0-9]{2,3}$")


def body():
    data = request.get_json(silent=True, force=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def parse_date(raw, field):
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 calendar date (YYYY-MM-DD)." % field)
    try:
        return date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]))
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s is not a valid calendar date." % field)


def parse_instant(raw, field):
    if not isinstance(raw, str):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant." % field)
    m = _INSTANT_RE.match(raw)
    if not m:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant." % field)
    txt = raw.replace("z", "Z")
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s is not a valid instant." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _present(b, name):
    return name in b and b[name] is not None


def req_present(b, name):
    if not _present(b, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)


def get_str(b, name, required=False, default=None, pattern=None, allow_empty=False):
    if not _present(b, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    v = b[name]
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % name)
    if not allow_empty and v.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string." % name)
    if pattern is not None and not pattern.match(v):
        fail("ERR_INVALID_REQUEST", "%s has an invalid format." % name)
    return v


def get_enum(b, name, allowed, required=False, default=None):
    if not _present(b, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    v = b[name]
    if not isinstance(v, str) or v not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return v


def get_int(b, name, required=False, default=None, minimum=None, maximum=None):
    if not _present(b, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s." % (name, minimum))
    if maximum is not None and v > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s." % (name, maximum))
    return v


def get_num(b, name, required=False, default=None, minimum=None, maximum=None):
    if not _present(b, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % name)
    d = dec(v)
    if minimum is not None and d < dec(minimum):
        fail("ERR_INVALID_REQUEST", "%s must be >= %s." % (name, minimum))
    if maximum is not None and d > dec(maximum):
        fail("ERR_INVALID_REQUEST", "%s must be <= %s." % (name, maximum))
    return d


def get_bool(b, name, required=False, default=None):
    if not _present(b, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    v = b[name]
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)
    return v


def get_date(b, name, required=False, default=None):
    """Returns (date_obj, raw_string) or (None, None)."""
    if not _present(b, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return (default, None if default is None else fmt_date(default))
    raw = b[name]
    return (parse_date(raw, name), raw)


def get_instant(b, name, required=False):
    """Returns (datetime, raw_string) or (None, None)."""
    if not _present(b, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return (None, None)
    raw = b[name]
    return (parse_instant(raw, name), raw)


def get_num_list(b, name, required=False):
    if not _present(b, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return None
    v = b[name]
    if not isinstance(v, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array of numbers." % name)
    out = []
    for item in v:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            fail("ERR_INVALID_REQUEST", "%s must contain only numbers." % name)
        out.append(item)
    return out


# ----------------------------------------------------------------- query helpers
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100 inclusive.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def q_str(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v


def q_enum(name, allowed):
    v = q_str(name)
    if v is None:
        return None
    if v not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return v


def q_date(name):
    v = q_str(name)
    if v is None:
        return None
    return parse_date(v, name)


def q_bool(name):
    v = q_str(name)
    if v is None:
        return None
    if v.lower() in ("true", "1"):
        return True
    if v.lower() in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


def sorted_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
