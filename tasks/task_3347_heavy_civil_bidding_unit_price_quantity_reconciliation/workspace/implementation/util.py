"""Shared helpers: decimal rounding, ISO-8601 handling and request-body reading."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import invalid_request

CENT = Decimal("1")
TWO_PLACES = Decimal("0.01")


def dec(value):
    """Decimal from an int/float/str without binary-float contamination."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise invalid_request("A boolean is not a number.")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_cents(value):
    """Round a Decimal to a whole number of cents, half away from zero."""
    return int(dec(value).quantize(CENT, rounding=ROUND_HALF_UP))


def round_2dp(value):
    """Round a Decimal to exactly two decimal places, half away from zero."""
    return dec(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def f2(value):
    """Two-decimal float rendering for percentage-valued derived figures."""
    return float(round_2dp(value))


# --------------------------------------------------------------------------
# ISO-8601 UTC timestamps (exactly three fractional digits on the way out)
# --------------------------------------------------------------------------

def parse_iso(value):
    if not isinstance(value, str) or not value.strip():
        raise invalid_request("An ISO 8601 UTC timestamp is required.")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise invalid_request("The timestamp %r is not a valid ISO 8601 instant." % (value,))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_iso(moment):
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (moment.astimezone(timezone.utc).microsecond // 1000)


# --------------------------------------------------------------------------
# Request body handling
# --------------------------------------------------------------------------

def read_body(required=(), optional=(), enums=None, numeric=None, booleans=()):
    """Read and validate the JSON body.

    Well-formedness failures (unparseable body, missing required field, unknown
    field, enum member outside its declared set) raise ERR_INVALID_REQUEST.
    """
    enums = enums or {}
    numeric = numeric or {}
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise invalid_request("The request body must be a JSON object.")

    allowed = set(required) | set(optional)
    for key in payload:
        if key not in allowed:
            raise invalid_request("Unknown field %r in the request body." % (key,))
    for key in required:
        if key not in payload:
            raise invalid_request("The field %r is required." % (key,))

    for key, members in enums.items():
        if key in payload and payload[key] is not None:
            if payload[key] not in members:
                raise invalid_request(
                    "The field %r must be one of %s." % (key, ", ".join(sorted(members)))
                )

    for key in booleans:
        if key in payload and payload[key] is not None and not isinstance(payload[key], bool):
            raise invalid_request("The field %r must be a boolean." % (key,))

    for key in numeric:
        if key in payload and payload[key] is not None:
            value = payload[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise invalid_request("The field %r must be a number." % (key,))

    for key in required:
        if payload.get(key) is None:
            raise invalid_request("The field %r is required." % (key,))

    return payload


def require_int(payload, key, minimum=None, maximum=None):
    value = payload.get(key)
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request("The field %r must be an integer." % (key,))
    if minimum is not None and value < minimum:
        raise invalid_request("The field %r must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise invalid_request("The field %r must be at most %s." % (key, maximum))
    return value


def optional_int(payload, key, default, minimum=None, maximum=None):
    if payload.get(key) is None:
        return default
    return require_int(payload, key, minimum=minimum, maximum=maximum)


def require_str(payload, key):
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise invalid_request("The field %r is required." % (key,))
    return value


def parse_pagination():
    """limit defaults to 10 and must be 1..100; offset defaults to 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("The limit parameter must be an integer.")
        if limit < 1 or limit > 100:
            raise invalid_request("The limit parameter must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("The offset parameter must be an integer.")
        if offset < 0:
            raise invalid_request("The offset parameter must be zero or greater.")
    return limit, offset
