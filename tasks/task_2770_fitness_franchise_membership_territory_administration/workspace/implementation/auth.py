"""Bands 1-3 of PRD 2.6: authentication, role authorization, resource ownership."""
from flask import request

from config import ROLES
from errors import ApiError


def authenticate():
    """Band 1. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return uid, role


def authorize(role, allowed):
    """Band 2."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def require_owner(condition):
    """Band 3."""
    if not condition:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def guard(allowed):
    """Bands 1+2 in one call."""
    uid, role = authenticate()
    authorize(role, allowed)
    return uid, role
