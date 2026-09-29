"""Core primitives: constants, logical clock, in-memory store, errors, envelope,
auth and request-validation helpers.

Every structural name here is taken from PRD.md / SCAFFOLD.yaml:
  auth headers        : X-User-ID, X-User-Role
  envelope            : meta{api_request_id, api_request_timestamp}, response_type, data
  error body          : data{error_id, message}
  pagination          : limit, offset, total_count, has_more (default 10, min 1, max 100)
  concurrency fields  : expected_pair_version, expected_record_version
  audit fields        : created_at, updated_at, version
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# --------------------------------------------------------------------------
# global_constants (SCAFFOLD.yaml)
# --------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
SCORE_PRECISION_DP = 2
NULL_CREDIT_FRACTION = Decimal("0.25")
PARTIAL_AGREEMENT_FRACTION = Decimal("0.5")
PREFIX_COMPARE_CHARS = 3
MIN_EVIDENCE_COUNT = 2
CONTAMINATION_REVIEW_ELEMENT_THRESHOLD = 25
REVERSAL_WINDOW_DAYS = 90
PROPAGATION_DEADLINE_HOURS_SYNCHRONOUS = 24
PROPAGATION_DEADLINE_HOURS_BATCH = 72
SEARCH_ATTEMPT_TTL_MINUTES = 15
METRIC_MIN_SAMPLE_SIZE = 30
BAND_CUTOFF_P1 = Decimal("85.00")
BAND_CUTOFF_P2 = Decimal("70.00")
BAND_MULTIPLIER_P1 = Decimal("1.50")
BAND_MULTIPLIER_P2 = Decimal("1.00")
BAND_MULTIPLIER_P3 = Decimal("0.50")
FRAUD_AUTO_OPEN_RAW_SCORE_MIN = Decimal("70.00")
FRAUD_CONFLICT_COMPONENT_POINTS = Decimal("30.00")
FRAUD_SCORE_COMPONENT_CAP = Decimal("30.00")
FRAUD_SITE_COMPONENT_PER_FLAGGED_RECORD = Decimal("2.00")
FRAUD_SITE_COMPONENT_CAP = Decimal("20.00")
FRAUD_INSURANCE_COMPONENT_POINTS = Decimal("25.00")
BPS_SCALE = 10000

SCORED_ATTRIBUTES = ["last_name", "first_name", "dob", "ssn_last4", "sex", "postal_code", "phone"]
OVERLAY_SNAPSHOT_KEYS = [
    "last_name", "first_name", "dob", "sex", "ssn_last4", "address_line",
    "postal_code", "phone", "biometric_template_hash", "insurance_member_id",
]

ROLES = ["SiteRegistrar", "IdentityAnalyst", "IdentityStewardApprover", "PrivacyOfficer", "MpiAdmin"]
ALL_ROLES = list(ROLES)

SEX_VALUES = ["M", "F", "X", "U"]

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, message):
    return ApiError(error_id, ERROR_STATUS[error_id], message)


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SITE_SCOPE_VIOLATION": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_RULE_SET_NOT_FOUND": 404,
    "ERR_SEARCH_ATTEMPT_NOT_FOUND": 404,
    "ERR_RECORD_NOT_FOUND": 404,
    "ERR_PAIR_NOT_FOUND": 404,
    "ERR_MERGE_NOT_FOUND": 404,
    "ERR_OVERLAY_NOT_FOUND": 404,
    "ERR_REMEDIATION_NOT_FOUND": 404,
    "ERR_TASK_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_DOWNSTREAM_SYSTEM_NOT_FOUND": 404,
    "ERR_WEIGHTS_SUM_INVALID": 422,
    "ERR_THRESHOLD_ORDER_INVALID": 422,
    "ERR_SEARCH_ATTEMPT_REQUIRED": 422,
    "ERR_STALE_PAIR_VERSION": 412,
    "ERR_STALE_RECORD_VERSION": 412,
    "ERR_RECORD_UNDER_FRAUD_HOLD": 409,
    "ERR_RECORD_REMEDIATION_PENDING": 409,
    "ERR_EXCHANGE_CONSENT_MISSING": 403,
    "ERR_SITE_SUSPENDED": 409,
    "ERR_RECORD_NOT_ACTIVE": 409,
    "ERR_PAIR_INVALID_STATE": 409,
    "ERR_MERGE_INVALID_STATE": 409,
    "ERR_OVERLAY_INVALID_STATE": 409,
    "ERR_REMEDIATION_INVALID_STATE": 409,
    "ERR_TASK_INVALID_STATE": 409,
    "ERR_INVESTIGATION_INVALID_STATE": 409,
    "ERR_DOWNSTREAM_SYSTEM_PAUSED": 409,
    "ERR_PROPAGATION_IN_FLIGHT": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INSUFFICIENT_REVIEW_EVIDENCE": 422,
    "ERR_MERGE_SELF_REFERENCE": 422,
    "ERR_PAIR_RECORD_MISMATCH": 422,
    "ERR_REASSIGN_TARGET_INVALID": 422,
    "ERR_DUPLICATE_MRN": 409,
    "ERR_PAIR_ALREADY_EXISTS": 409,
    "ERR_SEARCH_ATTEMPT_EXPIRED": 409,
    "ERR_REVERSAL_WINDOW_EXPIRED": 409,
    "ERR_PROPAGATION_WINDOW_EXPIRED": 409,
    "ERR_METRIC_WINDOW_OVERLAP": 409,
    "ERR_DISPATCH_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_CREATION_BLOCKED": 409,
    "ERR_REMEDIATION_COUNT_INVALID": 422,
}


def bad_request(detail):
    return err("ERR_INVALID_REQUEST", "Request payload is invalid: %s" % detail)


# --------------------------------------------------------------------------
# Decimal helpers
# --------------------------------------------------------------------------
def D(value):
    return Decimal(str(value))


def q2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def qint(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num(value):
    """Render a Decimal as a JSON number carrying its 2dp value."""
    if value is None:
        return None
    return float(q2(value))


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_datetime(value):
    """Parse an ISO 8601 UTC datetime. Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tzs = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tzs and tzs not in ("Z", "z"):
        sign = 1 if tzs[0] == "+" else -1
        body = tzs[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * offset
    return base


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc).date()
    except ValueError:
        return None


