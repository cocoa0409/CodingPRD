"""Auth (ladder ranks 1-2), request-shape validation (ranks 3-5) and lookups (6-7)."""
from decimal import Decimal

from flask import request

import store
from errors import NOT_FOUND, ApiError

ROLES = (
    "ProgramAdmin",
    "NetworkManager",
    "ProjectCoordinator",
    "ServiceManager",
    "Installer",
    "Customer",
)

ALL_ROLES = list(ROLES)

# --- enum sets ---------------------------------------------------------------
TRADE_CODES = ["FLOORING", "GLAZING", "HVAC", "ROOFING", "MILLWORK"]
UNITS_OF_MEASURE = ["SQFT", "LINEAR_FT", "EACH"]
PERMIT_POLICIES = ["NEVER", "ALWAYS", "BY_JURISDICTION"]
CATEGORY_STATUSES = ["ACTIVE", "RETIRED"]
JURISDICTION_STATUSES = ["ACTIVE", "SUSPENDED"]
RESPONSIBLE_PARTIES = ["RETAILER", "INSTALLER", "CUSTOMER"]
INSTALLER_STATUSES = [
    "APPLIED", "DOCS_PENDING", "VERIFIED", "ACTIVE", "PROBATION", "SUSPENDED", "REMOVED",
]
CREDENTIAL_STATUSES = ["PENDING", "VERIFIED", "REJECTED", "EXPIRED"]
VERIFICATION_DECISIONS = ["VERIFY", "REJECT"]
BACKGROUND_RESULTS = ["PASS", "FAIL"]
FULFILLMENT_STATUSES = [
    "DRAFT", "MEASURE_PENDING", "MEASURED", "CHANGE_PENDING", "SCHEDULED",
    "IN_PROGRESS", "INSTALL_COMPLETE", "PUNCH_OPEN", "CLOSED", "CANCELLED",
]
FINANCIAL_STATUSES = [
    "QUOTED", "DEPOSIT_HELD", "BALANCE_DUE", "SETTLED",
    "PARTIALLY_REFUNDED", "REFUNDED", "FORFEITED",
]
PERMIT_STATUSES = [
    "NOT_REQUIRED", "PENDING_APPLICATION", "APPLIED", "ISSUED",
    "INSPECTION_SCHEDULED", "INSPECTION_PASSED", "INSPECTION_FAILED", "CLOSED",
]
MEASUREMENT_STATUSES = ["SCHEDULED", "COMPLETED", "VOIDED"]
SUBFLOOR_CONDITIONS = ["NONE", "MINOR", "MAJOR"]
CHANGE_ORDER_ORIGINS = ["MEASUREMENT_VARIANCE", "CUSTOMER_REQUEST", "SITE_CONDITION"]
CHANGE_ORDER_STATUSES = [
    "DRAFT", "PENDING_CUSTOMER", "REVISION_REQUESTED", "ACCEPTED", "DECLINED", "SUPERSEDED",
]
UNIT_KINDS = ["PRIMARY_UNITS", "TRIM_LINEAR_FT", "FIXTURE_EACH"]
CHANGE_ORDER_DECISIONS = ["ACCEPT", "DECLINE", "REQUEST_REVISION"]
DELIVERY_STATUSES = ["PLANNED", "IN_TRANSIT", "DELAYED", "DELIVERED", "RETURNED"]
ASSIGNMENT_STATUSES = ["HELD", "CONFIRMED", "IN_PROGRESS", "RELEASED", "COMPLETED", "NO_SHOW"]
PUNCH_SEVERITIES = ["MINOR", "MAJOR", "SAFETY"]
PUNCH_STATUSES = ["OPEN", "RESOLVED", "VERIFIED", "ESCALATED"]
QUALITY_RESULTS = ["NONE", "PASS", "PASS_WITH_PUNCH", "FAIL"]
INSPECTION_RESULTS = ["PASSED", "FAILED"]
CLAIM_TYPES = ["LABOR_DEFECT", "MATERIAL_DEFECT"]
CLAIM_STATUSES = ["SUBMITTED", "ESCALATED", "UPHELD", "DENIED"]
TRIAGE_DECISIONS = ["UPHOLD", "DENY", "ESCALATE"]
EVENT_TYPES = [
    "ON_TIME_COMPLETION", "LATE_COMPLETION", "NO_SHOW", "PUNCH_MINOR",
    "PUNCH_MAJOR", "PUNCH_SAFETY", "WARRANTY_UPHELD", "CSAT_SURVEY",
]
EVENT_SOURCES = ["MANUAL", "SYSTEM"]


