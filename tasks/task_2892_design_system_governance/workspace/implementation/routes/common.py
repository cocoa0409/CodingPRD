"""Shared route helpers."""

from responses import listing
from store import paginate
from validation import pagination


def respond_list(rows, serializer, limit, offset):
    page, total, has_more = paginate(rows, limit, offset)
    return listing([serializer(r) for r in page], limit, offset, total, has_more)


__all__ = ["respond_list", "pagination"]
