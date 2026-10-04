"""Entity helpers: creation, serialization, common fields, parsing."""

import uuid
from datetime import datetime, timezone

import errors
from db import store


def new_id():
    return str(uuid.uuid4())


def now_iso():
    from response import iso_from

    return iso_from(store.clock)


def bump(entity):
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now_iso()


def base_entity():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def parse_iso(value, field="timestamp"):
    """Parse ISO8601 string into aware datetime (UTC assumed when naive with Z)."""
    if not isinstance(value, str):
        raise errors.validation(f"{field} must be an ISO8601 string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise errors.validation(f"{field} is not a valid ISO8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    from response import iso_from

    return iso_from(dt)


def require_field(body, name):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        raise errors.validation(f"missing required field: {name}")
    return body[name]


def req_int(body, name, minimum=None):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise errors.validation(f"{name} must be >= {minimum}")
    return v


def opt_int(body, name, default=None, minimum=None):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise errors.validation(f"{name} must be >= {minimum}")
    return v


def req_str(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or v == "":
        raise errors.validation(f"{name} must be a non-empty string")
    return v


def req_enum(body, name, choices):
    v = require_field(body, name)
    if v not in choices:
        raise errors.validation(f"{name} must be one of {sorted(choices)}")
    return v


def get_or_404(collection, entity_id, label="resource"):
    entity = collection.get(entity_id)
    if entity is None:
        raise errors.not_found(f"{label} not found: {entity_id}")
    return entity
