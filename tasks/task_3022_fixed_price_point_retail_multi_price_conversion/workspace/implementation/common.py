"""Shared resource plumbing: identifiers, common fields, filtering, pagination
and the request-validation precedence chain (PRD §2.2 - §2.8)."""

from datetime import datetime

from flask import request

from db import db, iso
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_MISSING_USER_CONTEXT,
    ERR_INSUFFICIENT_ROLE,
)
from response import ok_array, ok_object

# §2.1 — the seven declared business roles plus the harness-only admin.
ROLES = (
    "MerchandiseBuyer",
    "StoreOperationsManager",
    "ImportCoordinator",
    "DistributionCenterOperator",
    "ResetCalendarPlanner",
    "MerchandiseAnalyst",
    "LegalCostEngineer",
    "PlatformAdmin",
)

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# Canonical key order per resource: the declared entity fields first, then an
# optional extension block, then the §2.5 common field set last.
FIELD_ORDERS = {
    "price_point": [
        "label", "shelf_price_cents", "target_landed_cost_ratio", "status",
        "issued_store_count",
    ],
    "season_window": [
        "season_code", "opens_on", "closes_on", "status", "overlapping_reset_count",
    ],
    "pack_program": [
        "vendor_id", "price_point_id", "pack_qty", "case_pack_qty",
        "formulation_code", "quoted_landed_cost_cents", "target_landed_cost_cents",
        "status",
    ],
    "item": [
        "sku", "description", "unit_retail_cents", "price_point_id",
        "commodity_class", "season_code", "sqft_per_unit", "shelf_package_capacity",
        "units_per_case", "base_landed_cost_cents", "fixed_store_handling_cents",
        "variable_store_cost_cents", "sourcing_vendor_id", "on_hand_units",
        "broken_case_allowance", "is_shelf_overflow", "landed_cost_cents",
        "break_even_units", "net_contribution_cents_per_unit", "break_even_regime",
        "status",
    ],
    "vendor": [
        "vendor_name", "country_of_origin", "import_flag", "exclusivity_program_count",
    ],
    "container": [
        "vendor_id", "container_number", "port_code", "dc_code",
        "total_freight_cents", "customs_cleared", "status",
    ],
    "store": [
        "store_number", "shelf_facing_capacity_sqft", "conversion_price_point_id",
        "sign_order_filed", "shelf_tag_filed", "register_file_locked", "status",
        "price_integrity_audit_count", "open_violation_count",
    ],
    "aisle_reset": [
        "store_id", "price_point_id", "season_window_id", "aisle_code",
        "starts_at", "ends_at", "allocated_shelf_sqft", "seasonal_changeover", "status",
    ],
    "conversion_project": [
        "store_id", "from_price_point_id", "to_price_point_id",
        "expected_store_version", "status", "coverage_delta_pct",
    ],
    # §2.5 exception — an immutable event log: id and created_at only.
    "audit": [
        "store_id", "price_point_id", "audited_at", "observed_item_count",
        "mismatched_item_count", "result", "mismatch_ratio", "status",
    ],
    "landed_cost": [
        "item_id", "container_id", "method", "applied_amount_cents",
        "effective_sequence",
    ],
    "allocation_line": [
        "container_id", "store_id", "item_id", "sequence", "requested_units",
        "allocated_units", "overflow_units", "released_units", "remaining_units",
        "status",
    ],
}

# Resource type -> (table attribute, not-found error id)
TABLES = {
    "price_point": ("price_points", "ERR_PRICE_POINT_NOT_FOUND"),
    "season_window": ("season_windows", "ERR_SEASON_WINDOW_NOT_FOUND"),
    "pack_program": ("pack_programs", "ERR_PACK_PROGRAM_NOT_FOUND"),
    "item": ("items", "ERR_ITEM_NOT_FOUND"),
    "vendor": ("vendors", "ERR_VENDOR_NOT_FOUND"),
    "container": ("containers", "ERR_CONTAINER_NOT_FOUND"),
    "store": ("stores", "ERR_STORE_NOT_FOUND"),
    "aisle_reset": ("aisle_resets", "ERR_AISLE_RESET_NOT_FOUND"),
    "conversion_project": ("conversion_projects", "ERR_CONVERSION_PROJECT_NOT_FOUND"),
    "audit": ("audits", "ERR_AUDIT_NOT_FOUND"),
    "landed_cost": ("landed_costs", "ERR_LANDED_COST_NOT_FOUND"),
    "allocation_line": ("allocation_lines", "ERR_ALLOCATION_LINE_NOT_FOUND"),
}

