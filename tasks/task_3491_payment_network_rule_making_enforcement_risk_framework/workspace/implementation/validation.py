"""Request-shape validation helpers (PRD section 2.8, priority 3) plus
pagination parsing (section 2.3) and a generic list-response builder."""
from flask import request

from clock import parse_iso_date
from envelope import ok_list
from errors import fail


def get_body():
    """Parse the JSON request body; a missing or malformed body behaves as
    an empty object so required-field checks report ERR_INVALID_REQUEST."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def _invalid(name, why="missing or invalid"):
    fail("ERR_INVALID_REQUEST", "Field '%s': %s" % (name, why))


def require_str(body, name):
    value = body.get(name)
    if not isinstance(value, str):
        _invalid(name)
    return value


def optional_str(body, name):
    """Optional string; absent or explicit null yields None."""
    if name not in body or body[name] is None:
        return None
    value = body[name]
    if not isinstance(value, str):
        _invalid(name, "must be a string or null")
    return value


def require_int(body, name):
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        _invalid(name, "must be an integer")
    return value


def require_bool(body, name):
    value = body.get(name)
    if not isinstance(value, bool):
        _invalid(name, "must be a boolean")
    return value


def optional_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, bool):
        _invalid(name, "must be a boolean")
    return value


def require_enum(body, name, allowed):
    value = require_str(body, name)
    if value not in allowed:
        _invalid(name, "must be one of %s" % ", ".join(allowed))
    return value


def require_date(body, name):
    text = require_str(body, name)
    parsed = parse_iso_date(text)
    if parsed is None:
        _invalid(name, "must be an ISO YYYY-MM-DD date")
    return parsed


def optional_nullable_date(body, name):
    """Optional date that may also be explicitly null (e.g. effective_until)."""
    if name not in body or body[name] is None:
        return None
    return require_date(body, name)


def parse_pagination():
    """limit defaults to 10, clamped to [1, 100]; offset defaults to 0,
    clamped to >= 0 (PRD section 2.3)."""
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(records, serializer, filters=None):
    """Sort by created_at ascending (stable via insertion sequence), filter by
    exact match, paginate, and serialize."""
    items = list(records)
    if filters:
        items = [
            r for r in items if all(r.get(key) == value for key, value in filters)
        ]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total_count = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total_count)
