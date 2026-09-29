"""Shared list-endpoint plumbing (PRD 2.3)."""

from decimal import Decimal

from envelope import list_response
from store import public
from validate import paginate, pagination


def _key(record, name):
    value = record.get(name)
    if value is None:
        return ""
    if isinstance(value, (int, Decimal, float)) and not isinstance(value, bool):
        return value
    return value


def emit_list(rows, sort_keys=("created_at",), view=public):
    limit, offset = pagination()
    ordered = sorted(
        rows,
        key=lambda r: tuple(_key(r, k) for k in sort_keys) + (r["created_at"], r["_seq"]),
    )
    page, total = paginate(ordered, limit, offset)
    return list_response([view(r) for r in page], limit, offset, total)
