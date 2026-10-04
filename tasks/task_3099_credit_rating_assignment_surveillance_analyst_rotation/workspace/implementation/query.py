"""Request body and query-string helpers."""

from flask import request

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def body():
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def get(data, key, default=None):
    value = data.get(key, default)
    return value


def require(data, key):
    """Return a required field; missing/blank is a malformed payload."""
    value = data.get(key)
    if value is None:
        return None
    return value


def text(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    return value


def to_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_pagination():
    """limit/offset with the scaffold's defaults, minimum and maximum."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = to_int(raw_limit)
    if limit is None:
        limit = DEFAULT_LIMIT
    limit = max(MIN_LIMIT, min(MAX_LIMIT, limit))
    offset = to_int(raw_offset)
    if offset is None or offset < 0:
        offset = DEFAULT_OFFSET
    return limit, offset


def paginate(rows):
    """Sort ascending by created_at, then slice.

    The sort is stable, so rows sharing a created_at keep their insertion
    order — deterministic within a server's lifetime.
    """
    ordered = sorted(rows, key=lambda r: r.get("created_at"))
    limit, offset = parse_pagination()
    window = ordered[offset:offset + limit]
    return window, limit, offset, len(ordered)


def bool_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return str(raw).strip().lower() in ("1", "true", "yes")


def apply_filters(rows, allowed):
    """Keep only query-parameter filters the endpoint declares."""
    result = rows
    for field in allowed:
        raw = request.args.get(field)
        if raw is None:
            continue
        value = raw
        if field in ("is_departed", "rotation_eligible"):
            parsed = bool_param(field)
            result = [r for r in result if bool(r.get(field)) is bool(parsed)]
            continue
        result = [r for r in result if str(r.get(field)) == str(value)]
    return result