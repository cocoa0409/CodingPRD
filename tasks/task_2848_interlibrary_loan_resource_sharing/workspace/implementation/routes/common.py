"""Shared helpers for the route modules."""
from db import by_created
from response import ok_list
from validate import page, pagination


def list_response(rows, sort_key=None):
    limit, offset = pagination()
    if sort_key is None:
        ordered = by_created(rows)
    else:
        ordered = sorted(rows, key=sort_key)
    page_rows, total = page(ordered, limit, offset)
    return ok_list(page_rows, limit, offset, total)


def filter_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]
