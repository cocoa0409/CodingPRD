"""Header parsing plus role enforcement (validation priorities 1 and 2)."""

from flask import request

from errors import fail

ROLES = {
    "Consumer",
    "Referee",
    "BureauConnector",
    "LenderOps",
    "ComplianceOfficer",
    "PlatformAdmin",
    "DataProtectionOfficer",
}


def identity():
    """Return (user_id, role). Missing/malformed headers -> ERR_INVALID_REQUEST."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None:
        fail("ERR_INVALID_REQUEST", "X-User-ID and X-User-Role headers are required.")
    if not str(uid).strip() or not str(role).strip():
        fail("ERR_INVALID_REQUEST", "X-User-ID and X-User-Role headers must be well formed.")
    if role not in ROLES:
        fail("ERR_INVALID_REQUEST", "The supplied X-User-Role is not a declared role.")
    return str(uid), role


def require(roles):
    """Assert the caller's role is admitted by the endpoint. Returns identity."""
    uid, role = identity()
    if role not in roles:
        fail("ERR_FORBIDDEN_FOR_ROLE",
             "The caller's role is not permitted for this endpoint.")
    return uid, role


def body():
    from flask import request as _rq
    data = _rq.get_json(silent=True)
    if data is None:
        fail("ERR_INVALID_REQUEST", "A JSON request body is required.")
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def optional_body():
    from flask import request as _rq
    data = _rq.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data