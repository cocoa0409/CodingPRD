"""Request-shape validation — rung 6 of PRD §2.9 (ERR_INVALID_REQUEST, 400).

Required fields must be present, enum values must be declared members, integer
fields must be non-negative integers, and datetimes must parse as ISO 8601.
Fields the server computes are ignored when a client supplies them.
"""
import re

from flask import request

import db
from errors import ApiError

_HHMM_RE = re.compile(r"^([0-9]{1,2}):([0-9]{2})$")


def _bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise _bad("Request body must be a JSON object")
    return Body(raw)


class Body:
    def __init__(self, raw):
        self.raw = raw

    def has(self, name):
        return name in self.raw and self.raw[name] is not None

    def peek(self, name):
        value = self.raw.get(name)
        return value

    def peek_str(self, name):
        value = self.raw.get(name)
        return value if isinstance(value, str) else None

    # -- scalars ----------------------------------------------------------
    def string(self, name, required=True, default=None):
        if not self.has(name):
            if required:
                raise _bad("%s is required" % name)
            return default
        value = self.raw[name]
        if not isinstance(value, str) or not value.strip():
            raise _bad("%s must be a non-empty string" % name)
        return value

    def enum(self, name, allowed, required=True, default=None):
        if not self.has(name):
            if required:
                raise _bad("%s is required" % name)
            return default
        value = self.raw[name]
        if not isinstance(value, str) or value not in allowed:
            raise _bad("%s must be one of %s" % (name, ", ".join(sorted(allowed))))
        return value

    def integer(self, name, required=True, default=None, minimum=0):
        if not self.has(name):
            if required:
                raise _bad("%s is required" % name)
            return default
        value = self.raw[name]
        if isinstance(value, bool) or not isinstance(value, int):
            if isinstance(value, float) and float(value).is_integer():
                value = int(value)
            else:
                raise _bad("%s must be an integer" % name)
        if minimum is not None and value < minimum:
            raise _bad("%s must not be below %d" % (name, minimum))
        return value

    def number(self, name, required=True, default=None, minimum=0):
        if not self.has(name):
            if required:
                raise _bad("%s is required" % name)
            return default
        value = self.raw[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _bad("%s must be a number" % name)
        if minimum is not None and value < minimum:
            raise _bad("%s must not be below %s" % (name, minimum))
        return value

    def boolean(self, name, required=False, default=None):
        if not self.has(name):
            if required:
                raise _bad("%s is required" % name)
            return default
        value = self.raw[name]
        if not isinstance(value, bool):
            raise _bad("%s must be a boolean" % name)
        return value

    def datetime_str(self, name, required=True, default=None):
        """Return the client's exact ISO 8601 text after confirming it parses."""
        if not self.has(name):
            if required:
                raise _bad("%s is required" % name)
            return default
        value = self.raw[name]
        try:
            db.parse_iso(value)
        except Exception:
            raise _bad("%s must be an ISO 8601 timestamp" % name)
        return value

    def hhmm(self, name, required=False, default=None):
        if not self.has(name):
            if required:
                raise _bad("%s is required" % name)
            return default
        value = self.raw[name]
        if not isinstance(value, str):
            raise _bad("%s must be an HH:MM string" % name)
        match = _HHMM_RE.match(value.strip())
        if not match:
            raise _bad("%s must be an HH:MM string" % name)
        hours, minutes = int(match.group(1)), int(match.group(2))
        if hours > 23 or minutes > 59:
            raise _bad("%s must be a valid time of day" % name)
        return value

    def array(self, name, required=True, default=None):
        if not self.has(name):
            if required:
                raise _bad("%s is required" % name)
            return default
        value = self.raw[name]
        if not isinstance(value, list):
            raise _bad("%s must be an array" % name)
        return value

    def id_array(self, name, required=True, default=None):
        value = self.array(name, required=required, default=default)
        if value is None:
            return value
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise _bad("%s must contain only identifier strings" % name)
        return value

    def string_array(self, name, required=True, default=None):
        return self.id_array(name, required=required, default=default)


def parse_dt(value):
    return db.parse_iso(value)


def require_row(table, row_id, error_id, label=None):
    """Body / path foreign-key resolution — rungs 8 and 9."""
    if not isinstance(row_id, str) or row_id not in table:
        raise ApiError(error_id, "%s not found" % (label or "Resource"))
    return table[row_id]
