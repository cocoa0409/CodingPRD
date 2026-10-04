"""Request-body validation helpers.

Body problems are collected, not raised, so semantic validations (priorities
3-10) run before the malformed-body check (priority 11, last resort). Call
finalize() once all semantic checks have had their chance.
"""
from flask import request

from errors import fail
from timeutil import parse_iso


class Body:
    def __init__(self):
        data = request.get_json(silent=True)
        self.d = data if isinstance(data, dict) else {}
        self.bad = False

    def raw(self, name):
        return self.d.get(name)

    def has(self, name):
        return name in self.d

    def str_(self, name, required=True):
        v = self.d.get(name)
        if v is None:
            if required:
                self.bad = True
            return None
        if not isinstance(v, str):
            self.bad = True
            return None
        return v

    def int_(self, name, required=True):
        v = self.d.get(name)
        if v is None:
            if required:
                self.bad = True
            return None
        if isinstance(v, bool) or not isinstance(v, int):
            self.bad = True
            return None
        return v

    def num_(self, name, required=True):
        v = self.d.get(name)
        if v is None:
            if required:
                self.bad = True
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            self.bad = True
            return None
        return v

    def dt_(self, name, required=True):
        v = self.d.get(name)
        if v is None:
            if required:
                self.bad = True
            return None
        if not isinstance(v, str):
            self.bad = True
            return None
        try:
            return parse_iso(v)
        except (ValueError, TypeError):
            self.bad = True
            return None

    def list_(self, name, required=True):
        v = self.d.get(name)
        if v is None:
            if required:
                self.bad = True
            return None
        if not isinstance(v, list):
            self.bad = True
            return None
        return v

    def enum_(self, name, values, required=True):
        v = self.str_(name, required)
        if v is not None and v not in values:
            self.bad = True
            return None
        return v

    def finalize(self):
        if self.bad:
            fail("ERR_INVALID_REQUEST", "Malformed request body: missing or mistyped field")


def parse_limit_offset():
    def to_int(s, default):
        try:
            return int(s)
        except (TypeError, ValueError):
            return default

    limit = to_int(request.args.get("limit"), 10)
    offset = to_int(request.args.get("offset"), 0)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
