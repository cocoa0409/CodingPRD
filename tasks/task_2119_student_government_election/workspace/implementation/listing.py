"""List helper: filter conjunctively, sort by created_at ASC, then paginate."""
import db
import response
import validation


def list_response(rows, serializer):
    limit, offset = validation.pagination()
    ordered = db.by_seq(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return response.array_response(
        [serializer(row) for row in page], limit, offset, total)


def filtered(collection, spec):
    """Every filter is optional and filters combine conjunctively (PRD 2.3)."""
    from flask import request
    rows = list(collection.values())
    for param, (field, caster) in spec.items():
        if param not in request.args:
            continue
        raw = request.args.get(param)
        value = caster(raw) if caster else raw
        if value is _NO_MATCH:
            return []
        rows = [row for row in rows if row.get(field) == value]
    return rows


class _NoMatch:
    pass


_NO_MATCH = _NoMatch()


def as_int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _NO_MATCH
