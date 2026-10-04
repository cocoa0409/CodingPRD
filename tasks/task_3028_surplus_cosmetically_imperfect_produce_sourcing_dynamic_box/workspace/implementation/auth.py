"""§2.1 User and Role-Based Access Control."""

from flask import request

import common
import store
from common import ApiError

# Which persisted collection backs each entity-backed role.
ENTITY_BACKED = {
    common.ROLE_CUSTOMER: store.CUSTOMERS,
    common.ROLE_SUPPLIER: store.SUPPLIERS,
    common.ROLE_FULFILLMENT_OPERATOR: store.FULFILLMENT_CENTERS,
}


def authenticate():
    """Validation rung 1: both headers present, role recognized, id resolves."""
    user_id = request.headers.get(common.HEADER_USER_ID)
    role = request.headers.get(common.HEADER_USER_ROLE)
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers are both required.")
    if role not in common.RECOGNIZED_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-Role is not a recognized role.")
    if role in ENTITY_BACKED and user_id not in ENTITY_BACKED[role]:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "The supplied X-User-ID does not resolve to a stored row.")
    return {"id": user_id, "role": role}


def require_roles(actor, allowed):
    """Validation rung 2: the acting role is permitted for the operation."""
    if actor["role"] not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "The acting role may not perform this operation.")


def is_admin(actor):
    return actor["role"] == common.ROLE_PLATFORM_ADMIN


def owns_customer_scoped(actor, row):
    """Customer role: the row's customer_id must equal X-User-ID."""
    if actor["role"] == common.ROLE_CUSTOMER:
        return row.get("customer_id") == actor["id"]
    return True


def owns_supplier_scoped(actor, row):
    """Supplier role: the row's supplier_id must equal X-User-ID."""
    if actor["role"] == common.ROLE_SUPPLIER:
        return row.get("supplier_id") == actor["id"]
    return True


def owns_center_scoped(actor, row):
    """FulfillmentOperator role: the row's center must equal X-User-ID."""
    if actor["role"] == common.ROLE_FULFILLMENT_OPERATOR:
        return row.get("fulfillment_center_id") == actor["id"]
    return True


def enforce_customer_scope(actor, row):
    if not owns_customer_scoped(actor, row):
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "An entity-backed role may only act on its own resources.")


def enforce_center_scope(actor, row):
    if not owns_center_scoped(actor, row):
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "An entity-backed role may only act on its own resources.")


def enforce_operator_order_scope(actor, order):
    """A FulfillmentOperator acts only for its own center's lane."""
    if actor["role"] == common.ROLE_FULFILLMENT_OPERATOR:
        if order.get("fulfillment_center_id") != actor["id"]:
            raise ApiError("ERR_UNAUTHORIZED", 403,
                           "The order is outside the acting center's lane.")