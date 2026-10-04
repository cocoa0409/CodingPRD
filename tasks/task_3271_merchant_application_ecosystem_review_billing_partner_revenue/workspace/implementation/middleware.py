"""Auth: header extraction, role checking, ownership helpers."""
from flask import request
from errors import ApiError
import db

VALID_ROLES = {"PlatformAdmin", "Developer", "Reviewer", "Merchant"}


def actor():
    """Return (user_id, role); raise ERR_UNAUTHENTICATED when missing/invalid."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    return uid, role


def require_role(*roles):
    uid, role = actor()
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this endpoint")
    return uid, role


def get_or_404(store, rid, label="resource"):
    obj = store.get(rid)
    if obj is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found: {rid}")
    return obj


def json_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return body


def require_fields(body, *fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"missing required field: {f}")
    return body


def touch(entity):
    """Refresh updated_at and bump version on a mutated entity."""
    entity["updated_at"] = db.fmt_dt(db.clock.now())
    entity["version"] = entity.get("version", 1) + 1


def new_entity():
    now = db.fmt_dt(db.clock.now())
    return {"id": db.new_uuid(), "created_at": now, "updated_at": now, "version": 1}
