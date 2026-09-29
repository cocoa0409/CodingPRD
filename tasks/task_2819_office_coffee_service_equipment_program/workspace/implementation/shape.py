"""Request-shape validation (admission ladder rung 4) and pagination parsing.

Every input field declared without a default must be present; declared types must
match; enum values must be members of their declared set; integers must respect
their declared ranges; ISO-8601 instants must parse; limit and offset must respect
the pagination bounds of PRD 2.3. All failures are ERR_VALIDATION (400).
"""
from flask import request

from envelope import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from errors import ApiError
from timeutil import parse_date_only, parse_instant

_MISSING = object()


def body():
    payload = request.get_json(silent=True, force=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return payload


def _bad(field, why):
    raise ApiError("ERR_VALIDATION", "Field '%s' %s." % (field, why))


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


class Fields(object):
    """Accumulates validated values for one request body."""

    def __init__(self, payload):
        self.payload = payload
        self.values = {}

    def present(self, name):
        return name in self.payload and self.payload[name] is not None

    def raw_present(self, name):
        return name in self.payload

    def get(self, name, default=None):
        return self.values.get(name, default)

    def _fetch(self, name, required):
        if name not in self.payload or self.payload[name] is None:
            if required:
                _bad(name, "is required")
            return _MISSING
        return self.payload[name]

    def string(self, name, required=True, min_len=None, max_len=None):
        raw = self._fetch(name, required)
        if raw is _MISSING:
            return None
        if not isinstance(raw, str):
            _bad(name, "must be a string")
        if min_len is not None and len(raw) < min_len:
            _bad(name, "must be at least %d characters" % min_len)
        if max_len is not None and len(raw) > max_len:
            _bad(name, "must be at most %d characters" % max_len)
        self.values[name] = raw
        return raw

    def integer(self, name, required=True, minimum=None, maximum=None):
        raw = self._fetch(name, required)
        if raw is _MISSING:
            return None
        if not is_int(raw):
            _bad(name, "must be an integer")
        if minimum is not None and raw < minimum:
            _bad(name, "must be >= %d" % minimum)
        if maximum is not None and raw > maximum:
            _bad(name, "must be <= %d" % maximum)
        self.values[name] = raw
        return raw

    def boolean(self, name, required=True, default=None):
        raw = self._fetch(name, required)
        if raw is _MISSING:
            if default is not None:
                self.values[name] = default
            return default
        if not isinstance(raw, bool):
            _bad(name, "must be a boolean")
        self.values[name] = raw
        return raw

    def enum(self, name, allowed, required=True):
        raw = self._fetch(name, required)
        if raw is _MISSING:
            return None
        if not isinstance(raw, str) or raw not in allowed:
            _bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
        self.values[name] = raw
        return raw

    def instant(self, name, required=True):
        raw = self._fetch(name, required)
        if raw is _MISSING:
            return None
        if not isinstance(raw, str):
            _bad(name, "must be an ISO-8601 instant string")
        parsed = parse_instant(raw)
        if parsed is None:
            _bad(name, "must be a valid ISO-8601 instant")
        self.values[name] = parsed
        return parsed

    def array(self, name, required=True):
        raw = self._fetch(name, required)
        if raw is _MISSING:
            return None
        if not isinstance(raw, list):
            _bad(name, "must be an array")
        self.values[name] = raw
        return raw


def fields():
    return Fields(body())


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if raw_limit is not None:
        try:
            limit = int(raw_limit.strip())
        except (ValueError, AttributeError):
            _bad("limit", "must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            _bad("limit", "must be between %d and %d" % (MIN_LIMIT, MAX_LIMIT))
    if raw_offset is not None:
        try:
            offset = int(raw_offset.strip())
        except (ValueError, AttributeError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


def query_date(name, required=True):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            _bad(name, "is required")
        return None
    parsed = parse_date_only(raw)
    if parsed is None:
        _bad(name, "must be a valid date")
    return parsed


def query_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return _UNMATCHABLE


class _Unmatchable(object):
    def __eq__(self, other):
        return False

    def __ne__(self, other):
        return True

    def __hash__(self):
        return 0


_UNMATCHABLE = _Unmatchable()