# --- ranks 1 and 2 -----------------------------------------------------------
class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if not role or not str(role).strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")
    return Actor(user_id, role)


def body():
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:
        payload = None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_FIELD_TYPE", "The request body must be a JSON object.")
    return payload


# --- field specifications ----------------------------------------------------
class Spec(object):
    def __init__(self, name, kind, required=True, **kw):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = kw.get("enum")
        self.minimum = kw.get("minimum")
        self.maximum = kw.get("maximum")
        self.gt = kw.get("gt")
        self.minlen = kw.get("minlen", 1)
        self.maxlen = kw.get("maxlen")
        self.decimals = kw.get("decimals", 2)
        self.item_specs = kw.get("item_specs")
        self.max_items = kw.get("max_items")


def S(name, required=True, minlen=1, maxlen=None):
    return Spec(name, "string", required, minlen=minlen, maxlen=maxlen)


def I(name, required=True, minimum=None, maximum=None):
    return Spec(name, "int", required, minimum=minimum, maximum=maximum)


def M(name, required=True, minimum=0):
    return Spec(name, "money", required, minimum=minimum)


def N(name, required=True, gt=None, minimum=None, maximum=None, decimals=2):
    return Spec(name, "number", required, gt=gt, minimum=minimum, maximum=maximum,
                decimals=decimals)


def B(name, required=True):
    return Spec(name, "bool", required)


def E(name, values, required=True):
    return Spec(name, "enum", required, enum=values)


def T(name, required=True):
    return Spec(name, "instant", required)


def A(name, required=True, item_specs=None, max_items=None, enum=None):
    return Spec(name, "array", required, item_specs=item_specs, max_items=max_items, enum=enum)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _decimal_places(value):
    text = format(value, "f") if isinstance(value, Decimal) else repr(value)
    if "." not in text:
        return 0
    return len(text.split(".", 1)[1].rstrip("0"))


def _check_type(spec, value):
    kind = spec.kind
    if kind == "string":
        if not isinstance(value, str):
            raise ApiError("ERR_INVALID_FIELD_TYPE", "%s must be a string." % spec.name)
        return value
    if kind in ("int", "money"):
        if not _is_int(value):
            raise ApiError("ERR_INVALID_FIELD_TYPE", "%s must be a JSON integer." % spec.name)
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError("ERR_INVALID_FIELD_TYPE", "%s must be a JSON number." % spec.name)
        return Decimal(str(value))
    if kind == "bool":
        if not isinstance(value, bool):
            raise ApiError("ERR_INVALID_FIELD_TYPE", "%s must be a boolean." % spec.name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec.enum:
            raise ApiError("ERR_INVALID_FIELD_TYPE", "%s is not a declared enum value." % spec.name)
        return value
    if kind == "instant":
        parsed = store.parse_instant(value)
        if parsed is None:
            raise ApiError(
                "ERR_INVALID_FIELD_TYPE",
                "%s must be an ISO 8601 UTC instant with exactly three fractional digits." % spec.name,
            )
        return parsed
    if kind == "array":
        if not isinstance(value, list):
            raise ApiError("ERR_INVALID_FIELD_TYPE", "%s must be an array." % spec.name)
        if spec.enum is not None:
            for item in value:
                if not isinstance(item, str) or item not in spec.enum:
                    raise ApiError(
                        "ERR_INVALID_FIELD_TYPE",
                        "%s contains an undeclared enum value." % spec.name,
                    )
        return value
    raise ApiError("ERR_INVALID_FIELD_TYPE", "%s is not understood." % spec.name)


def _check_range(spec, value):
    kind = spec.kind
    if kind == "string":
        if len(value) < spec.minlen:
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "%s is too short." % spec.name)
        if spec.maxlen is not None and len(value) > spec.maxlen:
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "%s is too long." % spec.name)
        return
    if kind in ("int", "money"):
        if spec.minimum is not None and value < spec.minimum:
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "%s is below its minimum." % spec.name)
        if spec.maximum is not None and value > spec.maximum:
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "%s is above its maximum." % spec.name)
        return
    if kind == "number":
        if spec.gt is not None and value <= Decimal(str(spec.gt)):
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "%s must be greater than %s." % (spec.name, spec.gt))
        if spec.minimum is not None and value < Decimal(str(spec.minimum)):
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "%s is below its minimum." % spec.name)
        if spec.maximum is not None and value > Decimal(str(spec.maximum)):
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "%s is above its maximum." % spec.name)
        if spec.decimals is not None and _decimal_places(value) > spec.decimals:
            raise ApiError(
                "ERR_FIELD_OUT_OF_RANGE",
                "%s carries more than %d decimal places." % (spec.name, spec.decimals),
            )
        return
    if kind == "array":
        if spec.max_items is not None and len(value) > spec.max_items:
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "%s holds too many entries." % spec.name)
        return


