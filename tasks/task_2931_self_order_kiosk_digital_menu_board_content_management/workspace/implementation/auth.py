"""Authentication, role authorisation, device identity and store scope.

Precedence positions 1 to 4 of PRD 2.11, in that order.
"""
from flask import request

import constants as C
from db import DB
from errors import fail

ALL_READ_ROLES = ("PlatformAdmin", "ContentManager", "PricingAnalyst", "PricingApprover",
                  "ComplianceOfficer", "StoreOperator")


def authenticate():
    """Every request must carry X-User-ID and X-User-Role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = str(role).strip()
    if role not in C.ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role names an undeclared role")
    return {"user_id": str(user_id).strip(), "role": role}


def require_roles(ctx, roles):
    if ctx["role"] not in roles:
        fail("ERR_UNAUTHORIZED_ROLE", "role %s may not call this endpoint" % ctx["role"])
    return ctx


def enter(roles):
    """Positions 1 then 2 for one endpoint."""
    ctx = authenticate()
    require_roles(ctx, roles)
    return ctx


def require_device_identity(ctx, device_id):
    """Position 3: a DeviceAgent acts as exactly one device."""
    if ctx["role"] == "DeviceAgent" and ctx["user_id"] != device_id:
        fail("ERR_DEVICE_IDENTITY_MISMATCH", "a device may act only as itself")


def require_store_scope(ctx, store_id):
    """Position 4: a StoreOperator acts as exactly one store."""
    if ctx["role"] == "StoreOperator" and ctx["user_id"] != store_id:
        fail("ERR_STORE_SCOPE_VIOLATION", "the acting store does not own this resource")


def store_of_device(device_id):
    device = DB.devices.get(device_id)
    return device.get("store_id") if device else None
