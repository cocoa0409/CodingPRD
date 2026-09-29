"""Shared query-parameter handling for the list endpoints (PRD 2.3)."""
from flask import request

import store
from errors import fail

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    value = int(text)
    return value


def page_window():
    limit = _query_int("limit", LIMIT_DEFAULT)
    offset = _query_int("offset", OFFSET_DEFAULT)
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    if offset < OFFSET_DEFAULT:
        fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must not be negative.")
    return limit, offset


def enum_filter(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' has an unknown value." % name)
    return raw


def str_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def bool_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)


def listing(rows):
    """Order by created_at ascending, then apply the pagination window."""
    limit, offset = page_window()
    ordered = store.by_created(rows)
    total = len(ordered)
    window = ordered[offset : offset + limit]
    return window, limit, offset, total
