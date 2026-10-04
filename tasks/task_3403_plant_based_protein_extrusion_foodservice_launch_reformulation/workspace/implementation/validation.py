# Request-shape validation (tier 11 of PRD 2.8): missing required inputs,
# invalid enum/type values, and violated type-conditional requirements are all
# ERR_INVALID_REQUEST (400) and are evaluated LAST, after every state gate.
# Getters therefore record problems instead of raising; handlers raise at the
# end of the validation cascade via shape.raise_if_any().
from clock import parse_dt
from errors import err


class Shape:
    def __init__(self):
        self.problems = []

    def add(self, field, msg):
        self.problems.append("%s %s" % (field, msg))

    def raise_if_any(self):
        if self.problems:
            raise err("ERR_INVALID_REQUEST", "; ".join(self.problems))


def body_json():
    from flask import request

    data = request.get_json(silent=True, force=True)
    if isinstance(data, dict):
        return data
    return {}


def get_str(body, field, shape, required=True, non_empty=False):
    if field not in body or body[field] is None:
        if required:
            shape.add(field, "is required")
        return None
    v = body[field]
    if not isinstance(v, str):
        shape.add(field, "must be a string")
        return None
    if non_empty and v == "":
        shape.add(field, "must be non-empty")
        return None
    return v


def get_int(body, field, shape, required=True, minv=None, maxv=None):
    if field not in body or body[field] is None:
        if required:
            shape.add(field, "is required")
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        shape.add(field, "must be an integer")
        return None
    if minv is not None and v < minv:
        shape.add(field, "must be at least %d" % minv)
        return None
    if maxv is not None and v > maxv:
        shape.add(field, "must be at most %d" % maxv)
        return None
    return v


def get_num(body, field, shape, required=True):
    if field not in body or body[field] is None:
        if required:
            shape.add(field, "is required")
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        shape.add(field, "must be a number")
        return None
    return v


def get_bool(body, field, shape, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            shape.add(field, "is required")
            return None
        return default
    v = body[field]
    if not isinstance(v, bool):
        shape.add(field, "must be a boolean")
        return None
    return v


def get_dt(body, field, shape, required=True):
    """Return (raw_string, datetime); records a shape problem when invalid."""
    if field not in body or body[field] is None:
        if required:
            shape.add(field, "is required")
        return None, None
    raw = body[field]
    if not isinstance(raw, str):
        shape.add(field, "must be an ISO-8601 timestamp string")
        return None, None
    dt = parse_dt(raw)
    if dt is None:
        shape.add(field, "must be an ISO-8601 timestamp string")
        return None, None
    return raw, dt


def get_enum(body, field, choices, shape, required=True):
    if field not in body or body[field] is None:
        if required:
            shape.add(field, "is required")
        return None
    v = body[field]
    if not isinstance(v, str) or v not in choices:
        shape.add(field, "must be one of %s" % ", ".join(choices))
        return None
    return v


def get_list(body, field, shape, required=True, item_choices=None, non_empty=False):
    if field not in body or body[field] is None:
        if required:
            shape.add(field, "is required")
        return None
    v = body[field]
    if not isinstance(v, list):
        shape.add(field, "must be an array")
        return None
    if non_empty and len(v) == 0:
        shape.add(field, "must be a non-empty array")
        return None
    if item_choices is not None:
        for item in v:
            if not isinstance(item, str) or item not in item_choices:
                shape.add(field, "contains an invalid value")
                return None
    return v
