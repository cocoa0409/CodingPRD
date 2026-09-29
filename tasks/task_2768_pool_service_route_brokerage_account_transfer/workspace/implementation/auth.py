"""Authentication, RBAC and ownership -- PRD section 2.1 and checks 1-4 of 2.9."""

from flask import g, request

from errors import ApiError

ROLE_HEADER = "X-User-Role"
USER_HEADER = "X-User-ID"

ROLES = ("PlatformAdmin", "Broker", "Seller", "Buyer", "EscrowAgent")

# Roles whose X-User-ID is the id of a persisted entity.
ENTITY_BACKED = ("Seller", "Buyer")


def begin(*allowed_roles):
    """Check 1 (ERR_UNAUTHENTICATED) then check 2 (ERR_UNAUTHORIZED)."""
    role = request.headers.get(ROLE_HEADER)
    if role is None or role.strip() == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "The %s header is missing, empty or unrecognised." % ROLE_HEADER)
    user_id = request.headers.get(USER_HEADER) or ""
    g.role = role
    g.user_id = user_id
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s is not authorised for this operation." % role)
    return role, user_id


def actor():
    return g.get("role"), g.get("user_id")


def not_owner():
    raise ApiError("ERR_ACTOR_NOT_OWNER",
                   "The acting party does not own the addressed resource.")


def guard_seller_id(seller_id):
    """A Seller may only address resources hanging from its own seller record."""
    role, user_id = actor()
    if role == "Seller" and seller_id != user_id:
        not_owner()


def guard_buyer_id(buyer_id):
    role, user_id = actor()
    if role == "Buyer" and buyer_id != user_id:
        not_owner()


def guard_listing(listing):
    """Listings, stops, valuations and billing rows are seller-owned only."""
    if listing is not None:
        guard_seller_id(listing.get("seller_id"))


def guard_deal(deal, listing):
    """Deals and everything hanging from them are owned by the deal's buyer and
    by the seller of the deal's listing."""
    if deal is not None:
        guard_buyer_id(deal.get("buyer_id"))
    if listing is not None:
        guard_seller_id(listing.get("seller_id"))


def segregation_violation():
    raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                   "The acting identity collides with a conflicting earlier act.")
