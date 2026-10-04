"""Request body well-formedness (priority 4) and pagination parsing."""
from __future__ import annotations

from flask import request

from clock import parse_date, parse_month
from errors import fail

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def body_json() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body: dict, name: str) -> str:
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        fail("ERR_VALIDATION", f"Field '{name}' is required and must be a non-empty string")
    return v


def opt_str(body: dict, name: str):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, str):
        fail("ERR_VALIDATION", f"Field '{name}' must be a string")
    return v


def req_int(body: dict, name: str, minimum=None) -> int:
    v = body.get(name)
    if not _is_int(v):
        fail("ERR_VALIDATION", f"Field '{name}' is required and must be an integer")
    if minimum is not None and v < minimum:
        fail("ERR_VALIDATION", f"Field '{name}' must be >= {minimum}")
    return v


def opt_int(body: dict, name: str, minimum=None):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not _is_int(v):
        fail("ERR_VALIDATION", f"Field '{name}' must be an integer")
    if minimum is not None and v < minimum:
        fail("ERR_VALIDATION", f"Field '{name}' must be >= {minimum}")
    return v


def req_month_str(body: dict, name: str) -> str:
    v = body.get(name)
    try:
        ym = parse_month(v)
    except (ValueError, AttributeError):
        fail("ERR_VALIDATION", f"Field '{name}' must be a YYYY-MM month string")
    from clock import month_str
    return month_str(ym)


def opt_month_str(body: dict, name: str):
    if name not in body or body[name] is None:
        return None
    return req_month_str(body, name)


def req_date_str(body: dict, name: str) -> str:
    v = body.get(name)
    try:
        d = parse_date(v)
    except (ValueError, AttributeError):
        fail("ERR_VALIDATION", f"Field '{name}' must be a YYYY-MM-DD date string")
    return d.isoformat()


def req_enum(body: dict, name: str, values) -> str:
    v = body.get(name)
    if not isinstance(v, str) or v not in values:
        fail("ERR_VALIDATION",
             f"Field '{name}' must be one of {', '.join(values)}")
    return v


def opt_bool(body: dict, name: str, default=False) -> bool:
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        fail("ERR_VALIDATION", f"Field '{name}' must be a boolean")
    return v


def req_list(body: dict, name: str) -> list:
    v = body.get(name)
    if not isinstance(v, list):
        fail("ERR_VALIDATION", f"Field '{name}' is required and must be an array")
    return v


def pagination_args():
    """limit: default 10, min 1, max 100 (clamped). offset: default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit, 10)
        except (ValueError, TypeError):
            fail("ERR_VALIDATION", "Query parameter 'limit' must be an integer")
        if limit < PAGE_LIMIT_MIN:
            fail("ERR_VALIDATION", "Query parameter 'limit' must be >= 1")
        if limit > PAGE_LIMIT_MAX:
            limit = PAGE_LIMIT_MAX
    if raw_offset is None or raw_offset == "":
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset, 10)
        except (ValueError, TypeError):
            fail("ERR_VALIDATION", "Query parameter 'offset' must be an integer")
        if offset < 0:
            fail("ERR_VALIDATION", "Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(sorted_items, limit: int, offset: int):
    total = len(sorted_items)
    page = sorted_items[offset:offset + limit] if offset < total else []
    return page, total
