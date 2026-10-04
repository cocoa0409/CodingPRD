"""Foundation: logical clock, in-memory store, errors, envelope, auth, helpers."""
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import g, jsonify, request

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Error catalogue (PRD section 5) -- error_id -> HTTP status
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_RETURN_NOT_FOUND": 404,
    "ERR_FORM_NOT_FOUND": 404,
    "ERR_PROMPT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_SNAPSHOT_NOT_FOUND": 404,
    "ERR_STATE_RETURN_NOT_FOUND": 404,
    "ERR_FORM_SPEC_NOT_FOUND": 404,
    "ERR_BANK_PARTNER_NOT_FOUND": 404,
    "ERR_ACCOUNT_SUSPENDED": 409,
    "ERR_ALLOCATION_EXCEEDS_BASE": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_RETURN_NOT_EDITABLE": 409,
    "ERR_UPGRADE_ACK_REQUIRED": 409,
    "ERR_FREE_FILE_INELIGIBLE": 422,
    "ERR_TIER_BELOW_REQUIRED": 422,
    "ERR_DOWNGRADE_WOULD_LEAVE_GAP": 409,
    "ERR_REFUND_TRANSFER_NOT_ACTIVE": 409,
    "ERR_REFUND_INSUFFICIENT_FOR_FEES": 402,
    "ERR_DUPLICATE_FORM_ON_RETURN": 409,
    "ERR_DUPLICATE_STATE_RETURN": 409,
    "ERR_RESIDENCY_OVERLAP": 409,
    "ERR_AMENDMENT_HOLD_ACTIVE": 409,
    "ERR_FILING_IN_FLIGHT": 409,
    "ERR_INVALID_CLAIM_AMOUNT": 422,
    "ERR_GUARANTEE_NOT_ENROLLED": 409,
    "ERR_RETURN_NOT_FILED": 409,
    "ERR_SNAPSHOT_YEAR_INVALID": 422,
    "ERR_SNAPSHOT_SUPERSEDED": 422,
    "ERR_NO_FORMS_ON_RETURN": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
    # fallback codes (not in the catalog; defensive only)
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
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return words.capitalize() + "."


# ---------------------------------------------------------------------------
# Roles and auth headers (PRD 2.1)
# ---------------------------------------------------------------------------
ROLES = ("Taxpayer", "ClaimsAdjuster", "PlatformOperator")

HDR_USER = "X-User-ID"
HDR_ROLE = "X-User-Role"

# Platform constants (PRD 2.5)
FREE_FILE_AGI_LIMIT_CENTS = 8400000          # $84,000.00 inclusive
REFUND_TRANSFER_FEE_CENTS = 4000             # $40.00
GUARANTEE_CAP_CENTS = 100000                 # $1,000.00
AMENDMENT_HOLD_HOURS = 24
REGISTERED_BANK_PARTNERS = ("BANK_A", "BANK_B")
ACTIVE_BANK_DISCLOSURE_VERSION = "RTD-2026-1"
STATE_FLAT_RATE_NUMERATOR = 5                # 5% flat state rate
STATE_FLAT_RATE_DENOMINATOR = 100

TIER_CODES = ("FREE", "DELUXE", "PREMIER", "SELF_EMPLOYED")
TIER_RANK = {"FREE": 0, "DELUXE": 1, "PREMIER": 2, "SELF_EMPLOYED": 3}
RANK_TIER = {v: k for k, v in TIER_RANK.items()}

FILING_STATUSES = (
    "SINGLE",
    "MARRIED_FILING_JOINTLY",
    "MARRIED_FILING_SEPARATELY",
    "HEAD_OF_HOUSEHOLD",
    "QUALIFYING_WIDOWER",
)

REJECTION_CODES = (
    "R0000_SSN_MISMATCH",
    "R0500_NAME_CONTROL",
    "R1000_DUPLICATE_FILED",
    "R2000_DEPENDENT_CLAIMED",
    "R3000_MATH_ERROR",
)

CORRECTION_HINTS = {
    "R0000_SSN_MISMATCH": "Verify the SSN exactly as printed on the Social Security card.",
    "R0500_NAME_CONTROL": "Name control mismatch: check last-name spelling against SSA records.",
    "R1000_DUPLICATE_FILED": "A return for this SSN was already accepted; amend instead of refiling.",
    "R2000_DEPENDENT_CLAIMED": "A dependent on this return was claimed elsewhere; review the dependent list.",
    "R3000_MATH_ERROR": "The authority recomputed a line; review the flagged worksheet totals.",
}

