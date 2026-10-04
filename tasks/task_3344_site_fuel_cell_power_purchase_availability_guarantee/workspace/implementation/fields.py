"""Request-body field extraction.

Field-level defects are reported last (PRD 2.4), so a body records what is
missing or mistyped and surfaces the defect only when nothing earlier in the
validation order has already refused the request.
"""

from errors import ERR_INVALID_REQUEST, ApiError


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_string(value):
    return isinstance(value, str)


def _is_bool(value):
    return isinstance(value, bool)


TYPE_CHECKS = {
    "string": _is_string,
    "number": _is_number,
    "integer": _is_int,
    "boolean": _is_bool,
    "datetime": _is_string,
    "enum": _is_string,
}


class Body:
    def __init__(self, raw):
        self.raw = raw if isinstance(raw, dict) else {}
        self.problems = []

    def has(self, name):
        return name in self.raw and self.raw.get(name) is not None

    def req(self, name, kind=None, enum=None, allow_null=False):
        if name not in self.raw or (self.raw.get(name) is None and not allow_null):
            self.problems.append("%s is required" % name)
            return None
        value = self.raw.get(name)
        if value is None:
            return None
        if kind and not TYPE_CHECKS.get(kind, lambda v: True)(value):
            self.problems.append("%s has the wrong type" % name)
            return None
        if enum is not None and value not in enum:
            self.problems.append("%s is not one of the declared values" % name)
            return None
        return value

    def opt(self, name, kind=None, enum=None, default=None):
        if name not in self.raw or self.raw.get(name) is None:
            return default
        value = self.raw.get(name)
        if kind and not TYPE_CHECKS.get(kind, lambda v: True)(value):
            self.problems.append("%s has the wrong type" % name)
            return default
        if enum is not None and value not in enum:
            self.problems.append("%s is not one of the declared values" % name)
            return default
        return value

    def num(self, name, default=0):
        value = self.opt(name, kind="number")
        return default if value is None else value

    def intg(self, name, default=0):
        value = self.opt(name, kind="integer")
        return default if value is None else value

    def strg(self, name, default=None):
        value = self.opt(name, kind="string")
        return default if value is None else value

    def raise_if_invalid(self):
        if self.problems:
            raise ApiError(ERR_INVALID_REQUEST, "; ".join(self.problems), 400)

    def raise_now(self):
        """For bodies so incomplete that no earlier check can be evaluated."""
        self.raise_if_invalid()
