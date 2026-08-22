"""Core infrastructure for the Union Grievance & Arbitration Tracking API.

Holds the in-memory store, the logical clock, the response envelope helpers,
the error catalogue, authentication/RBAC and the request-body validators.

Storage is process-local Python dicts only.  Nothing is seeded at import time.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

UTC = timezone.utc

# The logical clock reads exactly this instant at server start-up (PRD 2.4).
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

# --------------------------------------------------------------------------
# Roles and parties (PRD 2.1)
# --------------------------------------------------------------------------
ROLE_UNION_STEWARD = "UnionSteward"
ROLE_GRIEVANT = "Grievant"
ROLE_ANALYST = "LaborRelationsAnalyst"
ROLE_DIRECTOR = "LaborRelationsDirector"
ROLE_NEGOTIATOR = "ChiefNegotiator"
ROLE_ADMIN = "ArbitrationAdministrator"

ALL_ROLES = (
    ROLE_UNION_STEWARD,
    ROLE_GRIEVANT,
    ROLE_ANALYST,
    ROLE_DIRECTOR,
    ROLE_NEGOTIATOR,
    ROLE_ADMIN,
)

# Every role that may call a plain read endpoint (everything except the two
# Grievant-scoped reads).
READ_ROLES = (
    ROLE_UNION_STEWARD,
    ROLE_ANALYST,
    ROLE_DIRECTOR,
    ROLE_NEGOTIATOR,
    ROLE_ADMIN,
)

PARTY_BY_ROLE = {
    ROLE_UNION_STEWARD: "UNION",
    ROLE_ANALYST: "EMPLOYER",
    ROLE_DIRECTOR: "EMPLOYER",
    ROLE_NEGOTIATOR: "EMPLOYER",
    # ArbitrationAdministrator and Grievant belong to neither party.
}


def party_of(role):
    return PARTY_BY_ROLE.get(role)


# --------------------------------------------------------------------------
# Error catalogue (PRD 5)
# --------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_CASE_PARTICIPANT": 403,
    "ERR_NOT_FILING_STEWARD": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_BARGAINING_UNIT_NOT_FOUND": 404,
    "ERR_CLAUSE_NOT_FOUND": 404,
    "ERR_EMPLOYEE_NOT_FOUND": 404,
    "ERR_GRIEVANCE_NOT_FOUND": 404,
    "ERR_STEP_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_PRECEDENT_NOT_FOUND": 404,
    "ERR_DEMAND_NOT_FOUND": 404,
    "ERR_ARBITRATOR_NOT_FOUND": 404,
    "ERR_AWARD_NOT_FOUND": 404,
    "ERR_COST_ENTRY_NOT_FOUND": 404,
    "ERR_WITNESS_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_STALE_GRIEVANCE_VERSION": 412,
    "ERR_INVALID_GRIEVANCE_STATE": 409,
    "ERR_INVALID_STEP_STATE": 409,
    "ERR_OFFER_NOT_DRAFT": 409,
    "ERR_OFFER_NOT_AUTHORIZED": 409,
    "ERR_DEMAND_STATE_INVALID": 409,
    "ERR_AWARD_STATE_INVALID": 409,
    "ERR_COST_ENTRY_ALREADY_VOIDED": 409,
    "ERR_AGREEMENT_EXPIRED": 409,
    "ERR_ARBITRATOR_INACTIVE": 409,
    "ERR_HEARING_NOT_CONCLUDED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ADVOCATE_WITNESS_CONFLICT": 422,
    "ERR_WITNESS_NOT_EMPLOYED": 422,
    "ERR_CLAUSE_NOT_ARBITRABLE": 422,
    "ERR_UNIT_MEMBERSHIP_MISMATCH": 422,
    "ERR_CLAUSE_UNIT_MISMATCH": 422,
    "ERR_PRECEDENT_CLAUSE_MISMATCH": 422,
    "ERR_PARTY_ROLE_MISMATCH": 403,
    "ERR_NOT_STRIKE_TURN": 409,
    "ERR_ARBITRATOR_NOT_ON_PANEL": 422,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_INVALID_PANEL_SIZE": 422,
    "ERR_STEP_LADDER_EXHAUSTED": 409,
    "ERR_PREP_INCOMPLETE": 409,
    "ERR_TOLLING_NOT_PERMITTED": 422,
    "ERR_PANEL_POOL_INSUFFICIENT": 409,
    "ERR_INVALID_DISCOVERY_DATE": 422,
    "ERR_GRIEVANCE_UNTIMELY": 422,
    "ERR_MEETING_DATE_IN_PAST": 422,
    "ERR_APPEAL_WINDOW_EXPIRED": 409,
    "ERR_ARBITRATION_DEMAND_UNTIMELY": 409,
    "ERR_INVALID_HEARING_WINDOW": 422,
    "ERR_ARBITRATOR_UNAVAILABLE": 409,
    "ERR_WITNESS_SLOT_CONFLICT": 409,
    "ERR_WITNESS_RELEASE_CAP_EXCEEDED": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_AUTHORITY_EXCEEDED": 403,
    "ERR_PRECEDENT_REVIEW_REQUIRED": 422,
    "ERR_OVERPAYMENT": 422,
    # Fallback for routes that do not exist at all.
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


# --------------------------------------------------------------------------
# Time helpers (PRD 2.4, 2.5)
# --------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 instant.  Raises ValueError when unparseable."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def add_days(instant, days):
    """Adding days means adding that many 86,400-second periods."""
    return instant + timedelta(days=days)


def floor_days(start, end):
    """Whole calendar days between two instants; the remainder is discarded."""
    return (end - start) // timedelta(days=1)


def ceil_half(days):
    """Halve a day-count, rounding up to a whole day."""
    return -(-int(days) // 2)


# --------------------------------------------------------------------------
# Numeric helpers (PRD 2.6)
# --------------------------------------------------------------------------
def to_dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))


def round_half_up(value):
    """Round to the nearest integer, one half going away from zero."""
    return int(to_dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps_rate(numerator, denominator):
    """round_half_up(numerator * 10000 / denominator); exactly 0 when denom 0."""
    if not denominator:
        return 0
    return round_half_up(to_dec(numerator) * 10000 / to_dec(denominator))


def num_out(value):
    """Serialize a `number`-typed field as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


