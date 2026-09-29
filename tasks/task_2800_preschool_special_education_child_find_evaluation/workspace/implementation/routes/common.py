"""Shared list-endpoint plumbing."""
from db import ordered
from response import list_response
from validation import pagination


def paged(rows, serializer):
    limit, offset = pagination()
    rows = ordered(rows)
    total = len(rows)
    window = rows[offset : offset + limit]
    return list_response([serializer(row) for row in window], limit, offset, total)


def matches(row, field, value):
    return value is None or row.get(field) == value
