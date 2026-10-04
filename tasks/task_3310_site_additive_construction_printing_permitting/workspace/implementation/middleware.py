"""Auth header extraction, role checking, idempotency, pagination parsing."""
import json
from flask import request

from errors import raise_err
from errors import (
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    ERR_MISSING_IDEMPOTENCY_KEY,
    ERR_IDEMPOTENCY_REPLAY_MISMATCH,
    ERR_INVALID_REQUEST,
)
from db import store

ROLES = {
    "PlatformAdmin",
    "SiteManager",
    "PermitCoordinator",
    "JurisdictionReviewer",
    "Engineer",
    "PrintOperator",
    "QualityInspector",
    "TradeContractor",
}


def get_role():
    """Priority 1: X-User-Role present and known."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "X-User-Role header missing or unknown role")
    return role


def get_user_id():
    return request.headers.get("X-User-ID")


def require_roles(*allowed):
    """Priority 5: role authorized for this endpoint."""
    role = get_role()
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, "Role %s not permitted for this endpoint" % role)
    return role


def check_idempotency():
    """Priority 2/3: Idempotency-Key on POST; replay consistency.

    Returns the stored (status_code, body_dict) if this is a replay of an
    identical request, else None after recording nothing yet.
    """
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise_err(ERR_MISSING_IDEMPOTENCY_KEY, "Idempotency-Key header required on POST")
    raw = request.get_data(as_text=True) or ""
    try:
        canon = json.dumps(json.loads(raw), sort_keys=True)
    except Exception:
        canon = raw
    existing = store.idempotency.get(key)
    if existing is not None:
        if existing["body"] != canon:
            raise_err(
                ERR_IDEMPOTENCY_REPLAY_MISMATCH,
                "Idempotency-Key reused with a different request body",
            )
        return existing["status"], existing["response"]
    return None


def store_idempotency(status, response_body):
    key = request.headers.get("Idempotency-Key")
    if not key:
        return
    raw = request.get_data(as_text=True) or ""
    try:
        canon = json.dumps(json.loads(raw), sort_keys=True)
    except Exception:
        canon = raw
    store.idempotency[key] = {
        "body": canon,
        "status": status,
        "response": response_body,
    }


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset
