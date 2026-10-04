"""Shared request-validation and entity helpers."""
import uuid
from datetime import datetime, timezone

import clock
from db import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND


def new_id():
    return str(uuid.uuid4())


def get_body():
    body = {}
    try:
        body = __import__("flask").request.get_json(silent=True)
    except Exception:
        body = None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def require_fields(body, fields, allowed_extra=None):
    allowed = set(fields) | set(allowed_extra or [])
    for k in body.keys():
        if k not in allowed:
            raise_err(ERR_INVALID_REQUEST, f"unknown field: {k}")
    for f in fields:
        if f not in body or body[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"missing field: {f}")
    return body


def req_str(v, name):
    if not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, f"field {name} must be a non-empty string")
    return v


def req_int(v, name, minimum=None, maximum=None, allowed=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"field {name} must be an integer")
    if allowed is not None and v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"field {name} out of allowed set")
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, f"field {name} below minimum")
    if maximum is not None and v > maximum:
        raise_err(ERR_INVALID_REQUEST, f"field {name} above maximum")
    return v


def req_bool(v, name):
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"field {name} must be a boolean")
    return v


def req_enum(v, name, values):
    if not isinstance(v, str) or v not in values:
        raise_err(ERR_INVALID_REQUEST, f"field {name} must be one of {sorted(values)}")
    return v


def req_str_list(v, name, allow_empty=False):
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise_err(ERR_INVALID_REQUEST, f"field {name} must be an array of strings")
    if not allow_empty and len(v) == 0:
        raise_err(ERR_INVALID_REQUEST, f"field {name} must be non-empty")
    return v


def req_dt(v, name):
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"field {name} must be an ISO8601 datetime")
    try:
        s = v.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, f"field {name} is not a valid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(entity, has_version=True):
    """Bump version and updated_at after a mutation."""
    entity["updated_at"] = clock.now_iso()
    if has_version:
        entity["version"] = entity.get("version", 1) + 1


def get_or_404(collection, entity_id):
    coll = getattr(db, collection)
    ent = coll.get(entity_id)
    if ent is None:
        raise_err(ERR_NOT_FOUND, f"{collection} {entity_id} not found")
    return ent


def find_by(collection, field, value):
    for ent in getattr(db, collection).values():
        if ent.get(field) == value:
            return ent
    return None
