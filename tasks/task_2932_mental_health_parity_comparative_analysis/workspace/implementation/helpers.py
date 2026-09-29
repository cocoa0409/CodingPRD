"""Shared route helpers: query filters, ordering and list responses (PRD 2.3)."""

from flask import request

from envelope import paginated, pagination_params
from store import creation_key


def _as_text(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def query_filters(rows, fields):
    """Exact-match filters taken from the query string, one per declared field."""
    out = list(rows)
    for field in fields:
        raw = request.args.get(field)
        if raw is None:
            continue
        out = [r for r in out if _as_text(r.get(field)) == raw]
    return out


def list_response(rows, serializer, filter_fields=()):
    rows = query_filters(rows, filter_fields)
    limit, offset = pagination_params()
    rows = sorted(rows, key=creation_key)
    total_count = len(rows)
    window = rows[offset:offset + limit]
    return paginated([serializer(row) for row in window], limit, offset, total_count)
