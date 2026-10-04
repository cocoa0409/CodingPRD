"""Auth middleware (SCAFFOLD §1.4 priorities 1-2 / PRD §2.1, §2.9).
Headers: X-User-ID and X-User-Role, both present and non-blank."""
from flask import request

from errors import raise_err

ALL_ROLES = [
    "ElectionOpsAdmin",
    "CoveragePlanner",
    "StringerCoordinator",
    "Stringer",
    "FeedOperator",
    "TabulationClerk",
    "DecisionAnalyst",
    "DecisionDeskChief",
    "RecountOfficer",
    "MediaCustomer",
]


def identity():
    """Priority 1: both headers present and non-blank, else 401."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip():
        raise_err("ERR_UNAUTHENTICATED", "X-User-ID header missing or blank")
    if role is None or not str(role).strip():
        raise_err("ERR_UNAUTHENTICATED", "X-User-Role header missing or blank")
    return uid, role


def require_roles(*roles):
    """Priorities 1-2: authentication then role admission for the endpoint."""
    uid, role = identity()
    if role not in roles:
        raise_err(
            "ERR_UNAUTHORIZED_ROLE",
            f"Role {role} is not permitted for this endpoint",
        )
    return uid, role


def body():
    """JSON request body as a dict; missing/malformed JSON reads as {}."""
    from flask import request as _req
    data = _req.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data
