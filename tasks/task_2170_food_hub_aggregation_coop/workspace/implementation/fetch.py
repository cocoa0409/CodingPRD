"""Ladder rungs 4 and 5: path-segment and body foreign-key existence."""

from errors import ApiError
from store import db

_RESOLVERS = {
    "producer": ("producers", "ERR_PRODUCER_NOT_FOUND"),
    "document": ("documents", "ERR_DOCUMENT_NOT_FOUND"),
    "product": ("products", "ERR_PRODUCT_NOT_FOUND"),
    "buyer": ("buyers", "ERR_BUYER_NOT_FOUND"),
    "order": ("orders", "ERR_ORDER_NOT_FOUND"),
    "line": ("lines", "ERR_ORDER_NOT_FOUND"),
    "allocation": ("allocations", "ERR_ALLOCATION_NOT_FOUND"),
    "dock_slot": ("dock_slots", "ERR_DOCK_SLOT_NOT_FOUND"),
    "appointment": ("appointments", "ERR_APPOINTMENT_NOT_FOUND"),
    "route": ("routes", "ERR_ROUTE_NOT_FOUND"),
    "claim": ("claims", "ERR_CLAIM_NOT_FOUND"),
    "cycle": ("cycles", "ERR_CYCLE_NOT_FOUND"),
}


def get(kind, identifier):
    collection_name, error_id = _RESOLVERS[kind]
    collection = getattr(db, collection_name)
    if not isinstance(identifier, str):
        raise ApiError(error_id)
    record = collection.get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record


def body_fk(payload, field, kind):
    """Resolve a foreign key supplied in the request body (rung 5).

    A field that is absent altogether is left to the request-shape rung.
    """
    if field not in payload or payload[field] is None:
        return None
    return get(kind, payload[field])
