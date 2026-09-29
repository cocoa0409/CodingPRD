"""Generic schema validity (PRD 2.8 rule 8): required fields present, declared
types honoured, enum members in range, integers within their stated bounds and
datetimes well-formed ISO 8601 UTC instants -- all ERR_INVALID_REQUEST (400)."""
from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import invalid

_MISSING = object()


def body():
    """The JSON request body as a dict. A non-object body is a schema violation."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        invalid("Request body must be valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        invalid("Request body must be a JSON object.")
    return payload


def _present(data, name):
    return name in data and data[name] is not None


def require(data, name):
    if not _present(data, name):
        invalid("Field '%s' is required." % name)
    return data[name]


def string(data, name, required=True, default=None, min_len=1, max_len=None):
    if not _present(data, name):
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        invalid("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        invalid("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def integer(data, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(data, name):
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        invalid("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("Field '%s' must be at most %d." % (name, maximum))
    return value


def boolean(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % name)
    return value


def enum(data, name, allowed, required=True, default=None):
    if not _present(data, name):
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        invalid("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def instant(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        invalid("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    parsed = clock.parse_iso(value)
    if parsed is None:
        invalid("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    return parsed


def miles(data, name, required=True, default=None, minimum=None, strictly_positive=False):
    """A number carried to exactly two decimal places (PRD 2.6)."""
    if not _present(data, name):
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        invalid("Field '%s' must be a number." % name)
    if minimum is not None and dec < Decimal(minimum):
        invalid("Field '%s' must be at least %s." % (name, minimum))
    if strictly_positive and dec <= 0:
        invalid("Field '%s' must be greater than 0." % name)
    from calc import q2
    return q2(dec)


def polygon(data, name="polygon"):
    """An ordered array of vertices, each carrying latitude_micro/longitude_micro.

    Vertex-shape problems are generic schema failures; a ring with fewer than
    three vertices is the separate priority-9 ERR_INVALID_POLYGON check.
    """
    if not _present(data, name):
        invalid("Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, list):
        invalid("Field '%s' must be an array of vertices." % name)
    ring = []
    for vertex in value:
        if not isinstance(vertex, dict):
            invalid("Each vertex of '%s' must be an object." % name)
        lat = integer(vertex, "latitude_micro", minimum=-90000000, maximum=90000000)
        lon = integer(vertex, "longitude_micro", minimum=-180000000, maximum=180000000)
        ring.append({"latitude_micro": lat, "longitude_micro": lon})
    return ring


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < 1 or limit > 100:
            invalid("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            invalid("Query parameter 'offset' must be at least 0.")
    return limit, offset


def _query_int(name, raw):
    text = raw.strip()
    if text == "":
        invalid("Query parameter '%s' must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        invalid("Query parameter '%s' must be an integer." % name)
    return int(text)


def filter_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        invalid("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw


def filter_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
