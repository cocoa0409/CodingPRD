"""Reference resolution and list serving helpers."""

from db import db, public
from errors import ApiError
from response import list_response

NOT_FOUND = {
    "zones": "ERR_ZONE_NOT_FOUND",
    "segments": "ERR_SEGMENT_NOT_FOUND",
    "closures": "ERR_CLOSURE_NOT_FOUND",
    "merchants": "ERR_MERCHANT_NOT_FOUND",
    "robots": "ERR_ROBOT_NOT_FOUND",
    "bays": "ERR_BAY_NOT_FOUND",
    "reservations": "ERR_RESERVATION_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "missions": "ERR_MISSION_NOT_FOUND",
    "plans": "ERR_PLAN_NOT_FOUND",
    "interventions": "ERR_INTERVENTION_NOT_FOUND",
    "incidents": "ERR_INCIDENT_NOT_FOUND",
}


def find(collection_name, row_id):
    collection = getattr(db, collection_name)
    if not isinstance(row_id, str):
        return None
    return collection.get(row_id)


def must(collection_name, row_id):
    row = find(collection_name, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection_name])
    return row


def serve_list(rows, limit, offset, sort_key=None, reverse=False):
    ordered = list(rows)
    if sort_key is None:
        ordered.sort(key=lambda r: (r["created_at"], r["_seq"]))
    else:
        ordered.sort(key=sort_key, reverse=reverse)
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return list_response([public(r) for r in page], limit, offset, total)
