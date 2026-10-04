"""Auth, body-shape validation helpers, pagination (validation pipeline 1-7)."""
from flask import request

from core import STORE, err, parse_date, parse_datetime, parse_month, sort_by_created

ROLES = {
    "PlatformAdmin",
    "BrandManager",
    "TradeSecretOfficer",
    "ComplianceAuditor",
    "ChannelManager",
    "PricingAnalyst",
    "MarketingManager",
    "RegulatoryAffairs",
    "SupplyPlanner",
    "DistributorContact",
    "Consumer",
}

ALL_ROLES = sorted(ROLES)

CHANNELS = {"HARDWARE", "AUTOMOTIVE", "INDUSTRIAL", "MASS"}
DELIVERY_SYSTEMS = {"AEROSOL", "TRIGGER_SPRAY", "PUMP", "PRECISION_PEN", "BULK_CONTAINER"}
CAPABILITIES = {"BLENDING", "AEROSOL_FILL", "LIQUID_FILL", "PACKAGING"}
VOC_CLASSES = {"STANDARD", "LOW_VOC"}
VOC_REGIMES = {"STANDARD", "STRICT"}
GRANT_REASONS = {"PRODUCTION", "PILOT_SUPPLY", "SECOND_SOURCE"}
LOCKDOWN_REASONS = {"CONFIDENTIALITY_BREACH", "COUNTERFEIT_SURGE", "MANUAL"}
REVIEW_DECISIONS = {"APPROVE", "REJECT"}
USECASE_DECISIONS = {"VERIFY", "REJECT"}


# ---------------------------------------------------------------------------
# 1-2: user context + role authorization
# ---------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or role is None
        or not str(user_id).strip()
        or not str(role).strip()
        or role not in ROLES
    ):
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role must be present, non-empty and declare a known role")
    return user_id, role


def authorize(role, allowed):
    if role not in allowed:
        err("ERR_FORBIDDEN_FOR_ROLE", "Role %s is not authorized for this endpoint" % role)


# ---------------------------------------------------------------------------
# 3: path existence
# ---------------------------------------------------------------------------
def get_or_404(store_key, entity_id, label="resource"):
    ent = STORE[store_key].get(entity_id)
    if ent is None:
        err("ERR_NOT_FOUND", "%s %s not found" % (label, entity_id))
    return ent


# ---------------------------------------------------------------------------
# 4: request shape
# ---------------------------------------------------------------------------
def body():
    """JSON object body or {} for empty/missing bodies; malformed JSON -> 400."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def need(b, name):
    if name not in b or b[name] is None:
        err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    return b[name]


def as_str(v, name):
    if not isinstance(v, str) or not v.strip():
        err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % name)
    return v


def as_int(v, name, minimum=None, maximum=None):
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        err("ERR_INVALID_REQUEST", "Field %s must be <= %s" % (name, maximum))
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % name)
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def as_str_list(v, name, non_empty=True):
    if not isinstance(v, list) or (non_empty and len(v) == 0):
        err("ERR_INVALID_REQUEST", "Field %s must be a non-empty array" % name)
    for item in v:
        if not isinstance(item, str) or not item.strip():
            err("ERR_INVALID_REQUEST", "Field %s must contain only non-empty strings" % name)
    return v


def as_enum_list(v, name, allowed):
    items = as_str_list(v, name)
    for item in items:
        if item not in allowed:
            err("ERR_INVALID_REQUEST", "Field %s has an invalid value: %s" % (name, item))
    return items


def as_date(v, name):
    d = parse_date(v)
    if d is None:
        err("ERR_INVALID_REQUEST", "Field %s must be a YYYY-MM-DD date" % name)
    return d


def as_datetime(v, name):
    dt = parse_datetime(v)
    if dt is None:
        err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 UTC datetime" % name)
    return dt


def as_month(v, name):
    m = parse_month(v)
    if m is None:
        err("ERR_INVALID_REQUEST", "Field %s must be a YYYY-MM month" % name)
    return m


def as_discount_pct(v, name="discount_pct"):
    """0 < p <= 90.00 with at most two decimal places."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_INVALID_REQUEST", "Field %s must be a number" % name)
    from decimal import Decimal, InvalidOperation
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        err("ERR_INVALID_REQUEST", "Field %s must be a number" % name)
    if d.as_tuple().exponent < -2:
        err("ERR_INVALID_REQUEST", "Field %s must have at most two decimal places" % name)
    if d <= 0 or d > Decimal("90.00"):
        err("ERR_INVALID_REQUEST", "Field %s must be > 0 and <= 90.00" % name)
    return v


def opt_int(b, name, default, minimum=None):
    if name not in b or b[name] is None:
        return default
    return as_int(b[name], name, minimum=minimum)


def opt_bool(b, name, default=False):
    if name not in b or b[name] is None:
        return default
    return as_bool(b[name], name)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10 (min 1, max 100), offset default 0
# ---------------------------------------------------------------------------
def paginate(items):
    items = sort_by_created(items)
    args = request.args
    raw_limit = args.get("limit", "10")
    raw_offset = args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", "limit and offset must be integers")
    if limit < 1 or limit > 100:
        err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        err("ERR_INVALID_REQUEST", "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, pagination


def filter_eq(items, field, value):
    if value is None:
        return items
    return [e for e in items if e.get(field) == value]
