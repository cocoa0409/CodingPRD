"""Shared route plumbing: role gates, list rendering and small predicates."""
import envelope
import validate


def list_result(rows, serializer, limit, offset):
    page, total = validate.paginate(rows, limit, offset)
    return envelope.array_response([serializer(row) for row in page], limit, offset, total)


def filter_eq(rows, key, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(key) == value]