CARRYFORWARD_FORM_MAP = {
    "DEPRECIATION": "F4562",
    "CAPITAL_LOSS": "SCH_D",
    "BASIS": "F8949",
}
CARRYFORWARD_ITEM_TYPES = tuple(CARRYFORWARD_FORM_MAP.keys())


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(\.\d+)?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(text):
    """Parse an ISO-8601 datetime; returns None when unparseable."""
    if not isinstance(text, str):
        return None
    m = _DT_RE.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        micro = int(round(float(frac) * 1_000_000))
    tzpart = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if tzpart and tzpart not in ("Z", "z"):
        sign = 1 if tzpart[0] == "+" else -1
        body = tzpart[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * offset
    return base


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(text):
    """Parse a strict YYYY-MM-DD date; returns a datetime.date or None."""
    if not isinstance(text, str):
        return None
    m = _DATE_RE.match(text.strip())
    if not m:
        return None
    try:
        from datetime import date as _date
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# In-memory store -- starts EMPTY on every boot; nothing is ever seeded.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    COLLECTIONS = (
        "accounts",
        "tiers",
        "form_specs",
        "snapshots",
        "returns",
        "forms",
        "prompts",
        "state_returns",
        "filing_attempts",
        "refund_transfers",
        "claims",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def now():
    return db.clock


def new_row(kind, audited=True, **fields):
    row = {
        "_kind": kind,
        "_seq": db.next_seq(),
        "id": str(uuid.uuid4()),
        "created_at": db.clock,
    }
    if audited:
        row["updated_at"] = db.clock
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """Record a mutation: bump version and updated_at (when present)."""
    if "version" in row:
        row["version"] += 1
        row["updated_at"] = db.clock
    return row


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def jsonable(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def dump(row, extra=None):
    if row is None:
        return None
    out = {k: jsonable(v) for k, v in row.items() if not k.startswith("_")}
    if extra:
        out.update({k: jsonable(v) for k, v in extra.items()})
    return out


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def _meta():
    token = "".join(secrets.choice(_ALPHABET) for _ in range(16))
    return {
        "api_request_id": "req_" + token,
        "api_request_timestamp": fmt_dt(datetime.now(UTC)),
    }


def respond_object(data, status=200):
    return (
        jsonify({"meta": _meta(), "response_type": "object", "data": jsonable(data)}),
        status,
    )


def respond_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return (
        jsonify({"meta": meta, "response_type": "array", "data": jsonable(items)}),
        status,
    )


def respond_error(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


# ---------------------------------------------------------------------------
# Auth (validation priorities 1 and 2)
# ---------------------------------------------------------------------------
def endpoint(*roles):
    """Gate: headers well-formed, role valid and permitted for the endpoint."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get(HDR_USER)
            role = request.headers.get(HDR_ROLE)
            if not (user_id or "").strip() or not (role or "").strip():
                raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
            if role not in ROLES:
                raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
            if role not in allowed:
                raise ApiError("ERR_INSUFFICIENT_PERMISSIONS")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def check_ownership(account):
    """Taxpayer identity equals the owning account id (PRD 2.1)."""
    if g.role == "Taxpayer" and g.user_id != account["id"]:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS")


# ---------------------------------------------------------------------------
# Schema validation helpers
# ---------------------------------------------------------------------------
_MISSING = object()


def bad_request(detail):
    raise ApiError("ERR_INVALID_REQUEST", detail)


def body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad_request("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad_request("Request body must be a JSON object.")
    return parsed


def _fetch(src, key, required):
    if key not in src or src[key] is None:
        if required:
            bad_request("Field '%s' is required." % key)
        return _MISSING
    return src[key]


def f_str(src, key, required=True, allow_empty=False):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        bad_request("Field '%s' must not be empty." % key)
    return value


def f_enum(src, key, domain, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in domain:
        bad_request("Field '%s' must be one of %s." % (key, ", ".join(domain)))
    return value


def f_bool(src, key, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % key)
    return value


def f_int(src, key, required=True, default=None, minimum=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be at least %s." % (key, minimum))
    return value


def f_str_list(src, key, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, list):
        bad_request("Field '%s' must be an array." % key)
    for member in value:
        if not isinstance(member, str):
            bad_request("Field '%s' members must be strings." % key)
    return list(value)


def f_date(src, key, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    parsed = parse_date(value)
    if parsed is None:
        bad_request("Field '%s' must be an ISO date (YYYY-MM-DD)." % key)
    return parsed


def expected_version(src, ret):
    """OCC (priority 7): when supplied, expected_return_version must match."""
    value = _fetch(src, "expected_return_version", required=False)
    if value is _MISSING:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field 'expected_return_version' must be an integer.")
    if value != ret["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_return_version does not match the return's current version.",
        )


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def q_int(key, default=None, minimum=None, maximum=None):
    if key not in request.args:
        return default
    value = request.args.get(key)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        bad_request("Query parameter '%s' must be an integer." % key)
    if minimum is not None and parsed < minimum:
        bad_request("Query parameter '%s' must be at least %s." % (key, minimum))
    if maximum is not None and parsed > maximum:
        bad_request("Query parameter '%s' must be at most %s." % (key, maximum))
    return parsed


def pagination():
    limit = q_int("limit", 10, 1, 100)
    offset = q_int("offset", 0, 0, None)
    return limit, offset


def paginate(rows, dumper=None):
    limit, offset = pagination()
    rows = sort_created(list(rows))
    total = len(rows)
    page = rows[offset:offset + limit]
    dumper = dumper or dump
    return respond_list([dumper(r) for r in page], total, limit, offset)
