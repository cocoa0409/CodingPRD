"""Authentication, role authorisation and client scoping."""

from flask import request

import db
from errors import ApiError

ROLES = (
    "CenterAdmin",
    "ReceivingClerk",
    "GradingInspector",
    "RefurbTechnician",
    "DispositionSupervisor",
    "RefundAnalyst",
    "ClientRep",
)

CLIENT_REP = "ClientRep"


def identity():
    """Priority 1: both headers present, non-empty, and the role a declared member."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if user_id == "" or role == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def require(*allowed):
    """Priority 1 then priority 2."""
    user_id, role = identity()
    if role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def scope(role, user_id, client_id):
    """Priority 3: a ClientRep may only reach its own client's resources."""
    if role != CLIENT_REP:
        return
    if client_id is None:
        return
    if client_id != user_id:
        raise ApiError("ERR_CLIENT_SCOPE_VIOLATION")


def scope_peek(role, user_id, client_id):
    """Priority 3 applied before shape validation: only fires for a real other client."""
    if role != CLIENT_REP or client_id is None:
        return
    if client_id != user_id and db.get("clients", client_id) is not None:
        raise ApiError("ERR_CLIENT_SCOPE_VIOLATION")


def narrow(role, user_id, filters):
    """Silently narrow a filtered list read for a ClientRep."""
    if role == CLIENT_REP:
        filters = dict(filters)
        filters["client_id"] = user_id
    return filters
