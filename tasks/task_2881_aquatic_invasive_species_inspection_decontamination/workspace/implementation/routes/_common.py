"""Helpers shared by every route module."""

from envelope import ok_list
from store import by_created_at, serialize
from validate import ALL_ROLES, page, read_pagination  # noqa: F401


def listing(rows, limit, offset):
    ordered = by_created_at(rows)
    items, total = page(ordered, limit, offset)
    return ok_list([serialize(r) for r in items], limit, offset, total)


def matches(row, filters):
    """filters is a dict of field -> expected value; None values are ignored."""
    for field, expected in filters.items():
        if expected is None:
            continue
        if row.get(field) != expected:
            return False
    return True
