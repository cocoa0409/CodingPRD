"""Collection reads: filters, ordering, pagination (PRD 2.3)."""

from flask import request

from errors import APIError
from db import db
from response import page
from serializers import serialize_many

DEFAULT_LIMIT = 10
MAX_LIMIT = 100


def paginate(rows, collection):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = DEFAULT_LIMIT if limit_raw is None else _int(limit_raw, "limit")
    offset = 0 if offset_raw is None else _int(offset_raw, "offset")
    if limit < 1 or limit > MAX_LIMIT:
        raise APIError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise APIError("ERR_INVALID_REQUEST", "offset must not be negative.")
    total = len(rows)
    window = rows[offset:offset + limit]
    return page(serialize_many(collection, window), limit, offset, total)


def _int(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise APIError("ERR_INVALID_REQUEST", "The query parameter '%s' is not an integer." % name)


def apply_filters(rows, spec):
    """spec maps query-parameter name -> row field name."""
    result = rows
    for param, field in spec.items():
        value = request.args.get(param)
        if value is None:
            continue
        result = [r for r in result if _stringify(r.get(field)) == value]
    return result


def apply_int_filters(rows, spec):
    result = rows
    for param, field in spec.items():
        value = request.args.get(param)
        if value is None:
            continue
        try:
            wanted = int(value)
        except (TypeError, ValueError):
            continue
        result = [r for r in result if r.get(field) == wanted]
    return result


def _stringify(value):
    if value is None:
        return None
    return str(value)


def ordered(rows):
    return db.sorted_by_created(rows)