def validate(data, specs):
    """Ranks 3, 4 and 5 in that order, each pass walking the declared field order."""
    # rank 3 - required presence, top level then nested
    for spec in specs:
        if spec.required and (spec.name not in data or data[spec.name] is None):
            raise ApiError("ERR_MISSING_REQUIRED_FIELD", "%s is required." % spec.name)
    for spec in specs:
        if spec.kind != "array" or not spec.item_specs:
            continue
        value = data.get(spec.name)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            for sub in spec.item_specs:
                if sub.required and (sub.name not in item or item[sub.name] is None):
                    raise ApiError(
                        "ERR_MISSING_REQUIRED_FIELD",
                        "%s[].%s is required." % (spec.name, sub.name),
                    )

    # rank 4 - declared types, top level then nested
    out = {}
    for spec in specs:
        if spec.name in data and data[spec.name] is not None:
            out[spec.name] = _check_type(spec, data[spec.name])
    for spec in specs:
        if spec.kind != "array" or not spec.item_specs:
            continue
        value = out.get(spec.name)
        if value is None:
            continue
        coerced_items = []
        for item in value:
            if not isinstance(item, dict):
                raise ApiError(
                    "ERR_INVALID_FIELD_TYPE",
                    "%s entries must be JSON objects." % spec.name,
                )
            coerced = {}
            for sub in spec.item_specs:
                if sub.name in item and item[sub.name] is not None:
                    coerced[sub.name] = _check_type(sub, item[sub.name])
            coerced_items.append(coerced)
        out[spec.name] = coerced_items

    # rank 5 - numeric ranges and string lengths, top level then nested
    for spec in specs:
        if spec.name in out:
            _check_range(spec, out[spec.name])
    for spec in specs:
        if spec.kind != "array" or not spec.item_specs:
            continue
        if spec.name not in out:
            continue
        for item in out[spec.name]:
            for sub in spec.item_specs:
                if sub.name in item:
                    _check_range(sub, item[sub.name])
    return out


def occ(data, name):
    """Rank 9: the OCC field must be a positive integer."""
    value = data.get(name)
    if not _is_int(value) or value < 1:
        raise ApiError("ERR_MISSING_REQUIRED_FIELD", "%s must be a positive integer." % name)
    return value


def pagination():
    """Rank 5 for reads: limit in 1..100, offset >= 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "offset must be an integer of at least 0.")
        if offset < 0:
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "offset must be at least 0.")
    return limit, offset


def arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def need(collection, row_id):
    """Ranks 6 and 7: resolve an id or answer that entity's not-found code."""
    row = store.get(collection, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection])
    return row


def filter_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if str(r.get(field)) == str(value)]


def filter_bool(rows, field, value):
    if value is None:
        return rows
    wanted = str(value).strip().lower() in ("true", "1", "yes")
    return [r for r in rows if bool(r.get(field)) == wanted]
