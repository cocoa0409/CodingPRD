"""Shared list-endpoint helper: default sort created_at ascending (insertion
sequence breaks same-instant ties), limit/offset windowing, envelope."""

from envelope import ok_list


def list_response(records, serializer, limit, offset):
    rows = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset : offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)
