"""Shared route helpers: identifier resolution and resource serialization."""
from flask import g

from calc import refresh_applicable_limit
from envelope import created, listing, ok
from errors import NOT_FOUND, ApiError
from store import public, sorted_rows
from validation import paginate, parse_pagination


def touched():
    return g.touched


def resolve(collection, field, ident):
    """Resolve one identifier or raise that resource type's 404."""
    row = collection.get(ident)
    if row is None:
        raise ApiError(NOT_FOUND[field])
    return row


def optional_resolve(collection, field, ident):
    if ident is None:
        return None
    return resolve(collection, field, ident)


def view(row):
    if row.get("_kind") == "Permit":
        refresh_applicable_limit(row)
    return public(row)


def one(row, status=200):
    if status == 201:
        return created(view(row))
    return ok(view(row))


def collection_response(rows, sort_key=None):
    limit, offset = parse_pagination()
    if sort_key is None:
        rows = sorted_rows(rows)
    else:
        rows = sorted(rows, key=sort_key)
    window, total = paginate(rows, limit, offset)
    return listing([view(r) for r in window], limit, offset, total)


def filtered(collection, filters):
    """Apply conjunctive equality filters, skipping None values."""
    rows = []
    for row in collection.values():
        keep = True
        for field, value in filters.items():
            if value is None:
                continue
            if row.get(field) != value:
                keep = False
                break
        if keep:
            rows.append(row)
    return rows
