"""Validation pipeline helpers (PRD section 2.8, stages 1-4 + pagination)."""
import uuid

from flask import request

from constants import (
    ALL_ROLES, PAGE_DEFAULT_LIMIT, PAGE_DEFAULT_OFFSET, PAGE_MAX_LIMIT,
    PAGE_MIN_LIMIT,
)
from errors import ApiError
from store import STORE, parse_dt


def auth():
    """Stage 1: authentication. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def require_role(role, allowed):
    """Stage 2: endpoint-level authorization."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def body():
    """Parse the JSON request body; a missing body is an empty object."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(data, field):
    value = data.get(field)
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "field '%s' is required and must be a string" % field)
    return value


def opt_str(data, field, default=None):
    value = data.get(field)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "field '%s' must be a string" % field)
    return value


def req_int(data, field):
    value = data.get(field)
    if not _is_int(value):
        raise ApiError("ERR_INVALID_REQUEST", "field '%s' is required and must be an integer" % field)
    return value


def opt_int(data, field, default=None):
    value = data.get(field)
    if value is None:
        return default
    if not _is_int(value):
        raise ApiError("ERR_INVALID_REQUEST", "field '%s' must be an integer" % field)
    return value


def opt_bool(data, field, default=False):
    value = data.get(field)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "field '%s' must be a boolean" % field)
    return value


def req_num(data, field):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "field '%s' is required and must be a number" % field)
    return value


def req_enum(data, field, values):
    value = data.get(field)
    if not isinstance(value, str) or value not in values:
        raise ApiError("ERR_INVALID_REQUEST", "field '%s' must be one of %s" % (field, sorted(values)))
    return value


def req_dt(data, field):
    """Required ISO-8601 datetime; returns (raw_string, parsed_datetime)."""
    raw = req_str(data, field)
    try:
        return raw, parse_dt(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "field '%s' must be an ISO 8601 datetime" % field)


def get_or_404(table, entity_id):
    """Stage 4: existence of a path identifier."""
    entity = table.get(entity_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", "resource %s does not exist" % entity_id)
    return entity


def pagination_params():
    """limit/offset per PRD section 2.3 (defaults 10/0, limit in [1,100])."""
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if isinstance(int(raw_limit), bool) or limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between %d and %d" % (PAGE_MIN_LIMIT, PAGE_MAX_LIMIT))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def new_entity(fields=None):
    """Common resource properties (PRD section 2.5): id/created_at/updated_at/version."""
    ts = STORE.now_ts()
    entity = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": STORE.next_global(),
    }
    if fields:
        entity.update(fields)
    return entity


def touch(entity):
    """Every mutation refreshes updated_at and advances version by exactly 1."""
    entity["updated_at"] = STORE.now_ts()
    entity["version"] += 1


def apply_filters(items, filters):
    """Exact-match query filters; each filter is (query_arg, value). None skips."""
    out = items
    for field, value in filters:
        if value is not None:
            out = [item for item in out if item.get(field) == value]
    return out
