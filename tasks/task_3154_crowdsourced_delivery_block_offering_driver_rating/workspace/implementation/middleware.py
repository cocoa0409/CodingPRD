"""Auth header extraction, role checking, and request helpers.

Header scheme (PRD §2.1): X-User-ID + X-User-Role on every request.
Roles: Anonymous, Driver, StationOps, PlatformAdmin, AppealsReviewer.
X-User-ID is required for every role except Anonymous.
"""

from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_VALIDATION

ROLES = {"Anonymous", "Driver", "StationOps", "PlatformAdmin", "AppealsReviewer"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority-1 auth check: headers present and well-formed."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or unknown X-User-Role")
    if role != "Anonymous" and (user_id is None or user_id == ""):
        raise_err(ERR_UNAUTHENTICATED, "Missing X-User-ID for a non-Anonymous role")
    return Caller(user_id=user_id, role=role)


def require_roles(caller, allowed):
    """Priority-2 role permission check."""
    if caller.role not in allowed:
        raise_err(ERR_FORBIDDEN, "Role %s is not permitted for this endpoint" % caller.role)


def require_driver_ownership(caller, driver_id):
    """Entity-backed ownership: Driver's X-User-ID must equal the resource's driver FK."""
    if caller.role == "Driver" and caller.user_id != driver_id:
        raise_err(ERR_FORBIDDEN, "Driver may only act on their own resources")


def get_json_body(required=True):
    """Parse request JSON body. Malformed JSON -> ERR_VALIDATION.

    Returns {} for empty bodies when not required.
    """
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        if required:
            raise_err(ERR_VALIDATION, "Request body is required")
        return {}
    import json as _json

    try:
        body = _json.loads(raw)
    except Exception:
        raise_err(ERR_VALIDATION, "Malformed JSON body")
    if not isinstance(body, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object")
    return body


def parse_pagination():
    """Parse limit/offset query params with defaults from scaffold §1.0.

    limit: default 10, min 1, max 100. offset: default 0, min 0.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        raise_err(ERR_VALIDATION, "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_VALIDATION, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset < 0:
        raise_err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset : offset + limit], total
