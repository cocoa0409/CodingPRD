"""Shared list helper: filter, sort by created_at ASC, paginate."""

from middleware import get_pagination
from response import ok_list
from services.serialize import public_list


def list_response(rows, filters=None):
    items = [r for r in rows if filters is None or filters(r)]
    items.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return ok_list(public_list(page), limit, offset, total)
