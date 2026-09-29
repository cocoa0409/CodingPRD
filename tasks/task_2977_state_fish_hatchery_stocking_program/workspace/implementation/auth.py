"""Ladder levels 1-3: authentication, role authorisation, scope and ownership."""

from flask import request

from constants import HATCHERY_MANAGER, PROGRAM_ADMIN
from errors import ApiError


def authenticate():
    """Level 1. 'A request whose X-User-ID header is absent, empty, or consists
    only of whitespace is rejected with ERR_UNAUTHENTICATED.'"""
    user_id = request.headers.get("X-User-ID")
    if user_id is None or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "The X-User-ID header is required.")
    return user_id


def authorize(*allowed_roles):
    """Levels 1 then 2, in that order. Returns (user_id, role)."""
    user_id = authenticate()
    role = request.headers.get("X-User-Role")
    if role is None or role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "This role may not invoke this operation.")
    return user_id, role


def scope_hatchery(role, user_id, hatchery_id):
    """Level 3. A HatcheryManager's X-User-ID is the id of the acting Hatchery."""
    if role == HATCHERY_MANAGER and user_id != hatchery_id:
        raise ApiError(
            "ERR_HATCHERY_SCOPE_VIOLATION",
            "This record belongs to another station.",
        )


def own_request(role, user_id, stocking_request):
    """Level 3. A ProgramAdmin is exempt from the request-ownership test."""
    if role == PROGRAM_ADMIN:
        return
    if stocking_request["requested_by_user_id"] != user_id:
        raise ApiError("ERR_NOT_REQUEST_OWNER", "This request belongs to another requester.")
