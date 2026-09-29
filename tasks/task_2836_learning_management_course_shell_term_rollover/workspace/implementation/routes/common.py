"""Shared route plumbing: response emission and list filtering."""

from flask import request

from db import by_created, flush
from errors import ApiError
from middleware import authenticate
from response import collection, no_content, paginate, read_page, single
from serialize import project, project_all
from util import BadValue, to_bool


def guard(*roles):
    return authenticate(roles)


def ok(record):
    flush()
    return single(project(record))


def created(record):
    flush()
    return single(project(record), 201)


def deleted():
    flush()
    return no_content()


def plain_ok(payload=None):
    flush()
    return single(payload if payload is not None else {})


def listing(records, order=None):
    limit, offset = read_page()
    ordered = by_created(records) if order is None else order(records)
    window = paginate(ordered, limit, offset)
    return collection(project_all(window), limit, offset, len(ordered))


def term_order(records):
    """The one departure from created_at ascending: term_start_at descending
    with created_at ascending as the tie-break (PRD 2.3)."""
    return sorted(records, key=lambda r: (-r["term_start_at"].timestamp(),
                                          r["created_at"], r["_seq"]))


def arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def bool_arg(name):
    value = arg(name)
    if value is None:
        return None
    try:
        return to_bool(value)
    except BadValue:
        raise ApiError("ERR_INVALID_REQUEST", "'%s' must be a boolean." % name)


def apply_filters(records, spec):
    """spec maps a query parameter name to the record field it filters."""
    out = list(records)
    for param, field in spec.items():
        wanted = arg(param)
        if wanted is None:
            continue
        out = [r for r in out if r.get(field) == wanted]
    return out
