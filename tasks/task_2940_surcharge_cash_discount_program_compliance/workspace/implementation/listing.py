"""Collection reads: equality filters, default ordering and pagination (PRD 2.3)."""

from flask import request

from envelope import ok_list, paginate, pagination_params
from store import sort_rows

INVALID = object()


def arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value if value != "" else None


def bool_arg(name):
    value = arg(name)
    if value is None:
        return None
    low = value.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return INVALID


def enum_arg(name, members):
    value = arg(name)
    if value is None:
        return None
    return value if value in members else INVALID


def filtered(rows, specs):
    """Conjunctive equality filters; an unmatchable value selects nothing."""
    for value, key in specs:
        if value is None:
            continue
        if value is INVALID:
            return []
        rows = [row for row in rows if row.get(key) == value]
    return rows


def list_response(rows, serializer):
    limit, offset = pagination_params()
    rows = sort_rows(rows)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_list([serializer(row) for row in page], limit, offset, total)
