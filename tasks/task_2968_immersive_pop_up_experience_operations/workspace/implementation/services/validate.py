"""Request-shape validation — ladder rung 4 (PRD §2.7).

Every failure in this module raises ERR_VALIDATION / 422.  Nothing here knows
about stored state; foreign keys, uniqueness and state gates live further up
the ladder.
"""

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{3}))?Z$")


def fail(message):
    raise ApiError("ERR_VALIDATION", message)


def json_body(required=False):
    """The parsed JSON object, or {} when the caller sent nothing."""
    if not request.data:
        if required:
            fail("A JSON request body is required.")
        return {}
    raw = request.get_json(silent=True)
    if raw is None:
        fail("The request body is not valid JSON.")
    if not isinstance(raw, dict):
        fail("The request body must be a JSON object.")
    return raw


def parse_date(value, name):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        fail("%s must be a 10-character ISO calendar date (YYYY-MM-DD)." % name)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        fail("%s is not a real calendar date." % name)


def parse_instant(value, name):
    if not isinstance(value, str):
        fail("%s must be an ISO 8601 UTC instant." % name)
    m = _INSTANT_RE.match(value)
    if not m:
        fail("%s must be an ISO 8601 UTC instant ending in Z with zero or three "
             "fractional digits." % name)
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            int(m.group(7) or 0) * 1000, tzinfo=timezone.utc,
        )
    except ValueError:
        fail("%s is not a real UTC instant." % name)


class Body(object):
    """Thin declarative reader over a JSON request body."""

    def __init__(self, raw=None, require_body=False):
        self.raw = json_body(require_body) if raw is None else raw

    # -- presence -------------------------------------------------------
    def has(self, name):
        return name in self.raw and self.raw[name] is not None

    def _get(self, name, required, default):
        if name not in self.raw or self.raw[name] is None:
            if required:
                fail("Field '%s' is required." % name)
            return default, False
        return self.raw[name], True

    # -- scalars --------------------------------------------------------
    def string(self, name, required=True, default=None, min_len=None,
               max_len=None, pattern=None):
        value, present = self._get(name, required, default)
        if not present:
            return value
        if not isinstance(value, str):
            fail("Field '%s' must be a string." % name)
        if min_len is not None and len(value) < min_len:
            fail("Field '%s' must be at least %d characters." % (name, min_len))
        if max_len is not None and len(value) > max_len:
            fail("Field '%s' may not exceed %d characters." % (name, max_len))
        if pattern is not None and not re.match(pattern, value):
            fail("Field '%s' does not match its required pattern." % name)
        return value

    def integer(self, name, required=True, default=None, minimum=None, maximum=None):
        value, present = self._get(name, required, default)
        if not present:
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            fail("Field '%s' must be an integer." % name)
        if minimum is not None and value < minimum:
            fail("Field '%s' may not be smaller than %d." % (name, minimum))
        if maximum is not None and value > maximum:
            fail("Field '%s' may not be larger than %d." % (name, maximum))
        return value

    def number(self, name, required=True, default=None, minimum=None,
               maximum=None, exclusive_minimum=None):
        value, present = self._get(name, required, default)
        if not present:
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail("Field '%s' must be a number." % name)
        try:
            dec = Decimal(str(value))
        except InvalidOperation:
            fail("Field '%s' must be a number." % name)
        if minimum is not None and dec < Decimal(str(minimum)):
            fail("Field '%s' may not be smaller than %s." % (name, minimum))
        if maximum is not None and dec > Decimal(str(maximum)):
            fail("Field '%s' may not be larger than %s." % (name, maximum))
        if exclusive_minimum is not None and dec <= Decimal(str(exclusive_minimum)):
            fail("Field '%s' must be greater than %s." % (name, exclusive_minimum))
        return value

    def boolean(self, name, required=True, default=None):
        value, present = self._get(name, required, default)
        if not present:
            return value
        if not isinstance(value, bool):
            fail("Field '%s' must be a boolean." % name)
        return value

    def enum(self, name, values, required=True, default=None):
        value, present = self._get(name, required, default)
        if not present:
            return value
        if not isinstance(value, str):
            fail("Field '%s' must be a string." % name)
        if value not in values:
            fail("Field '%s' must be one of %s." % (name, ", ".join(values)))
        return value

    def enum_array(self, name, values, required=True, default=None,
                   allow_empty=True):
        value, present = self._get(name, required, default)
        if not present:
            return list(default) if isinstance(default, (list, tuple)) else default
        if not isinstance(value, list):
            fail("Field '%s' must be an array." % name)
        if not allow_empty and len(value) == 0:
            fail("Field '%s' may not be empty." % name)
        seen = set()
        for item in value:
            if not isinstance(item, str) or item not in values:
                fail("Field '%s' carries an undeclared member." % name)
            if item in seen:
                fail("Field '%s' carries duplicates." % name)
            seen.add(item)
        return list(value)

    def string_array(self, name, required=True, default=None, allow_empty=True,
                     min_len=None, max_len=None, pattern=None):
        value, present = self._get(name, required, default)
        if not present:
            return list(default) if isinstance(default, (list, tuple)) else default
        if not isinstance(value, list):
            fail("Field '%s' must be an array." % name)
        if not allow_empty and len(value) == 0:
            fail("Field '%s' may not be empty." % name)
        seen = set()
        for item in value:
            if not isinstance(item, str):
                fail("Field '%s' must be an array of strings." % name)
            if min_len is not None and len(item) < min_len:
                fail("Field '%s' members must be at least %d characters." % (name, min_len))
            if max_len is not None and len(item) > max_len:
                fail("Field '%s' members may not exceed %d characters." % (name, max_len))
            if pattern is not None and not re.match(pattern, item):
                fail("Field '%s' members do not match the required pattern." % name)
            if item in seen:
                fail("Field '%s' carries duplicates." % name)
            seen.add(item)
        return list(value)

    def reference(self, name, required=True, default=None):
        """A foreign-key field: must be a non-empty string at rung 4."""
        value, present = self._get(name, required, default)
        if not present:
            return value
        if not isinstance(value, str) or value.strip() == "":
            fail("Field '%s' must be a non-empty id string." % name)
        return value

    def date_field(self, name, required=True, default=None):
        value, present = self._get(name, required, default)
        if not present:
            return None, value
        return parse_date(value, name), value

    def instant_field(self, name, required=True, default=None):
        value, present = self._get(name, required, default)
        if not present:
            return None, value
        return parse_instant(value, name), value


# ---------------------------------------------------------------------------
# query-string helpers (list filters)
# ---------------------------------------------------------------------------

def query_int(name, default=None, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("%s may not be smaller than %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("%s may not be larger than %d." % (name, maximum))
    return value


def query_enum(name, values, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if raw not in values:
        fail("%s must be one of %s." % (name, ", ".join(values)))
    return raw
