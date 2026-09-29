"""Shared list/read plumbing for the read surfaces."""
from flask import request

import db
import response


def matches(row, spec):
    """spec maps a query parameter name to the row field it filters on."""
    for param, field in spec.items():
        wanted = request.args.get(param)
        if wanted is None or wanted == "":
            continue
        value = row.get(field)
        if value is None or str(value) != wanted:
            return False
    return True


def list_endpoint(kind, spec):
    limit, offset = response.pagination()
    items = [r for r in db.rows(kind) if matches(r, spec)]
    total = len(items)
    window = response.page(items, limit, offset)
    return response.listing([db.serialize(kind, r) for r in window], limit, offset, total)
