"""Rung 5 of the rejection ladder: request shape validation.

Every violation in here is an ERR_INVALID_REQUEST, so the internal ordering of
the individual checks is not observable.
"""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

MISSING = object()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"([Zz]|[+-]00:?00)$"
)


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def read_body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        bad("Request body is not valid JSON.")
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def parse_instant(value, name):
    if not isinstance(value, str):
        bad("%s must be an ISO-8601 instant string." % name)
    m = _TS_RE.match(value.strip())
    if not m:
        bad("%s must be a valid ISO-8601 UTC instant with a Z offset." % name)
    frac = m.group(7) or ".0"
    micro = min(999999, int(round(float(frac) * 1000000)))
    try:
        return datetime(
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
            int(m.group(4)),
            int(m.group(5)),
            int(m.group(6)),
            micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        bad("%s is not a real calendar instant." % name)


class F(object):
    """One declared input field."""

    def __init__(
        self,
        name,
        kind,
        required=True,
        default=MISSING,
        members=None,
        minv=None,
        maxv=None,
        gt=None,
        minlen=None,
        maxlen=None,
        nonblank=False,
        upper=False,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.members = members
        self.minv = minv
        self.maxv = maxv
        self.gt = gt
        self.minlen = minlen
        self.maxlen = maxlen
        self.nonblank = nonblank
        self.upper = upper

    def coerce(self, raw):
        name = self.name
        kind = self.kind
        if kind == "string":
            if not isinstance(raw, str):
                bad("%s must be a string." % name)
            if self.nonblank and raw.strip() == "":
                bad("%s must not be blank." % name)
            if self.minlen is not None and len(raw) < self.minlen:
                bad("%s is shorter than %d characters." % (name, self.minlen))
            if self.maxlen is not None and len(raw) > self.maxlen:
                bad("%s is longer than %d characters." % (name, self.maxlen))
            if self.upper and raw != raw.upper():
                bad("%s must be uppercase." % name)
            return raw
        if kind == "integer":
            if isinstance(raw, bool) or not isinstance(raw, int):
                bad("%s must be an integer." % name)
            return self._range(raw)
        if kind == "number":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                bad("%s must be a number." % name)
            try:
                val = Decimal(str(raw))
            except InvalidOperation:
                bad("%s must be a number." % name)
            if not val.is_finite():
                bad("%s must be a finite number." % name)
            return self._range(val)
        if kind == "boolean":
            if not isinstance(raw, bool):
                bad("%s must be a boolean." % name)
            return raw
        if kind == "enum":
            if not isinstance(raw, str) or raw not in self.members:
                bad("%s must be one of %s." % (name, ", ".join(self.members)))
            return raw
        if kind == "datetime":
            return parse_instant(raw, name)
        if kind == "date":
            if not isinstance(raw, str) or not _DATE_RE.match(raw):
                bad("%s must be a YYYY-MM-DD date." % name)
            try:
                datetime.strptime(raw, "%Y-%m-%d")
            except ValueError:
                bad("%s is not a real calendar date." % name)
            return raw
        if kind == "enum_array":
            if not isinstance(raw, list) or len(raw) == 0:
                bad("%s must be a non-empty array." % name)
            for item in raw:
                if not isinstance(item, str) or item not in self.members:
                    bad(
                        "%s members must be drawn from %s."
                        % (name, ", ".join(self.members))
                    )
            return list(raw)
        raise AssertionError("unknown kind " + kind)

    def _range(self, val):
        if self.gt is not None and not val > self.gt:
            bad("%s must be greater than %s." % (self.name, self.gt))
        if self.minv is not None and val < self.minv:
            bad("%s must be at least %s." % (self.name, self.minv))
        if self.maxv is not None and val > self.maxv:
            bad("%s must be at most %s." % (self.name, self.maxv))
        return val


def parse(specs, body=None):
    """Validate a body against its declared fields and return the values."""
    if body is None:
        body = read_body()
    out = {}
    for spec in specs:
        present = spec.name in body and body[spec.name] is not None
        if not present:
            if spec.required:
                bad("%s is required." % spec.name)
            if spec.default is not MISSING:
                out[spec.name] = spec.default
            continue
        out[spec.name] = spec.coerce(body[spec.name])
    return out


def require_interval(vals, start_name, end_name):
    start = vals.get(start_name)
    end = vals.get(end_name)
    if start is not None and end is not None and not end > start:
        bad("%s must be strictly after %s." % (end_name, start_name))
