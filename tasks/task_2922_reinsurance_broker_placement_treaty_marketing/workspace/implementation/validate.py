"""Request-shape validation (PRD 2.6, priorities 5, 6 and 7).

Every failure here is ERR_VALIDATION / 400.  Money is an integer in minor units;
percentages carry at most four decimals; instants are ISO-8601 UTC with exactly
three fractional digits.
"""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import bad_request
from response import (
    PAGINATION_LIMIT_DEFAULT,
    PAGINATION_LIMIT_MAX,
    PAGINATION_LIMIT_MIN,
    PAGINATION_OFFSET_DEFAULT,
    PAGINATION_OFFSET_MIN,
)
from util import dec, parse_instant

MISSING = object()


def body():
    """Parse the JSON request body; a malformed body is a shape violation."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad_request("request body must be a JSON object")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad_request("request body must be a JSON object")
    return payload


class Shape(object):
    """Reads and checks one request body against the declared input contract."""

    def __init__(self, payload=None, patch=False):
        self.data = body() if payload is None else payload
        # In patch mode an omitted (or explicitly null) field means "unchanged".
        self.patch = patch

    # -- plumbing ----------------------------------------------------------
    def _raw(self, name, required, default):
        if name not in self.data:
            if required:
                bad_request("%s is required" % name)
            return MISSING if default is MISSING else default
        value = self.data[name]
        if value is None:
            if required:
                bad_request("%s must not be null" % name)
            return MISSING if default is MISSING else default
        return value

    def present(self, name):
        return name in self.data and self.data[name] is not None

    def reject_unknown(self, allowed):
        pass  # unknown members are ignored, not rejected

    # -- scalars -----------------------------------------------------------
    def string(self, name, min_len=1, max_len=None, required=True, default=MISSING):
        value = self._raw(name, required, default)
        if value is MISSING or value is None:
            return value if value is not MISSING else None
        if not isinstance(value, str):
            bad_request("%s must be a string" % name)
        if min_len is not None and len(value) < min_len:
            bad_request("%s must be at least %d characters" % (name, min_len))
        if max_len is not None and len(value) > max_len:
            bad_request("%s must be at most %d characters" % (name, max_len))
        return value

    def upper_code(self, name, length, required=True, default=MISSING):
        value = self.string(name, min_len=length, max_len=length,
                            required=required, default=default)
        if isinstance(value, str) and value != value.upper():
            bad_request("%s must be upper-case" % name)
        return value

    def enum(self, name, members, required=True, default=MISSING):
        value = self._raw(name, required, default)
        if value is MISSING or value is None:
            return value if value is not MISSING else None
        if not isinstance(value, str) or value not in members:
            bad_request("%s must be one of %s" % (name, ", ".join(members)))
        return value

    def boolean(self, name, required=True, default=MISSING):
        value = self._raw(name, required, default)
        if value is MISSING or value is None:
            return value if value is not MISSING else None
        if not isinstance(value, bool):
            bad_request("%s must be a boolean" % name)
        return value

    def integer(self, name, minimum=None, maximum=None, required=True,
                default=MISSING, exclusive_min=None):
        value = self._raw(name, required, default)
        if value is MISSING or value is None:
            return value if value is not MISSING else None
        if isinstance(value, bool) or not isinstance(value, int):
            bad_request("%s must be an integer" % name)
        return self._range(name, value, minimum, maximum, exclusive_min)

    def money(self, name, minimum=0, required=True, default=MISSING,
              exclusive_min=None, maximum=None):
        """A monetary amount: an integer number of minor units."""
        return self.integer(name, minimum=minimum, maximum=maximum,
                            required=required, default=default,
                            exclusive_min=exclusive_min)

    def percent(self, name, minimum=None, maximum=None, required=True,
                default=MISSING, exclusive_min=None, exclusive_max=None,
                places=4):
        value = self._raw(name, required, default)
        if value is MISSING or value is None:
            return value if value is not MISSING else None
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            bad_request("%s must be a number" % name)
        try:
            number = dec(value)
        except (InvalidOperation, ValueError, TypeError):
            bad_request("%s must be a number" % name)
        if -number.as_tuple().exponent > places:
            bad_request("%s must carry at most %d decimal places" % (name, places))
        number = number.quantize(Decimal(1).scaleb(-places))
        if exclusive_max is not None and number >= dec(exclusive_max):
            bad_request("%s must be less than %s" % (name, exclusive_max))
        return self._range(name, number, minimum, maximum, exclusive_min)

    def instant(self, name, required=True, default=MISSING):
        value = self._raw(name, required, default)
        if value is MISSING or value is None:
            return value if value is not MISSING else None
        parsed = parse_instant(value)
        if parsed is None:
            bad_request("%s must be an ISO-8601 UTC instant with milliseconds" % name)
        return parsed

    def enum_array(self, name, members, required=True, default=MISSING):
        value = self._raw(name, required, default)
        if value is MISSING or value is None:
            return value if value is not MISSING else None
        if not isinstance(value, list):
            bad_request("%s must be an array" % name)
        for member in value:
            if not isinstance(member, str) or member not in members:
                bad_request("%s members must be one of %s" % (name, ", ".join(members)))
        return list(value)

    def id_ref(self, name, required=True, default=MISSING):
        value = self._raw(name, required, default)
        if value is MISSING or value is None:
            return value if value is not MISSING else None
        if not isinstance(value, str) or value == "":
            bad_request("%s must be a non-empty identifier" % name)
        return value

    def _range(self, name, number, minimum, maximum, exclusive_min):
        if minimum is not None and number < dec(minimum):
            bad_request("%s must be at least %s" % (name, minimum))
        if exclusive_min is not None and number <= dec(exclusive_min):
            bad_request("%s must be greater than %s" % (name, exclusive_min))
        if maximum is not None and number > dec(maximum):
            bad_request("%s must be at most %s" % (name, maximum))
        return number


# ---------------------------------------------------------------------------
# Pagination (priority 7)
# ---------------------------------------------------------------------------

def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw, 10) if not raw.strip().startswith("+") else int(raw.strip()[1:], 10)
    except (TypeError, ValueError):
        bad_request("%s must be an integer" % name)
    if value < minimum:
        bad_request("%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        bad_request("%s must be at most %d" % (name, maximum))
    return value


def pagination():
    limit = _query_int("limit", PAGINATION_LIMIT_DEFAULT,
                       PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX)
    offset = _query_int("offset", PAGINATION_OFFSET_DEFAULT,
                        PAGINATION_OFFSET_MIN, None)
    return limit, offset


def query_enum(name, members):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in members:
        bad_request("%s must be one of %s" % (name, ", ".join(members)))
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad_request("%s must be a boolean" % name)


def query_id(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
