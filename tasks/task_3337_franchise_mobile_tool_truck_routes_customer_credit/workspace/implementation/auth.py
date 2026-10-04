"""Role resolution, RBAC and entity-backed ownership checks.

Every request carries X-User-ID and X-User-Role. Four roles are opaque
operator roles (PlatformAdmin, FranchiseManager, CreditOfficer, WarrantyAdmin)
whose identifier is never compared to an entity id. The other three are
entity-backed: FranchiseOwner and RouteSalesRep resolve to a Franchisee,
Technician resolves to a Technician.
"""

from flask import request

import store
from errors import fail

ROLES = (
    "PlatformAdmin",
    "FranchiseOwner",
    "FranchiseManager",
    "CreditOfficer",
    "RouteSalesRep",
    "WarrantyAdmin",
    "Technician",
)

OPAQUE_ROLES = ("PlatformAdmin", "FranchiseManager", "CreditOfficer", "WarrantyAdmin")


def actor():
    """Resolve the acting principal, refusing a request with no user context."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_MISSING_USER_CONTEXT")
    return user_id, role


def require(*allowed):
    """Resolve the actor and refuse a role that is not permitted here."""
    user_id, role = actor()
    if role not in allowed:
        fail("ERR_UNAUTHORIZED")
    return user_id, role


# --------------------------------------------------------------------------
# Ownership helpers — only entity-backed roles are ever checked.
# --------------------------------------------------------------------------

def owns_franchisee(user_id, role, franchisee_id):
    if role in OPAQUE_ROLES:
        return True
    return user_id == franchisee_id


def route_owner_id(route):
    return route.get("franchisee_id") if route else None


def shop_owner_id(shop):
    if not shop:
        return None
    route = store.routes.get(shop.get("route_id"))
    return route_owner_id(route)


def technician_owner_id(technician):
    """The franchisee the technician's workplace belongs to."""
    if not technician:
        return None
    shop = store.shops.get(technician.get("current_shop_location_id"))
    owner = shop_owner_id(shop)
    if owner:
        return owner
    route = store.routes.get(technician.get("home_route_id"))
    return route_owner_id(route)


def order_owner_id(order):
    if not order:
        return None
    return route_owner_id(store.routes.get(order.get("route_id")))


def account_owner_id(account):
    if not account:
        return None
    technician = store.technicians.get(account.get("technician_id"))
    owner = technician_owner_id(technician)
    if owner:
        return owner
    return route_owner_id(store.routes.get(account.get("territory_id")))


def application_owner_id(application):
    if not application:
        return None
    return shop_owner_id(store.shops.get(application.get("shop_location_id")))


def product_order_owner_id(product_order):
    if not product_order:
        return None
    return route_owner_id(store.routes.get(product_order.get("route_id")))


def pledge_owner_id(pledge):
    if not pledge:
        return None
    return product_order_owner_id(store.product_orders.get(pledge.get("product_order_id")))


def ensure_owned(user_id, role, owner_id):
    """Refuse an entity-backed actor mutating a resource it does not own."""
    if role in OPAQUE_ROLES:
        return
    if owner_id is None or owner_id != user_id:
        fail("ERR_UNAUTHORIZED")


def ensure_technician_self(user_id, role, technician_id):
    """A Technician role may only reach its own rows."""
    if role == "Technician" and user_id != technician_id:
        fail("ERR_UNAUTHORIZED")