# §2.5 — the standard system-managed field set, initial values.
INITIAL_VERSION = 1


# ---------------------------------------------------------------------------
# Route registry
#
# Parsed once at import: declaration order is significant, because the
# existence checks must run left to right in the order the path declares them
# (PRD §2.8).
# ---------------------------------------------------------------------------

VIEWS = []


def route(path, methods, roles):
    """Register a handler. Path params use <name>; conversion is manual and
    ordered, so no Flask converter ever runs before our auth checks."""
    compiled = _compile(path)

    def decorator(handler):
        for method in methods:
            VIEWS.append((method.upper(), compiled, roles, handler))
        return handler

    return decorator


def _compile(path):
    segments = []
    for raw in path.strip("/").split("/"):
        if raw.startswith("<") and raw.endswith(">"):
            segments.append(("param", raw[1:-1]))
        else:
            segments.append(("literal", raw))
    return (path, segments)


def match_view(method, path):
    """Resolve a request.

    Returns ("found", handler, roles, params), or ("method_not_allowed", ...),
    or ("no_match", None, None, None). Path parameters are extracted here, so
    no Flask converter can fire ahead of the auth checks of PRD §2.1.
    """
    stripped = path.strip("/")
    candidates = stripped.split("/") if stripped else []
    path_matched = False
    for view_method, (_, segments), roles, handler in VIEWS:
        params = _match_segments(segments, candidates)
        if params is None:
            continue
        path_matched = True
        if view_method == method:
            return "found", handler, roles, params
    if path_matched:
        return "method_not_allowed", None, None, None
    return "no_match", None, None, None


def _match_segments(segments, candidates):
    if len(segments) != len(candidates):
        return None
    params = {}
    for (kind, value), candidate in zip(segments, candidates):
        if kind == "literal":
            if value != candidate:
                return None
        else:
            params[value] = candidate
    return params


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _jsonable(value):
    """Datetimes go out as ISO 8601 UTC with three fractional digits.

    Flask's default encoder would render them as HTTP dates, which is not the
    timestamp format this API declares (PRD §2.5).
    """
    if isinstance(value, datetime):
        return iso(value)
    return value


def serialize(kind, row):
    order = FIELD_ORDERS.get(kind)
    if order:
        out = {}
        for field in order:
            if field in row:
                out[field] = _jsonable(row[field])
        for key, value in row.items():
            if key not in out and not key.startswith("__") and key not in ("id", "created_at", "updated_at", "version"):
                out[key] = _jsonable(value)
    else:
        out = {k: _jsonable(v) for k, v in row.items() if not k.startswith("__")}
    if kind == "season_window":
        # §2.9 — the status a caller reads is derived from the logical clock.
        from derivations import season_window_status
        out["status"] = season_window_status(row)
    out["id"] = row["id"]
    if row.get("__has_created_at", True):
        out["created_at"] = row["created_at"]
    # §2.5 — PriceIntegrityAudit is an immutable event log: no updated_at, no version.
    if row.get("__has_common", True):
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def touch(row, by=1):
    """Refresh updated_at and bump version — a derived-field mutation counts."""
    row["updated_at"] = db.now_iso()
    row["version"] = row["version"] + by


def new_row(kind, fields, has_common=True):
    row = dict(fields)
    row["id"] = db.new_id()
    row["created_at"] = db.now_iso()
    row["__kind"] = kind
    row["__has_created_at"] = True
    if has_common:
        row["__has_common"] = True
        row["updated_at"] = row["created_at"]
        row["version"] = INITIAL_VERSION
    else:
        row["__has_common"] = False
    return row


