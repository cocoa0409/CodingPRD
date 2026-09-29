"""Request-body shape validation (ladder rule 6 -> ERR_INVALID_REQUEST, 400).

PRD 2.10 rule 6: "Request-body shape: required fields present, enum members legal,
integers inside their declared bounds, arrays free of duplicates and drawn from their
declared code sets, instants parseable as ISO 8601 UTC, and limit and offset inside
the pagination bounds."
"""

from flask import request

import store
from errors import fail

MISSING = object()


def body():
    """The JSON body as a dict; an absent or unparseable body behaves as empty so
    that path resolution (ladder rule 4) still outranks shape validation (rule 6)."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def _bad(message):
    fail("ERR_INVALID_REQUEST", message)


def raw(data, key):
    return data.get(key, MISSING)


def need_str(data, key, min_len, max_len):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        _bad("%s is required" % key)
    if not isinstance(value, str):
        _bad("%s must be a string" % key)
    if len(value) < min_len or len(value) > max_len:
        _bad("%s must be between %d and %d characters" % (key, min_len, max_len))
    return value


def opt_str(data, key, min_len, max_len, default=None):
    if key not in data or data[key] is None:
        return default
    return need_str(data, key, min_len, max_len)


def need_enum(data, key, allowed):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        _bad("%s is required" % key)
    if not isinstance(value, str) or value not in allowed:
        _bad("%s must be one of %s" % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if key not in data or data[key] is None:
        return default
    return need_enum(data, key, allowed)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def need_int(data, key, minimum=None, maximum=None):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        _bad("%s is required" % key)
    if not _is_int(value):
        _bad("%s must be an integer" % key)
    if minimum is not None and value < minimum:
        _bad("%s must be at least %d" % (key, minimum))
    if maximum is not None and value > maximum:
        _bad("%s must be at most %d" % (key, maximum))
    return value


def opt_int(data, key, minimum=None, maximum=None, default=None):
    if key not in data or data[key] is None:
        return default
    return need_int(data, key, minimum, maximum)


def opt_bool(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, bool):
        _bad("%s must be a boolean" % key)
    return value


def need_instant(data, key):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        _bad("%s is required" % key)
    parsed = store.parse_instant(value)
    if parsed is None:
        _bad("%s must be an ISO 8601 UTC instant" % key)
    return parsed


def need_date(data, key):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        _bad("%s is required" % key)
    parsed = store.parse_date(value)
    if parsed is None:
        _bad("%s must be a calendar date in YYYY-MM-DD form" % key)
    return parsed


def need_code_array(data, key, allowed):
    """A list drawn from a declared code set, free of duplicates, possibly empty."""
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        _bad("%s is required" % key)
    if not isinstance(value, list):
        _bad("%s must be an array" % key)
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            _bad("%s members must be drawn from %s" % (key, ", ".join(allowed)))
        if item in seen:
            _bad("%s must not contain duplicates" % key)
        seen.add(item)
    return list(value)


def fk_lookup(data, key, table, not_found_id):
    """Ladder rule 5 - resolve a body foreign key in declaration order.

    Only a supplied string can name a record; anything else falls through to the
    shape check (rule 6) so that a missing or malformed identifier is a 400.
    """
    value = data.get(key, MISSING)
    if value is MISSING or not isinstance(value, str):
        return None
    record = table.get(value)
    if record is None:
        fail(not_found_id)
    return record
