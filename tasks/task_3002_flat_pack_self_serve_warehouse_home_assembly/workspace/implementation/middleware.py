"""Auth header extraction and role checking (PRD §2.1)."""

from flask import request

from errors import raise_err

ROLES = {"PlatformAdmin", "StoreOps", "DeliveryCoordinator", "AssemblyProvider", "Customer"}


def get_auth():
    """Return (user_id, role). Rejects Anonymous / missing / unknown with 401."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-ID / X-User-Role")
    return user_id, role


def require_role(*roles):
    user_id, role = get_auth()
    if role not in roles:
        raise_err("ERR_FORBIDDEN", f"Role {role} is not permitted for this endpoint")
    return user_id, role


def check_customer_ownership(user_id, role, owner_customer_id):
    """A Customer may only act on its own resources (§2.1)."""
    if role == "Customer" and user_id != owner_customer_id:
        raise_err("ERR_FORBIDDEN", "Customer may only act on its own resources")
