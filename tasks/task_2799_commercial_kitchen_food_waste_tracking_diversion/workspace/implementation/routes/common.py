"""Shared route helpers."""
from db import db, sort_rows
from errors import fail
from response import list_response
from validation import paginate, pagination


def must_exist(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        fail(error_id)
    return row


def respond_list(rows):
    """Applies the default created_at ordering, then offset/limit pagination."""
    limit, offset = pagination()
    ordered = sort_rows(rows)
    page, total = paginate(ordered, limit, offset)
    return list_response(page, limit, offset, total)


def filtered(rows, **criteria):
    result = []
    for row in rows:
        keep = True
        for key, value in criteria.items():
            if value is None:
                continue
            if row.get(key) != value:
                keep = False
                break
        if keep:
            result.append(row)
    return result
