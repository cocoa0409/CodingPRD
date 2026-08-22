"""Auth headers, RBAC and ownership checks — rungs 1 to 5 of PRD §2.9."""
from flask import g, request

import db
from errors import ApiError

ROLES = (
    "Exhibitor",
    "ShowOperations",
    "WarehouseAgent",
    "LaborSupervisor",
    "ClaimsAdjuster",
    "FinanceController",
)

ANY_ROLE = ROLES


def auth():
    """Rungs 1 and 2: both headers present and non-empty, role is one of the six."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = role.strip()
    uid = uid.strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_roles(*allowed):
    """Rung 3: the acting role must appear on the endpoint's authorised list."""
    uid, role = auth()
    flat = []
    for item in allowed:
        if isinstance(item, (list, tuple)):
            flat.extend(item)
        else:
            flat.append(item)
    if role not in flat:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint" % role)
    return uid, role


def own_exhibitor(exhibitor_id):
    """Rung 4: an acting Exhibitor may only touch its own account's resources."""
    if g.get("user_role") == "Exhibitor" and exhibitor_id is not None:
        if g.get("user_id") != exhibitor_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "Exhibitor may only act on its own resources")


def own_warehouse(warehouse_id):
    """Rung 4: an acting WarehouseAgent may only write against its own warehouse."""
    if g.get("user_role") == "WarehouseAgent" and warehouse_id is not None:
        if g.get("user_id") != warehouse_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "WarehouseAgent may only act on the warehouse it staffs")


def segregation(subject_user_id):
    """Rung 5: the acting operator must differ from the originating operator."""
    if subject_user_id is not None and g.get("user_id") == subject_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The originating operator may not take this decision")


# ---------------------------------------------------------------------------
# exhibitor reachability helpers (PRD §2.1: directly, or through the named row)
# ---------------------------------------------------------------------------

def booth_exhibitor(booth):
    return booth.get("exhibitor_id") if booth else None


def order_exhibitor(order):
    if not order:
        return None
    booth = db.store.booths.get(order.get("booth_id"))
    return booth_exhibitor(booth)
