"""Shared list-endpoint plumbing: filtering, ordering and pagination.

PRD 2.3: unless a more specific ordering rule is stated, list endpoints return
resources ordered by their creation timestamp ascending, with deterministic
tie-breaking; every list response carries limit/offset/total_count/has_more.
"""

from flask import request

import response
import store


def _matches(value, raw, kind):
    if kind == "str":
        return value == raw
    if kind == "int":
        try:
            return value == int(raw)
        except (TypeError, ValueError):
            return False
    if kind == "bool":
        wanted = str(raw).strip().lower() in ("true", "1", "yes")
        return value is wanted
    return False


def apply_filters(rows, spec):
    """``spec`` is a sequence of (query_param, row_field, kind) triples."""
    args = request.args
    out = rows
    for param, field, kind in spec:
        raw = args.get(param)
        if raw is None or raw == "":
            continue
        out = [row for row in out if _matches(row.get(field), raw, kind)]
    return out


def render(rows, serializer):
    """Filter -> paginate -> serialize with the standard envelope."""
    limit, offset = response.read_pagination(request.args)
    page, total, _has_more = store.paginate(rows, limit, offset)
    return response.ok_list([serializer(row) for row in page], total, limit, offset)


def list_endpoint(rows, serializer, spec=()):
    return render(apply_filters(rows, spec), serializer)
