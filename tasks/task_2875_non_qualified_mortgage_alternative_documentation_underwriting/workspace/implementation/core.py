"""Cross-cutting primitives: errors, response envelope, auth, request shape checks."""
import json
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext, localcontext

from flask import request, Response

getcontext().prec = 34

# ---------------------------------------------------------------------------
# Error catalogue (PRD 1.6)
# ---------------------------------------------------------------------------
ERROR_CATALOGUE = {
    "ERR_MISSING_ROLE_HEADER": (401, "X-User-Role header is absent or empty"),
    "ERR_UNKNOWN_ROLE": (401, "X-User-Role is not a recognised role"),
    "ERR_MISSING_USER_HEADER": (401, "X-User-ID header is absent or empty"),
    "ERR_UNAUTHORIZED": (403, "role is not permitted to call this endpoint"),
    "ERR_PROGRAM_NOT_FOUND": (404, "documentation program not found"),
    "ERR_OVERLAY_NOT_FOUND": (404, "investor overlay not found"),
    "ERR_BORROWER_NOT_FOUND": (404, "borrower not found"),
    "ERR_LOAN_FILE_NOT_FOUND": (404, "loan file not found"),
    "ERR_WORKSHEET_NOT_FOUND": (404, "income worksheet not found"),
    "ERR_STATEMENT_MONTH_NOT_FOUND": (404, "statement month not found"),
    "ERR_VALUATION_ORDER_NOT_FOUND": (404, "valuation order not found"),
    "ERR_REVIEW_NOT_FOUND": (404, "appraisal review not found"),
    "ERR_FEE_ITEM_NOT_FOUND": (404, "points and fees item not found"),
    "ERR_EXCEPTION_NOT_FOUND": (404, "exception request not found"),
    "ERR_AUDIT_NOT_FOUND": (404, "post-close audit not found"),
    "ERR_FINDING_NOT_FOUND": (404, "audit finding not found"),
    "ERR_POOL_NOT_FOUND": (404, "securitization pool not found"),
    "ERR_INVALID_REQUEST": (400, "request shape is invalid"),
    "ERR_VALUE_OUT_OF_RANGE": (422, "a supplied value is outside its permitted domain"),
    "ERR_STALE_LOAN_FILE_VERSION": (412, "expected_loan_file_version does not match the loan file version"),
    "ERR_STALE_POOL_VERSION": (412, "expected_pool_version does not match the pool version"),
    "ERR_LOAN_FILE_STATE_INVALID": (409, "loan file is not in a state that permits this trigger"),
    "ERR_WORKSHEET_STATE_INVALID": (409, "income worksheet is not in a state that permits this trigger"),
    "ERR_STATEMENT_MONTH_STATE_INVALID": (409, "statement month is not in a state that permits this trigger"),
    "ERR_VALUATION_ORDER_STATE_INVALID": (409, "valuation order is not in a state that permits this trigger"),
    "ERR_REVIEW_STATE_INVALID": (409, "appraisal review is not in a state that permits this trigger"),
    "ERR_EXCEPTION_STATE_INVALID": (409, "exception request is not in a state that permits this trigger"),
    "ERR_FINDING_STATE_INVALID": (409, "audit finding write is not state-legal"),
    "ERR_POOL_STATE_INVALID": (409, "securitization pool is not in a state that permits this trigger"),
    "ERR_DOC_TYPE_PROGRAM_MISMATCH": (422, "doc_type is not offered by the loan's documentation program"),
    "ERR_HIGH_COST_LOAN_PROHIBITED": (422, "points and fees test failed; high-cost loan is prohibited"),
    "ERR_ATR_DOCUMENTATION_INCOMPLETE": (422, "ability-to-repay documentation is incomplete"),
    "ERR_SEASONING_NOT_SATISFIED": (422, "credit event seasoning is not satisfied"),
    "ERR_SECOND_VALUATION_REQUIRED": (422, "an accepted second valuation is required"),
    "ERR_APPRAISAL_ESCALATION_UNRESOLVED": (422, "appraisal escalation is unresolved"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "segregation of duties prevents this action"),
    "ERR_VALUATION_EXPIRED": (422, "the supporting valuation is outside its validity window"),
    "ERR_VALUATION_REORDER_TOO_SOON": (422, "a valuation of this type was ordered too recently"),
    "ERR_STATEMENT_PERIOD_OVERLAP": (409, "statement month period overlaps an existing month"),
    "ERR_STATEMENT_PERIOD_OUT_OF_WINDOW": (422, "statement month period is outside the permitted window"),
    "ERR_DUPLICATE_CODE": (409, "code is already in use"),
    "ERR_INSUFFICIENT_STATEMENT_MONTHS": (422, "included statement month count does not match the program"),
    "ERR_NO_INCLUDED_STATEMENT_MONTHS": (422, "at least one included statement month is required"),
    "ERR_OVERLAY_NOT_BREACHED": (422, "the overlay is not currently breached on this loan file"),
    "ERR_LOAN_NOT_SECURITIZATION_ELIGIBLE": (422, "loan file is not securitization eligible"),
    "ERR_LOAN_ALREADY_POOLED": (409, "loan file already belongs to a pool"),
    "ERR_LOAN_NOT_IN_POOL": (422, "loan file is not a member of this pool"),
    "ERR_EXCEPTION_AUTHORITY_INSUFFICIENT": (403, "insufficient authority for this exception tier"),
    "ERR_DTI_ABOVE_PROGRAM_MAX": (422, "dti_pct is above the program maximum"),
    "ERR_RESERVES_INSUFFICIENT": (422, "documented reserves are below the program minimum"),
    "ERR_RESIDUAL_INCOME_INSUFFICIENT": (422, "residual income is below the program minimum"),
    "ERR_FICO_BELOW_PROGRAM_MIN": (422, "fico score is below the program minimum"),
    "ERR_LTV_ABOVE_PROGRAM_MAX": (422, "ltv_pct is above the program maximum"),
    "ERR_DSCR_BELOW_PROGRAM_MIN": (422, "dscr_ratio is below the program minimum"),
    "ERR_POOL_BALANCE_CAP_EXCEEDED": (422, "pool target balance would be exceeded"),
    "ERR_NOT_FOUND": (404, "resource not found"),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        status, default_message = ERROR_CATALOGUE.get(error_id, (400, error_id))
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message


# ---------------------------------------------------------------------------
# Timestamps / decimals
# ---------------------------------------------------------------------------
def utc_now():
    return datetime.now(timezone.utc)


def iso_instant(dt):
    """ISO-8601 UTC instant with exactly three fractional-second digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000)


_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?(([Zz])|([+-]\d{2}:?\d{2}))?$")


def parse_instant(value):
    """Parse an ISO-8601 datetime (or bare date) into an aware UTC datetime.

    Returns None when the value is not a parseable instant.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or not _ISO_RE.match(text):
        return None
    body = text
    if body[-1] in ("Z", "z"):
        body = body[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(body)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(Decimal(value), 0))


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def months_between(earlier, later):
    """Whole calendar months from `earlier` to `later`; time of day ignored."""
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return months


def shift_months(dt, delta):
    """Shift a datetime by `delta` calendar months, clamping the day of month."""
    total = (dt.year * 12 + (dt.month - 1)) + delta
    year, month = divmod(total, 12)
    month += 1
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


# ---------------------------------------------------------------------------
# JSON serialization / response envelope
# ---------------------------------------------------------------------------
def _json_default(obj):
    if isinstance(obj, Decimal):
        integral = obj.to_integral_value()
        if obj == integral:
            return int(integral)
        return float(obj)
    if isinstance(obj, datetime):
        return iso_instant(obj)
    raise TypeError("not JSON serializable: %r" % (obj,))


def public_view(row):
    """Strip internal bookkeeping keys (leading underscore) from an entity row."""
    if isinstance(row, list):
        return [public_view(item) for item in row]
    if not isinstance(row, dict):
        return row
    return {k: v for k, v in row.items() if not k.startswith("_")}


def _request_meta():
    alphabet = string.ascii_uppercase + string.digits
    return {
        "api_request_id": "req_" + "".join(random.choice(alphabet) for _ in range(20)),
        "api_request_timestamp": iso_instant(utc_now()),
    }


def _emit(payload, status):
    body = json.dumps(payload, default=_json_default)
    return Response(body, status=status, mimetype="application/json")


def respond_object(row, status=200):
    data = public_view(row) if row is not None else {}
    return _emit({"meta": _request_meta(), "response_type": "object", "data": data}, status)


def respond_created(row):
    return respond_object(row, 201)


def respond_empty():
    return _emit({"meta": _request_meta(), "response_type": "object", "data": {}}, 200)


def respond_collection(rows, limit, offset, total_count):
    meta = _request_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    payload = {"meta": meta, "response_type": "array", "data": public_view(rows)}
    return _emit(payload, 200)


def respond_error(error):
    payload = {
        "meta": _request_meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return _emit(payload, error.http_status)


# ---------------------------------------------------------------------------
# Authentication / authorization (validations priority 1..4)
# ---------------------------------------------------------------------------
ROLES = (
    "ProgramAdmin",
    "LoanOfficer",
    "Underwriter",
    "CreditCommittee",
    "ChiefCreditOfficer",
    "AppraisalReviewer",
    "PostCloseAuditor",
    "SecuritizationAnalyst",
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "":
        raise ApiError("ERR_MISSING_ROLE_HEADER")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_MISSING_USER_HEADER")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return Actor(user_id, role)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def read_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative")
    return limit, offset


def paginate(rows):
    limit, offset = read_pagination()
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total


def sort_key(row):
    return (row.get("created_at", ""), row.get("_seq", 0))


def ordered(rows):
    return sorted(rows, key=sort_key)


# ---------------------------------------------------------------------------
# Request body shape validation (validations priority 6)
# ---------------------------------------------------------------------------
class Field(object):
    __slots__ = ("name", "kind", "required", "enum", "scale")

    def __init__(self, name, kind, required=False, enum=None, scale=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.scale = scale


def raw_body():
    """Best-effort body read used before shape validation runs."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def _coerce(field, value):
    kind = field.kind
    if kind == "str":
        if not isinstance(value, str):
            invalid("%s must be a string" % field.name)
        return value
    if kind == "enum":
        if not isinstance(value, str):
            invalid("%s must be a string" % field.name)
        if value not in field.enum:
            invalid("%s is not a permitted value" % field.name)
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            invalid("%s must be an integer" % field.name)
        return value
    if kind == "num":
        # Decimal-scaled fields accept a JSON number or an exact decimal string.
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            invalid("%s must be a number" % field.name)
        try:
            number = dec(value)
        except (ArithmeticError, ValueError):
            invalid("%s must be a number" % field.name)
        if not number.is_finite():
            invalid("%s must be a number" % field.name)
        if field.scale is not None:
            number = round_half_up(number, field.scale)
        return number
    if kind == "bool":
        if not isinstance(value, bool):
            invalid("%s must be a boolean" % field.name)
        return value
    if kind == "datetime":
        parsed = parse_instant(value)
        if parsed is None:
            invalid("%s must be an ISO-8601 timestamp" % field.name)
        return parsed
    if kind == "object":
        if not isinstance(value, dict):
            invalid("%s must be an object" % field.name)
        return value
    if kind == "str_array":
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            invalid("%s must be an array of strings" % field.name)
        return list(value)
    invalid("unsupported field %s" % field.name)


def validate_body(fields):
    """Validate the JSON body against `fields`; returns a dict of present values."""
    body = request.get_json(silent=True)
    if body is None:
        if request.get_data(cache=True) not in (b"", None):
            invalid("request body is not valid JSON")
        body = {}
    if not isinstance(body, dict):
        invalid("request body must be a JSON object")
    known = set(f.name for f in fields)
    for key in body:
        if key not in known:
            invalid("unknown field %s" % key)
    values = {}
    for field in fields:
        if field.name not in body or body[field.name] is None:
            if field.required:
                invalid("%s is required" % field.name)
            continue
        values[field.name] = _coerce(field, body[field.name])
    return values


def require_range(condition, message):
    if not condition:
        raise ApiError("ERR_VALUE_OUT_OF_RANGE", message)


def new_id():
    return str(uuid.uuid4())
