"""Request shape validation -- ladder step 12, ERR_INVALID_REQUEST (400)."""

import re
from datetime import date, datetime, timezone

from flask import request

from errors import ERR_INVALID_REQUEST, fail

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def read_body():
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        fail(ERR_INVALID_REQUEST, "The request body must be a JSON object.")
    return Body(raw)


def parse_date_string(text):
    if not isinstance(text, str) or not _DATE_RE.match(text):
        return None
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:
        return None


def parse_instant(text):
    """Accepts ISO 8601 instants, with or without fractional seconds, with a
    trailing Z or an explicit UTC offset."""
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if candidate == "":
        return None
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        # A bare calendar date is also a valid ISO-8601 instant at midnight UTC.
        as_date = parse_date_string(text.strip())
        if as_date is None:
            return None
        return datetime(as_date.year, as_date.month, as_date.day, tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


class Body(object):
    def __init__(self, raw):
        self.raw = raw

    # -- presence helpers ----------------------------------------------------
    def present(self, name):
        return name in self.raw

    def value(self, name, default=None):
        return self.raw.get(name, default)

    def _missing(self, name):
        fail(ERR_INVALID_REQUEST, "Required field '%s' is missing." % name)

    def _bad(self, name, what):
        fail(ERR_INVALID_REQUEST, "Field '%s' %s." % (name, what))

    # -- typed accessors -----------------------------------------------------
    def string(self, name, required=True, min_len=None, max_len=None,
               nullable=False, default=None):
        if name not in self.raw:
            if required:
                self._missing(name)
            return default
        value = self.raw[name]
        if value is None:
            if nullable:
                return None
            if required:
                self._bad(name, "must be a string")
            return default
        if not isinstance(value, str):
            self._bad(name, "must be a string")
        if min_len is not None and len(value) < min_len:
            self._bad(name, "must be at least %d characters" % min_len)
        if max_len is not None and len(value) > max_len:
            self._bad(name, "must be at most %d characters" % max_len)
        return value

    def integer(self, name, required=True, minimum=None, maximum=None,
                nullable=False, default=None):
        if name not in self.raw:
            if required:
                self._missing(name)
            return default
        value = self.raw[name]
        if value is None:
            if nullable:
                return None
            if required:
                self._bad(name, "must be an integer")
            return default
        if not _is_int(value):
            self._bad(name, "must be an integer")
        if minimum is not None and value < minimum:
            self._bad(name, "must be at least %d" % minimum)
        if maximum is not None and value > maximum:
            self._bad(name, "must be at most %d" % maximum)
        return value

    def cents(self, name, required=True, nullable=False, default=None,
              strictly_positive=False):
        """Every *_cents field is a non-negative integer in requests (PRD 2.6)."""
        value = self.integer(name, required=required, minimum=0,
                             nullable=nullable, default=default)
        if strictly_positive and value is not None and value <= 0:
            self._bad(name, "must be strictly greater than 0")
        return value

    def bps(self, name, required=True, nullable=False, default=None):
        return self.integer(name, required=required, minimum=0,
                            nullable=nullable, default=default)

    def boolean(self, name, required=True, default=None):
        if name not in self.raw:
            if required:
                self._missing(name)
            return default
        value = self.raw[name]
        if not isinstance(value, bool):
            self._bad(name, "must be a boolean")
        return value

    def number(self, name, required=True, minimum=None, maximum=None,
               default=None):
        if name not in self.raw:
            if required:
                self._missing(name)
            return default
        value = self.raw[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self._bad(name, "must be a number")
        if minimum is not None and value < minimum:
            self._bad(name, "must be at least %s" % minimum)
        if maximum is not None and value > maximum:
            self._bad(name, "must be at most %s" % maximum)
        return value

    def enum(self, name, members, required=True, nullable=False, default=None):
        if name not in self.raw:
            if required:
                self._missing(name)
            return default
        value = self.raw[name]
        if value is None:
            if nullable:
                return None
            if required:
                self._bad(name, "must be one of %s" % ", ".join(members))
            return default
        if not isinstance(value, str) or value not in members:
            self._bad(name, "must be one of %s" % ", ".join(members))
        return value

    def date(self, name, required=True, nullable=False, default=None):
        if name not in self.raw:
            if required:
                self._missing(name)
            return default
        value = self.raw[name]
        if value is None:
            if nullable:
                return None
            if required:
                self._bad(name, "must be a YYYY-MM-DD calendar date")
            return default
        parsed = parse_date_string(value)
        if parsed is None:
            self._bad(name, "must be a YYYY-MM-DD calendar date")
        return value

    def instant(self, name, required=True, nullable=False, default=None):
        if name not in self.raw:
            if required:
                self._missing(name)
            return default
        value = self.raw[name]
        if value is None:
            if nullable:
                return None
            if required:
                self._bad(name, "must be an ISO-8601 instant")
            return default
        parsed = parse_instant(value)
        if parsed is None:
            self._bad(name, "must be an ISO-8601 instant")
        return parsed

    def enum_array(self, name, members, required=True, non_empty=True,
                   default=None):
        if name not in self.raw:
            if required:
                self._missing(name)
            return default
        value = self.raw[name]
        if not isinstance(value, list):
            self._bad(name, "must be an array")
        if non_empty and len(value) == 0:
            self._bad(name, "must be a non-empty array")
        for item in value:
            if not isinstance(item, str) or item not in members:
                self._bad(name, "must contain only %s" % ", ".join(members))
        return list(value)


def require_interval(start, end, start_name, end_name):
    """Interval field pairs satisfy a start strictly earlier than its end."""
    if start is not None and end is not None and not start < end:
        fail(ERR_INVALID_REQUEST,
             "'%s' must be strictly earlier than '%s'." % (start_name, end_name))
