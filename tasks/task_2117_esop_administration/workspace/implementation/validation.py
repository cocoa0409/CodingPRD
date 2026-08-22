"""Request shape validation -- validation priority 3 (ERR_INVALID_REQUEST).

Every required input field present, every field of the declared type, every
enum field carrying a declared member, every integer field inside its declared
range, every date field parsing as YYYY-MM-DD, effective_to_date strictly
after effective_from_date, limit within 1..100 and offset not negative.
"""

import re
from datetime import date

from flask import request

from errors import fail

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MISSING = object()

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def body():
    """The JSON request body as a dict.  A missing body reads as empty."""
    if not request.data:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _present(payload, name):
    return name in payload and payload[name] is not None


def req_string(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    return value


def req_integer(payload, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' may not exceed %d." % (name, maximum))
    return value


def req_enum(payload, name, members, required=True, default=None):
    if not _present(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if value not in members:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be one of: %s." % (name, ", ".join(members)))
    return value


def parse_date(value):
    """Return a datetime.date for a strict YYYY-MM-DD string, else None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        year, month, day = (int(part) for part in value.split("-"))
        return date(year, month, day)
    except ValueError:
        return None


def req_date(payload, name, required=True, default=None):
    """Returns the plain YYYY-MM-DD string (calendar fields are stored as text)."""
    if not _present(payload, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = payload[name]
    if parse_date(value) is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD calendar date." % name)
    return value


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 and may not be negative."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_REQUEST", "limit must lie between 1 and 100.")

    if raw_offset is None or raw_offset == "":
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset may not be negative.")

    return limit, offset


def query_int(name):
    """An optional integer query filter; an unparsable value matches nothing."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return MISSING


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
