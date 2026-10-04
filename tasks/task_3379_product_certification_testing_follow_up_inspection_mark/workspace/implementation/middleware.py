"""Authentication, role permission, and ownership helpers implementing
pipeline stages 1-3 of PRD 2.8."""
import functools

from flask import request

import db
from constants import ALL_ROLES, ENTITY_BACKED_ROLES, ROLE_AHJ, ROLE_REP
from errors import (
    ApiError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE,
)


def authenticate():
    """Stage 1: X-User-ID and X-User-Role present, role declared, and for
    entity-backed roles the X-User-ID resolves to a backing entity instance."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED,
                       "missing or invalid X-User-ID / X-User-Role headers")
    backing_store = ENTITY_BACKED_ROLES.get(role)
    if backing_store is not None:
        if user_id not in getattr(db, backing_store):
            raise ApiError(
                ERR_UNAUTHENTICATED,
                "entity-backed role id does not resolve to a %s instance"
                % backing_store,
            )
    return user_id, role


def require_roles(*roles):
    """Decorator: stage 1 (authentication) then stage 2 (role permission).
    Injects user_id and role kwargs into the view."""
    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in roles:
                raise ApiError(ERR_UNAUTHORIZED_ROLE,
                               "role %s is not permitted on this endpoint" % role)
            kwargs["user_id"] = user_id
            kwargs["role"] = role
            return view(*args, **kwargs)
        return wrapper
    return decorator


def any_authenticated(view):
    return require_roles(*ALL_ROLES)(view)


def check_rep_ownership(user_id, role, manufacturer_id):
    """Stage 3 ownership for ManufacturerRep: may only mutate resources whose
    manufacturer_id equals X-User-ID."""
    if role == ROLE_REP and manufacturer_id != user_id:
        raise ApiError(ERR_FORBIDDEN,
                       "ManufacturerRep may only mutate its own resources")


def check_ahj_ownership(user_id, role, site_jurisdiction_id):
    """Stage 3 ownership for AHJAuthority: decides acceptance only for the
    field evaluation whose site_jurisdiction_id equals X-User-ID."""
    if role == ROLE_AHJ and site_jurisdiction_id != user_id:
        raise ApiError(ERR_FORBIDDEN,
                       "AHJAuthority may only decide its own site jurisdiction")