# --------------------------------------------------------------------------
# In-memory store -- starts EMPTY on every boot; nothing is ever seeded.
# --------------------------------------------------------------------------
class Store(object):
    COLLECTIONS = [
        "sites", "rule_sets", "records", "search_attempts", "pairs", "evidence",
        "merges", "overlays", "remediations", "systems", "tasks",
        "investigations", "external_matches", "metrics",
    ]

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.clock = parse_datetime(DEFAULT_CLOCK_UTC)

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def now():
    return store.clock


def new_id():
    return str(uuid.uuid4())


def base_entity(with_audit=True):
    ts = iso(now())
    row = {"id": new_id(), "created_at": ts, "_seq": store.next_seq()}
    if with_audit:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = iso(now())
    row["version"] = row.get("version", 1) + 1


def ordered(collection):
    return sorted(collection.values(), key=lambda r: r["_seq"])


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta(extra=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": iso(now())}
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(rows, page):
    meta = _meta({
        "limit": page["limit"],
        "offset": page["offset"],
        "total_count": page["total_count"],
        "has_more": page["has_more"],
    })
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_response(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.http_status


# --------------------------------------------------------------------------
# Auth (§1.4 priority 1-3 / PRD §2.1)
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognised authentication headers")
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role %s may not perform this operation" % role)
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def enforce_site_scope(site_in_scope):
    """§1.4 priority 3 -- SiteRegistrar may act only on its own RegistrationSite."""
    if g.user_role == "SiteRegistrar" and g.user_id != site_in_scope:
        raise err(
            "ERR_SITE_SCOPE_VIOLATION",
            "SiteRegistrar %s may only act on its own registration site" % g.user_id,
        )


# --------------------------------------------------------------------------
# Body / query validation (rank 4: ERR_INVALID_REQUEST)
# --------------------------------------------------------------------------
_MISSING = object()


def get_body(optional=True):
    if not request.data or not request.data.strip():
        if optional:
            return {}
        raise bad_request("a JSON object body is required")
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("body is not valid JSON")
    if parsed is None:
        if optional:
            return {}
        raise bad_request("a JSON object body is required")
    if not isinstance(parsed, dict):
        raise bad_request("body must be a JSON object")
    return parsed


def _raw(body, key):
    if key not in body:
        return _MISSING
    return body[key]


def as_number(value, key):
    """Accept int/float and numeric strings; reject bools and junk."""
    if isinstance(value, bool):
        raise bad_request("field '%s' must be a number" % key)
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip()
        try:
            return Decimal(text)
        except Exception:
            raise bad_request("field '%s' must be a number" % key)
    raise bad_request("field '%s' must be a number" % key)


def field_string(body, key, required=False, min_len=0, max_len=None, pattern=None,
                 default=None):
    # min_len defaults to 0: the PRD imposes a minimum length only on site_code,
    # mrn, system_code and ssn_last4, and those pass min_len explicitly.
    value = _raw(body, key)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("field '%s' is required" % key)
        return default
    if not isinstance(value, str):
        raise bad_request("field '%s' must be a string" % key)
    if len(value) < min_len:
        raise bad_request("field '%s' is too short" % key)
    if max_len is not None and len(value) > max_len:
        raise bad_request("field '%s' is too long" % key)
    if pattern is not None and not re.match(pattern, value):
        raise bad_request("field '%s' has an invalid format" % key)
    return value


def field_enum(body, key, values, required=False, default=None):
    value = _raw(body, key)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("field '%s' is required" % key)
        return default
    if not isinstance(value, str) or value not in values:
        raise bad_request("field '%s' must be one of %s" % (key, ", ".join(values)))
    return value


def field_decimal(body, key, required=False, minimum=None, maximum=None, default=None):
    value = _raw(body, key)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("field '%s' is required" % key)
        return default
    number = as_number(value, key)
    if minimum is not None and number < minimum:
        raise bad_request("field '%s' is below its minimum" % key)
    if maximum is not None and number > maximum:
        raise bad_request("field '%s' is above its maximum" % key)
    return number


def field_int(body, key, required=False, minimum=None, maximum=None, default=None):
    value = _raw(body, key)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("field '%s' is required" % key)
        return default
    number = as_number(value, key)
    if number != number.to_integral_value():
        raise bad_request("field '%s' must be an integer" % key)
    number = int(number)
    if minimum is not None and number < minimum:
        raise bad_request("field '%s' is below its minimum" % key)
    if maximum is not None and number > maximum:
        raise bad_request("field '%s' is above its maximum" % key)
    return number


def field_bool(body, key, required=False, default=None):
    value = _raw(body, key)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("field '%s' is required" % key)
        return default
    if not isinstance(value, bool):
        raise bad_request("field '%s' must be a boolean" % key)
    return value


def field_date(body, key, required=False, default=None):
    value = _raw(body, key)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("field '%s' is required" % key)
        return default
    if not isinstance(value, str) or parse_date(value) is None:
        raise bad_request("field '%s' must be a YYYY-MM-DD date" % key)
    return value.strip()


def field_datetime(body, key, required=False, default=None):
    value = _raw(body, key)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("field '%s' is required" % key)
        return default
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None:
        raise bad_request("field '%s' must be an ISO 8601 UTC datetime" % key)
    return parsed


def field_id(body, key, required=False, default=None):
    value = _raw(body, key)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("field '%s' is required" % key)
        return default
    if not isinstance(value, str) or not value:
        raise bad_request("field '%s' must be a string identifier" % key)
    return value


def field_map(body, key, allowed_keys=None, exact_keys=None, required=False):
    value = _raw(body, key)
    if value is _MISSING or value is None:
        if required:
            raise bad_request("field '%s' is required" % key)
        return None
    if not isinstance(value, dict):
        raise bad_request("field '%s' must be an object" % key)
    if exact_keys is not None and set(value.keys()) != set(exact_keys):
        raise bad_request("field '%s' must carry exactly the keys %s" % (key, ", ".join(exact_keys)))
    if allowed_keys is not None:
        extra = set(value.keys()) - set(allowed_keys)
        if extra:
            raise bad_request("field '%s' carries unsupported keys: %s" % (key, ", ".join(sorted(extra))))
    return value


# --------------------------------------------------------------------------
# Pagination and listing
# --------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except Exception:
            raise bad_request("query parameter 'limit' must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise bad_request("query parameter 'limit' must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except Exception:
            raise bad_request("query parameter 'offset' must be an integer")
        if offset < PAGINATION_DEFAULT_OFFSET:
            raise bad_request("query parameter 'offset' must be at least 0")
    return limit, offset


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return window, page


def query_filter(rows, key, getter=None):
    """Apply an exact-match query filter when the parameter is supplied."""
    if key not in request.args:
        return rows
    wanted = request.args.get(key)
    if getter is None:
        getter = lambda row: row.get(key)
    return [row for row in rows if getter(row) == wanted]
