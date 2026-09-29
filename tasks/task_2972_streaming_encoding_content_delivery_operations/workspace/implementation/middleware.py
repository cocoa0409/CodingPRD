"""Rungs 1-5 of the validation ladder (PRD 2.1, 2.6)."""

import functools

from flask import g, request

from db import db
from errors import ApiError

ROLES = (
    "ContentOps",
    "QcAnalyst",
    "EncodingEngineer",
    "DrmOperator",
    "DeliveryEngineer",
    "PlatformAdmin",
    "VendorOperator",
)

VENDOR_OPERATOR = "VendorOperator"


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    return value


def authenticate(allowed_roles):
    """Rung 1: both credentials present and non-blank.  Rung 2: role recognised."""
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID is required")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is required")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "unrecognised role")
    # Rung 3: the role must appear in this endpoint's authorised list.
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", "role may not call this endpoint")
    g.user_id = user_id
    g.role = role
    g.vendor = None
    # Rung 4: a VendorOperator's identity must resolve to a registered vendor,
    # on every endpoint whose role list includes VendorOperator.
    if role == VENDOR_OPERATOR:
        vendor = db.vendors.get(user_id)
        if vendor is None:
            raise ApiError("ERR_VENDOR_IDENTITY_UNKNOWN", "unknown vendor identity")
        g.vendor = vendor
    return role


def _scope_violation():
    raise ApiError("ERR_VENDOR_SCOPE_VIOLATION", "vendor may only address its own data")


def enforce_scope(scope, kwargs):
    """Rung 5: the five self-scoped vendor operations."""
    if scope is None or g.role != VENDOR_OPERATOR:
        return
    args = request.args
    if scope == "vendor_path":
        if kwargs.get("vendor_id") != g.user_id:
            _scope_violation()
    elif scope == "metrics_list":
        if args.get("vendor_id") != g.user_id:
            _scope_violation()
    elif scope == "reservations_list":
        fields = ("primary_vendor_id", "failover_vendor_id", "active_vendor_id")
        if not any(args.get(f) == g.user_id for f in fields):
            _scope_violation()
    elif scope == "policies_list":
        fields = ("primary_vendor_id", "backup_vendor_id")
        if not any(args.get(f) == g.user_id for f in fields):
            _scope_violation()


def endpoint(roles, scope=None):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate(roles)
            enforce_scope(scope, kwargs)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
