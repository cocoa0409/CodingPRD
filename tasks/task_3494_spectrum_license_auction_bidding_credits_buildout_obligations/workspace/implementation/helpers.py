"""Shared request helpers: auth, role checks, body validation, pagination,
existence resolution, and per-request mutation dedup for version bumps."""
from flask import request, g

import store
from errors import ApiError, bad_request, not_found

ROLES = ("AuctionAdmin", "Bidder", "IncumbentOperator", "TransferReviewer")


# --- mutation dedup ----------------------------------------------------------
# version increments exactly once per resource per request, however many
# cascaded side effects touch it (PRD §2.5: "+1 on every mutation"; one API
# operation's cascade is one mutation per affected resource).
def touch(entity):
    seen = g.setdefault("_touched", set())
    key = id(entity)
    if key in seen:
        return
    seen.add(key)
    store.touch(entity)


# --- auth --------------------------------------------------------------------
def auth():
    """Tier 1: X-User-ID and X-User-Role present, role value declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing X-User-ID / X-User-Role headers or unknown role")
    return uid, role


def require_role(role, allowed):
    """Tier 2: caller role must be on the endpoint's authorization list."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "Role %s is not authorized for this endpoint" % role)


# --- body parsing / field validation -----------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data


def req_present(b, name):
    if name not in b or b[name] is None:
        raise bad_request("Missing required field: %s" % name)
    return b[name]


def as_str(value, name):
    if not isinstance(value, str) or value == "":
        raise bad_request("Field %s must be a non-empty string" % name)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise bad_request("Field %s must be a boolean" % name)
    return value


def as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field %s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise bad_request("Field %s is out of range" % name)
    if maximum is not None and value > maximum:
        raise bad_request("Field %s is out of range" % name)
    return value


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field %s must be a number" % name)
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("Field %s must be one of %s" % (name, ", ".join(allowed)))
    return value


def as_datetime(value, name):
    dt = store.parse_iso(value)
    if dt is None:
        raise bad_request("Field %s must be an ISO 8601 UTC datetime" % name)
    return dt


# --- existence (tier 3) -------------------------------------------------------
def get_or_404(table, entity_id, message=None):
    entity = store.DB[table].get(entity_id)
    if entity is None:
        raise not_found(message or ("No such %s: %s" % (table, entity_id)))
    return entity


# --- pagination (PRD §2.3) ----------------------------------------------------
def paginate(items):
    """Sort by created_at ASC (creation sequence breaks ties, never id) and
    apply limit/offset. Unparseable values -> 400; out-of-range values clamp
    to the documented bounds (limit 1..100 default 10, offset >= 0)."""
    items = sorted(items, key=store.created_key)
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise bad_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise bad_request("offset must be an integer")
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


# --- OCC ----------------------------------------------------------------------
def check_occ(entity, expected, field_name):
    """Optimistic concurrency (PRD §2.8): sits outside the ten tiers; a stale
    base is rejected before any mutation is applied."""
    if expected != entity["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "%s does not match the resource's current version"
                       % field_name)
