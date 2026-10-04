"""Header authentication and role gating (PRD 2.1, validations priority 1-2)."""

from functools import wraps

from flask import request

from constants import ROLES
from errors import ApiError

ROLE_HEADER = "X-User-Role"
ID_HEADER = "X-User-ID"

# The only operation open to Anonymous is reading a load's customer-facing
# status timeline (PRD 2.1 / scaffold Table 7).
PUBLIC_PATHS = [
    ("GET", "/v1/loads/<load_id>/status-events"),
]


def _current_route_path():
    """Return the URL rule pattern for the matched endpoint, if any."""
    if request.url_rule is None:
        return None
    return request.url_rule.rule


def _is_public(method, rule):
    if rule is None:
        return False
    for allowed_method, pattern in PUBLIC_PATHS:
        if method == allowed_method and rule == pattern:
            return True
    return False


def authenticate():
    """Priority 1: both headers present and the role declared in PRD 2.1.

    Runs before every other check, including resource existence.
    """
    role = request.headers.get(ROLE_HEADER)
    identity = request.headers.get(ID_HEADER)
    if role is None or identity is None or role == "" or identity == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role: %s" % role)
    rule = _current_route_path()
    if role == "Anonymous" and not _is_public(request.method, rule):
        raise ApiError("ERR_UNAUTHORIZED", "Anonymous callers are admitted only on public operations.")
    return role, identity


def current_actor():
    role = request.headers.get(ROLE_HEADER)
    identity = request.headers.get(ID_HEADER)
    return role, identity


def roles_required(*allowed):
    """Priority 2: the acting role must be listed on the endpoint."""
    allowed_set = set(allowed)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            role, identity = authenticate()
            if role not in allowed_set:
                raise ApiError("ERR_UNAUTHORIZED",
                               "Role %s may not perform this operation." % role)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def require_owner(role, identity, owner_id, what="resource"):
    """Entity-backed actors act only on the resources they own."""
    if role in ("Anonymous", "PlatformAdmin", "ComplianceReviewer", "ClaimsAdjuster"):
        return
    if owner_id is None or owner_id != identity:
        raise ApiError("ERR_UNAUTHORIZED",
                       "The acting %s does not own this %s." % (role, what))