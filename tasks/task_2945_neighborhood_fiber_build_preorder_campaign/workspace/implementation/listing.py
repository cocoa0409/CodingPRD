"""Query filters (PRD 2.11). Foreign-key filters resolve before pagination is parsed."""

from flask import request

from errors import ApiError
from store import must_find


def fk(param, field, collection):
    return ("fk", param, field, collection)


def enum(param, field, allowed):
    return ("enum", param, field, allowed)


def text(param, field):
    return ("text", param, field, None)


def apply_filters(items, specs):
    for kind, param, field, arg in specs:
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if kind == "fk":
            must_find(arg, raw)
        elif kind == "enum" and raw not in arg:
            raise ApiError("ERR_INVALID_REQUEST", "%s is not a recognized value" % param)
        items = [row for row in items if row.get(field) == raw]
    return items


def resolve(data, field, collection):
    """Ladder step 4: resolve a body foreign key, deferring shape problems to step 7."""
    if field not in data or data[field] is None:
        return None
    value = data[field]
    if not isinstance(value, str) or value.strip() == "":
        return None
    return must_find(collection, value)