def insert(kind, row):
    attr, _ = TABLES[kind]
    table = getattr(db, attr)
    table[row["id"]] = row
    return row


def get_row(kind, row_id):
    attr, not_found = TABLES[kind]
    if not isinstance(row_id, str) or row_id not in getattr(db, attr):
        raise ApiError(not_found)
    return getattr(db, attr)[row_id]


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def is_absent(data, field):
    """A field is absent only when omitted or explicitly null.

    An empty string is NOT absent: `season_code` is declared as '' for a
    year-round staple (PRD §3.1), so emptiness is a value here, not a gap.
    """
    if field not in data:
        return True
    return data[field] is None


def is_blank(data, field):
    """Optional-on-omission check: omitted, null or empty all mean 'not given'."""
    if field not in data:
        return True
    value = data[field]
    return value is None or value == ""


def query(name, default=None):
    value = request.args.get(name)
    if value is None or value == "":
        return default
    return value


def query_int(name, default=None):
    value = query(name)
    if value is None:
        return default
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def require(data, fields):
    """Presence check in declared order -> ERR_INVALID_REQUEST."""
    for field in fields:
        if is_absent(data, field):
            raise ApiError(ERR_INVALID_REQUEST, "Missing required field '%s'." % field)


def _as_int(value, field):
    if isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, "'%s' must be an integer." % field)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "'%s' must be an integer." % field)


def as_int(data, field, default=None):
    """Required integer: only omission or null mean 'not given'."""
    if is_absent(data, field):
        return default
    return _as_int(data[field], field)


def as_int_opt(data, field, default=None):
    """Optional integer: omitted/null/'' all mean 'not given'."""
    if is_blank(data, field):
        return default
    return _as_int(data[field], field)


def as_number(data, field, default=None):
    if is_absent(data, field):
        return default
    value = data[field]
    if isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, "'%s' must be a number." % field)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "'%s' must be a number." % field)
    return number


def as_bool(data, field, default=None):
    if is_absent(data, field):
        return default
    value = data[field]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low == "true":
            return True
        if low == "false":
            return False
    raise ApiError(ERR_INVALID_REQUEST, "'%s' must be a boolean." % field)


def as_enum(data, field, allowed, default=None):
    if is_absent(data, field):
        return default
    value = data[field]
    if value not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, "'%s' must be one of %s." % (field, "/".join(allowed)))
    return value


# ---------------------------------------------------------------------------
# Auth (PRD §2.1)
# ---------------------------------------------------------------------------

def check_auth(roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_MISSING_USER_CONTEXT)
    if role not in roles:
        raise ApiError(ERR_INSUFFICIENT_ROLE)
    return role


# ---------------------------------------------------------------------------
# Listing: filters, creation-order sort, pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def paginate(rows):
    total_count = len(rows)
    limit = query_int("limit", PAGE_LIMIT_DEFAULT)
    offset = query_int("offset", PAGE_OFFSET_DEFAULT)
    if limit is None:
        limit = PAGE_LIMIT_DEFAULT
    if offset is None:
        offset = PAGE_OFFSET_DEFAULT
    limit = max(PAGE_LIMIT_MIN, min(PAGE_LIMIT_MAX, limit))
    if offset < 0:
        offset = 0
    page = rows[offset:offset + limit]
    return ok_array(page, total_count, limit, offset)


def listed(kind, filter_fn=None):
    origin, _ = TABLES[kind]
    rows = db.creation_order(getattr(db, origin))
    if filter_fn is not None:
        rows = [r for r in rows if filter_fn(r)]
    return [serialize(kind, r) for r in rows]


def apply_eq(rows, row_field, value, cast=None):
    if value is None or value == "":
        return rows
    if cast is None:
        return [r for r in rows if r.get(row_field) == value]
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return rows
    return [r for r in rows if r.get(row_field) == value]


def get_ok(kind, row_id):
    row = get_row(kind, row_id)
    return ok_object(serialize(kind, row))