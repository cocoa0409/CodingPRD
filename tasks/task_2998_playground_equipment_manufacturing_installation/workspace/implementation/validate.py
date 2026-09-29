"""Request body shape checks, pagination and body foreign-key resolution.

PRD section 2.6 ("request bodies are checked for shape ... any failure of that
kind is reported as ERR_INVALID_REQUEST"), section 2.3 (pagination) and section
2.10 step 4 (body foreign-key existence, checked BEFORE request shape).
"""

import re

from flask import request

from errors import ApiError
from store import ENTITY_NOT_FOUND, parse_date, parse_instant, store


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def raw_body():
    """The parsed JSON body, or {} when absent.  Non-object bodies are rejected."""
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad_request("Request body must be a JSON object.")
    return parsed


# ----------------------------------------------------------- body FK existence

def resolve_fks(body, specs):
    """specs: list of (field_name, entity_kind, required_bool).

    Evaluated left to right in the declared order.  A field that is absent or
    not a string is left to the shape pass, which reports ERR_INVALID_REQUEST.
    """
    resolved = {}
    for field, kind, required in specs:
        value = body.get(field, None)
        if value is None:
            continue
        if not isinstance(value, str):
            continue
        row = store.get(kind, value)
        if row is None:
            raise ApiError(
                ENTITY_NOT_FOUND[kind],
                "No {} exists with id '{}'.".format(kind, value),
            )
        resolved[field] = row
    return resolved


# ------------------------------------------------------------ scalar validators

def _present(body, field, required):
    if field not in body or body[field] is None:
        if required:
            raise bad_request("Field '{}' is required.".format(field))
        return False
    return True


def integer(body, field, required=True, minimum=None, maximum=None, default=None):
    if not _present(body, field, required):
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '{}' must be an integer.".format(field))
    if minimum is not None and value < minimum:
        raise bad_request("Field '{}' must be >= {}.".format(field, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '{}' must be <= {}.".format(field, maximum))
    return value


def boolean(body, field, required=False, default=None):
    if not _present(body, field, required):
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise bad_request("Field '{}' must be a boolean.".format(field))
    return value


def string(body, field, required=True, min_len=None, max_len=None, pattern=None,
           default=None, pattern_hint=None):
    if not _present(body, field, required):
        return default
    value = body[field]
    if not isinstance(value, str):
        raise bad_request("Field '{}' must be a string.".format(field))
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field '{}' must be at least {} characters.".format(field, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '{}' must be at most {} characters.".format(field, max_len))
    if pattern is not None and not re.match(pattern, value):
        raise bad_request(
            "Field '{}' must match {}.".format(field, pattern_hint or pattern)
        )
    return value


def enum(body, field, members, required=True, default=None):
    if not _present(body, field, required):
        return default
    value = body[field]
    if not isinstance(value, str) or value not in members:
        raise bad_request(
            "Field '{}' must be one of {}.".format(field, ", ".join(sorted(members)))
        )
    return value


def date_field(body, field, required=True, default=None):
    if not _present(body, field, required):
        return default
    value = body[field]
    parsed = parse_date(value)
    if parsed is None:
        raise bad_request("Field '{}' must be a YYYY-MM-DD calendar date.".format(field))
    return parsed


def instant_field(body, field, required=True):
    if not _present(body, field, required):
        return None
    parsed = parse_instant(body[field])
    if parsed is None:
        raise bad_request("Field '{}' must be an ISO-8601 UTC instant.".format(field))
    return parsed


def enum_array(body, field, members, min_items, max_items, required=True, default=None):
    if not _present(body, field, required):
        return default
    value = body[field]
    if not isinstance(value, list):
        raise bad_request("Field '{}' must be an array.".format(field))
    if len(value) < min_items or len(value) > max_items:
        raise bad_request(
            "Field '{}' must hold between {} and {} entries.".format(field, min_items, max_items)
        )
    for item in value:
        if not isinstance(item, str) or item not in members:
            raise bad_request(
                "Field '{}' entries must be members of {}.".format(field, ", ".join(sorted(members)))
            )
    if len(set(value)) != len(value):
        raise bad_request("Field '{}' entries must be distinct.".format(field))
    return list(value)


def color_options(body, field):
    if not _present(body, field, True):
        return None
    value = body[field]
    if not isinstance(value, list):
        raise bad_request("Field '{}' must be an array.".format(field))
    if len(value) < 1 or len(value) > 8:
        raise bad_request("Field '{}' must hold between 1 and 8 entries.".format(field))
    for item in value:
        if not isinstance(item, str) or item == "" or item != item.upper():
            raise bad_request("Field '{}' entries must be non-empty uppercase strings.".format(field))
    if len(set(value)) != len(value):
        raise bad_request("Field '{}' entries must be distinct.".format(field))
    return list(value)


# ------------------------------------------------------------------- pagination

def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        if not re.match(r"^-?\d+$", raw_limit.strip()):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer between 1 and 100.")
        limit = int(raw_limit.strip())
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer between 1 and 100.")
    if raw_offset is not None:
        if not re.match(r"^-?\d+$", raw_offset.strip()):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer >= 0.")
        offset = int(raw_offset.strip())
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer >= 0.")
    return limit, offset


def apply_filters(rows, filters):
    """filters: dict of row-field -> query-parameter name."""
    out = rows
    for field, param in filters.items():
        value = request.args.get(param)
        if value is None:
            continue
        out = [r for r in out if _matches(r.get(field), value)]
    return out


def _matches(stored, wanted):
    if stored is None:
        return False
    if isinstance(stored, bool):
        return ("true" if stored else "false") == wanted.lower()
    return str(stored) == wanted


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
