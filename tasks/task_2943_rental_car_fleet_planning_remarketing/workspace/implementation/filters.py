"""Query filtering and the shared list-endpoint pipeline (PRD 2.3)."""

from flask import request

from envelope import listing, paginate, pagination
from store import sort_rows


def _match(row, field, raw, kind):
    value = row.get(field)
    if kind == "bool":
        lowered = raw.strip().lower()
        if lowered in ("true", "1"):
            want = True
        elif lowered in ("false", "0"):
            want = False
        else:
            return False
        return value is want
    if kind == "int":
        try:
            want = int(raw.strip())
        except (TypeError, ValueError):
            return False
        return value == want
    return value == raw


def apply_filters(rows, spec):
    out = list(rows)
    for param, field, kind in spec:
        raw = request.args.get(param)
        if raw is None:
            continue
        out = [row for row in out if _match(row, field, raw, kind)]
    return out


def collect(rows, spec, serializer, sort_keys=("created_at",)):
    """Pagination bounds fire at rank 7, before anything is filtered."""
    limit, offset = pagination()
    rows = apply_filters(rows, spec)
    rows = sort_rows(rows, sort_keys)
    total_count = len(rows)
    page = paginate(rows, limit, offset)
    return listing([serializer(row) for row in page], limit, offset, total_count)
