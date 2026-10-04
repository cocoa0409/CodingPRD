"""Shared helpers for route modules."""
import clock
from db import db
from errors import err_not_found
from response import success
from validation import parse_pagination


def touch(entity):
    entity["updated_at"] = clock.now_str()
    entity["version"] += 1


def stamp_new(entity):
    now = clock.now_str()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def get_or_404(collection, entity_id):
    entity = collection.get(entity_id)
    if entity is None:
        raise err_not_found()
    return entity


def list_response(collection, filters):
    """filters: list of (param_name, entity_field, allowed_set_or_None)."""
    from flask import request

    for param, _field, allowed in filters:
        raw = request.args.get(param)
        if raw is not None and allowed is not None and raw not in allowed:
            from errors import err_invalid_request

            raise err_invalid_request("Query parameter '%s' must be one of %s" % (param, sorted(allowed)))

    limit, offset = parse_pagination(request.args)
    items = sorted(collection.values(), key=lambda e: (e["created_at"], e["id"]))
    for param, field, _allowed in filters:
        raw = request.args.get(param)
        if raw is not None:
            items = [e for e in items if e.get(field) == raw]
    total = len(items)
    page = items[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success(page, status=200, pagination=pagination)


def shipment_for_order(order_id):
    for s in db.shipments.values():
        if s["order_id"] == order_id:
            return s
    return None
