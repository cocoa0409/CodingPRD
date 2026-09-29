"""Rung 7: request-body shape and type conformance, plus query parsing.

Absent and explicitly-null are treated identically throughout ("not supplied"),
which is what the mechanism-gated and method-gated optional fields require.
"""
from decimal import Decimal

from flask import request

import util
from errors import ApiError


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def _parse():
    raw = request.get_data(cache=True)
    parsed, ok = util.loads_body(raw)
    if not ok or not isinstance(parsed, dict):
        return None
    return parsed


def peek_str(name):
    """Best-effort read of one body field for rung-5/rung-6 pre-resolution,
    which both run before the body has been shape-checked."""
    parsed = _parse()
    if parsed is None:
        return None
    value = parsed.get(name)
    return value if isinstance(value, str) else None


def peek_present(name):
    parsed = _parse()
    if parsed is None:
        return False
    return parsed.get(name) is not None


class Body(object):
    def __init__(self):
        parsed = _parse()
        if parsed is None:
            bad("Request body must be a JSON object.")
        self.raw = parsed
        self.seen = set()

    # -- plumbing ---------------------------------------------------------
    def _take(self, name):
        self.seen.add(name)
        value = self.raw.get(name)
        return value

    def _missing(self, name, required, default):
        if required:
            bad("Field '" + name + "' is required.")
        return default

    def close(self):
        extra = sorted(set(self.raw) - self.seen)
        if extra:
            bad("Unknown field '" + extra[0] + "'.")

    # -- typed readers ----------------------------------------------------
    def string(self, name, lo=1, hi=None, required=True, default=None):
        value = self._take(name)
        if value is None:
            return self._missing(name, required, default)
        if not isinstance(value, str):
            bad("Field '" + name + "' must be a string.")
        if len(value) < lo:
            bad("Field '" + name + "' is too short.")
        if hi is not None and len(value) > hi:
            bad("Field '" + name + "' is too long.")
        return value

    def email(self, name, lo, hi, required=True):
        value = self.string(name, lo, hi, required=required)
        if value is None:
            return None
        if value.count("@") != 1:
            bad("Field '" + name + "' must contain exactly one at-sign.")
        return value

    def digits(self, name, width, required=True, default=None):
        value = self._take(name)
        if value is None:
            return self._missing(name, required, default)
        if not isinstance(value, str):
            bad("Field '" + name + "' must be a string.")
        if len(value) != width or not value.isdigit():
            bad("Field '" + name + "' must be exactly "
                + str(width) + " digit characters.")
        return value

    def enum(self, name, members, required=True, default=None):
        value = self._take(name)
        if value is None:
            return self._missing(name, required, default)
        if not isinstance(value, str) or value not in members:
            bad("Field '" + name + "' must be one of "
                + ", ".join(members) + ".")
        return value

    def boolean(self, name, required=True, default=None):
        value = self._take(name)
        if value is None:
            return self._missing(name, required, default)
        if not isinstance(value, bool):
            bad("Field '" + name + "' must be a boolean.")
        return value

    def integer(self, name, lo=None, hi=None, required=True, default=None):
        value = self._take(name)
        if value is None:
            return self._missing(name, required, default)
        if isinstance(value, bool) or not isinstance(value, int):
            bad("Field '" + name + "' must be an integer.")
        if lo is not None and value < lo:
            bad("Field '" + name + "' is below the permitted minimum.")
        if hi is not None and value > hi:
            bad("Field '" + name + "' is above the permitted maximum.")
        return value

    def money(self, name, positive=False, required=True, default=None):
        """Money is always whole cents -- never a fractional value."""
        value = self.integer(name, required=required, default=default)
        if value is None:
            return None
        if positive and value <= 0:
            bad("Field '" + name + "' must be greater than zero.")
        if not positive and value < 0:
            bad("Field '" + name + "' must not be negative.")
        return value

    def quantity(self, name, positive=False, required=True, default=None):
        """Acreage / take / mitigation quantities: at most two fractional
        digits, and non-negative (or strictly positive)."""
        value = self._take(name)
        if value is None:
            return self._missing(name, required, default)
        if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
            bad("Field '" + name + "' must be a number.")
        number = util.to_dec(value)
        if util.decimal_places(number) > 2:
            bad("Field '" + name + "' may carry at most two decimal places.")
        if positive and number <= 0:
            bad("Field '" + name + "' must be greater than zero.")
        if not positive and number < 0:
            bad("Field '" + name + "' must not be negative.")
        return util.q2(number)

    def date(self, name, required=True, default=None):
        value = self._take(name)
        if value is None:
            return self._missing(name, required, default)
        if not isinstance(value, str):
            bad("Field '" + name + "' must be a calendar date string.")
        parsed = util.parse_date(value)
        if parsed is None:
            bad("Field '" + name + "' must be a valid YYYY-MM-DD date.")
        return parsed

    def instant(self, name, required=True, default=None):
        value = self._take(name)
        if value is None:
            return self._missing(name, required, default)
        if not isinstance(value, str):
            bad("Field '" + name + "' must be an ISO 8601 UTC instant.")
        parsed = util.parse_instant(value)
        if parsed is None:
            bad("Field '" + name + "' must be a valid ISO 8601 UTC instant.")
        return parsed

    def ident(self, name, required=True, default=None):
        value = self._take(name)
        if value is None:
            return self._missing(name, required, default)
        if not isinstance(value, str) or value == "":
            bad("Field '" + name + "' must be a non-empty identifier string.")
        return value

    def str_array(self, name, min_items, max_items, item_lo=1, item_hi=None,
                  width=None, required=True, default=None):
        value = self._take(name)
        if value is None:
            return self._missing(name, required, default)
        if not isinstance(value, list):
            bad("Field '" + name + "' must be an array.")
        if len(value) < min_items or len(value) > max_items:
            bad("Field '" + name + "' must carry between " + str(min_items)
                + " and " + str(max_items) + " entries.")
        for item in value:
            if not isinstance(item, str):
                bad("Every entry of '" + name + "' must be a string.")
            if width is not None:
                if len(item) != width or not item.isdigit():
                    bad("Every entry of '" + name + "' must be exactly "
                        + str(width) + " digit characters.")
            else:
                if len(item) < item_lo:
                    bad("An entry of '" + name + "' is too short.")
                if item_hi is not None and len(item) > item_hi:
                    bad("An entry of '" + name + "' is too long.")
        return list(value)


# --------------------------------------------------------------- queries ----


def _query_int(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None:
        return default
    text = raw.strip()
    negative = text.startswith("-")
    body = text[1:] if negative else text
    if body == "" or not body.isdigit():
        bad("Query parameter '" + name + "' must be an integer.")
    value = int(text)
    if lo is not None and value < lo:
        bad("Query parameter '" + name + "' is out of range.")
    if hi is not None and value > hi:
        bad("Query parameter '" + name + "' is out of range.")
    return value


def paging():
    """limit defaults to 10 and is bounded 1..100; out-of-range values are
    rejected, never clamped (PRD 2.3)."""
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def query_str(name):
    return request.args.get(name)


def query_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    bad("Query parameter '" + name + "' must be true or false.")