# --------------------------------------------------------------------------
# In-memory store
# --------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self.bargaining_units = {}
        self.contract_clauses = {}
        self.employees = {}
        self.grievances = {}
        self.grievance_steps = {}
        self.settlement_offers = {}
        self.precedent_cases = {}
        self.arbitrators = {}
        self.arbitration_demands = {}
        self.panel_strikes = {}
        self.witness_assignments = {}
        self.awards = {}
        self.cost_entries = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


def base_record(with_version=True):
    rec = {
        "id": new_id(),
        "created_at": db.clock,
        "_seq": db.next_seq(),
    }
    if with_version:
        rec["updated_at"] = db.clock
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version by exactly 1 (PRD 2.8)."""
    if "version" in rec:
        rec["updated_at"] = db.clock
        rec["version"] = rec["version"] + 1
    return rec


# --------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": fmt_dt(datetime.now(UTC)),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# --------------------------------------------------------------------------
# Auth / RBAC (PRD 2.1, ladder positions 1 and 2)
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    role = role.strip()
    user_id = str(user_id).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role does not name a declared role.")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this operation." % role)
    return user_id, role


# --------------------------------------------------------------------------
# Body parsing and schema validation (ladder position 6)
# --------------------------------------------------------------------------
def get_body():
    raw = request.get_json(silent=True, force=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return raw


def bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def _present(body, name):
    return name in body and body[name] is not None


def req_string(body, name, max_len=None, min_len=1):
    if not _present(body, name):
        bad(name, "is required")
    value = body[name]
    if not isinstance(value, str):
        bad(name, "must be a string")
    if len(value) < min_len:
        bad(name, "must not be empty")
    if max_len is not None and len(value) > max_len:
        bad(name, "exceeds the maximum length of %d" % max_len)
    return value


def opt_string(body, name, default=None, max_len=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        bad(name, "must be a string")
    if max_len is not None and len(value) > max_len:
        bad(name, "exceeds the maximum length of %d" % max_len)
    return value


def req_enum(body, name, allowed):
    value = req_string(body, name)
    if value not in allowed:
        bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def _as_int(name, value):
    if isinstance(value, bool):
        bad(name, "must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    bad(name, "must be an integer")


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        bad(name, "is required")
    value = _as_int(name, body[name])
    if minimum is not None and value < minimum:
        bad(name, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        bad(name, "must be <= %d" % maximum)
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    value = _as_int(name, body[name])
    if minimum is not None and value < minimum:
        bad(name, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        bad(name, "must be <= %d" % maximum)
    return value


def _as_number(name, value):
    if isinstance(value, bool):
        bad(name, "must be a number")
    if isinstance(value, (int, float)):
        return to_dec(value)
    bad(name, "must be a number")


def opt_number(body, name, default=None, minimum=None):
    if not _present(body, name):
        return default
    value = _as_number(name, body[name])
    if minimum is not None and value < to_dec(minimum):
        bad(name, "must be >= %s" % minimum)
    return value


def req_bool(body, name):
    if not _present(body, name):
        bad(name, "is required")
    if not isinstance(body[name], bool):
        bad(name, "must be a boolean")
    return body[name]


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    if not isinstance(body[name], bool):
        bad(name, "must be a boolean")
    return body[name]


def req_dt(body, name):
    if not _present(body, name):
        bad(name, "is required")
    try:
        return parse_dt(body[name])
    except (ValueError, TypeError):
        bad(name, "must be an ISO 8601 datetime")


def opt_dt(body, name, default=None):
    if not _present(body, name):
        return default
    try:
        return parse_dt(body[name])
    except (ValueError, TypeError):
        bad(name, "must be an ISO 8601 datetime")


def req_id(body, name):
    if not _present(body, name):
        bad(name, "is required")
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        bad(name, "must be a non-empty string identifier")
    return value


def opt_id(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        bad(name, "must be a non-empty string identifier")
    return value


def req_enum_array(body, name, allowed):
    if not _present(body, name):
        bad(name, "is required")
    value = body[name]
    if not isinstance(value, list) or len(value) == 0:
        bad(name, "must be a non-empty array")
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad(name, "must contain only %s" % ", ".join(sorted(allowed)))
    return list(value)


# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def read_pagination():
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit", "must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            bad("limit", "must be between %d and %d" % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset", "must be an integer")
        if offset < 0:
            bad("offset", "must not be negative")
    return limit, offset


def paginated(rows, serializer):
    limit, offset = read_pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def qp(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


# --------------------------------------------------------------------------
# Ordering helpers
# --------------------------------------------------------------------------
def order_by(rows, *keys):
    """Stable multi-key sort.  Insertion order (`_seq`) is the implicit final
    tie-break; no ordering ever reads an `id` value."""
    result = sorted(rows, key=lambda r: r["_seq"])
    for key in reversed(keys):
        field, direction = key if isinstance(key, tuple) else (key, "asc")
        result = sorted(result, key=lambda r, f=field: r[f], reverse=(direction == "desc"))
    return result


__all__ = [name for name in dir() if not name.startswith("__")]
