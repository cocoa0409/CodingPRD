"""Request-body shape and range checking (PRD 2.9 ladder position 3).

Everything here raises `ERR_INVALID_REQUEST`.  Structural failures are
diagnosed before any lookup, state or money rule so that a malformed request
can never surface a deeper business error.
"""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import bad_request
from timeutil import parse_ts

MISSING = object()


def raw_body(required=True):
    """Parse the JSON body.  Absent body is an empty object when optional."""
    data = request.get_json(silent=True)
    if data is None:
        if request.get_data() and required:
            raise bad_request("request body must be a JSON object")
        if required:
            raise bad_request("request body is required")
        return {}
    if not isinstance(data, dict):
        raise bad_request("request body must be a JSON object")
    return data


class Body(object):
    """A validated view over one request body."""

    def __init__(self, raw):
        self.raw = raw

    def present(self, key):
        return key in self.raw and self.raw[key] is not None

    def _fetch(self, key, required, default):
        if not self.present(key):
            if required:
                raise bad_request("%s is required" % key)
            return MISSING if default is MISSING else default
        return self.raw[key]

    # --- scalars ----------------------------------------------------------
    def string(self, key, required=True, max_len=None, default=None):
        value = self._fetch(key, required, default)
        if value is default and not self.present(key):
            return value
        if not isinstance(value, str) or not value.strip():
            raise bad_request("%s must be a non-empty string" % key)
        if max_len is not None and len(value) > max_len:
            raise bad_request("%s must be at most %d characters" % (key, max_len))
        return value

    def enum(self, key, allowed, required=True, default=None):
        value = self._fetch(key, required, default)
        if value is default and not self.present(key):
            return value
        if not isinstance(value, str) or value not in allowed:
            raise bad_request("%s must be one of %s" % (key, ", ".join(allowed)))
        return value

    def integer(self, key, required=True, minimum=1, maximum=None, default=None):
        value = self._fetch(key, required, default)
        if value is default and not self.present(key):
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad_request("%s must be an integer" % key)
        if minimum is not None and value < minimum:
            raise bad_request("%s must be at least %d" % (key, minimum))
        if maximum is not None and value > maximum:
            raise bad_request("%s must be at most %d" % (key, maximum))
        return value

    def boolean(self, key, required=True, default=None):
        value = self._fetch(key, required, default)
        if value is default and not self.present(key):
            return value
        if not isinstance(value, bool):
            raise bad_request("%s must be a boolean" % key)
        return value

    def decimal(
        self,
        key,
        required=True,
        minimum=Decimal("0"),
        exclusive_min=False,
        maximum=Decimal("100"),
        places=2,
        default=None,
    ):
        """A bounded decimal with a fixed maximum scale (percentages, ratios)."""
        value = self._fetch(key, required, default)
        if value is default and not self.present(key):
            return value
        if isinstance(value, bool):
            raise bad_request("%s must be a number" % key)
        if isinstance(value, (int, float)):
            text = repr(value) if isinstance(value, float) else str(value)
        elif isinstance(value, str):
            text = value.strip()
        else:
            raise bad_request("%s must be a number" % key)
        try:
            number = Decimal(text)
        except (InvalidOperation, ValueError):
            raise bad_request("%s must be a number" % key)
        if not number.is_finite():
            raise bad_request("%s must be a finite number" % key)
        if -number.as_tuple().exponent > places:
            raise bad_request("%s must have at most %d decimal places" % (key, places))
        if minimum is not None:
            if exclusive_min and number <= minimum:
                raise bad_request("%s must be greater than %s" % (key, minimum))
            if not exclusive_min and number < minimum:
                raise bad_request("%s must be at least %s" % (key, minimum))
        if maximum is not None and number > maximum:
            raise bad_request("%s must be at most %s" % (key, maximum))
        return number.quantize(Decimal(1).scaleb(-places))

    def timestamp(self, key, required=True, default=None):
        value = self._fetch(key, required, default)
        if value is default and not self.present(key):
            return value
        parsed = parse_ts(value)
        if parsed is None:
            raise bad_request("%s must be an ISO-8601 UTC timestamp" % key)
        return parsed

    def enum_list(self, key, allowed, required=True):
        value = self._fetch(key, required, None)
        if value is None and not self.present(key):
            return None
        if not isinstance(value, list) or not value:
            raise bad_request("%s must be a non-empty array" % key)
        seen = []
        for item in value:
            if not isinstance(item, str) or item not in allowed:
                raise bad_request(
                    "%s entries must be one of %s" % (key, ", ".join(allowed))
                )
            if item in seen:
                raise bad_request("%s must not contain duplicates" % key)
            seen.append(item)
        return seen


def body(required=True):
    return Body(raw_body(required=required))


def require_window(start, end, label="window"):
    """Start strictly before end."""
    if start is not None and end is not None and start >= end:
        raise bad_request("%s_start must be strictly before %s_end" % (label, label))
