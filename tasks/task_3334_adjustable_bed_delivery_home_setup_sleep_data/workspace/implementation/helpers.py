"""Entity lifecycle helpers: creation, mutation bookkeeping, serialization,
pagination parsing, and request-body field validation."""
import uuid

from db import DB, iso_z
from errors import err_validation
from flask import request


def new_entity(fields):
    """Create an entity dict with system fields; timestamps use the logical clock."""
    now = DB.clock.now_iso()
    ent = dict(fields)
    ent["id"] = str(uuid.uuid4())
    ent["created_at"] = now
    ent["updated_at"] = now
    ent["version"] = 1
    ent["_seq"] = DB.next_seq()
    return ent


def touch(ent):
    """Refresh updated_at and bump version by exactly 1 on every mutation."""
    ent["updated_at"] = DB.clock.now_iso()
    ent["version"] = ent.get("version", 1) + 1


def public(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def parse_pagination():
    """limit/offset per PRD §2.3: default 10, min 1, max 100, offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err_validation("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err_validation("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_validation("limit must be between 1 and 100")
    if offset < 0:
        raise err_validation("offset must be >= 0")
    return limit, offset


def sorted_items(items):
    """Default sort: created_at ascending, insertion seq as stable tie-break."""
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))


def page(items, limit, offset):
    return items[offset:offset + limit]


def body():
    """JSON request body; must be an object when present."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_validation("request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise err_validation("missing required field: %s" % name)
    return data[name]


def opt_field(data, name, default=None):
    v = data.get(name, default)
    return default if v is None else v


def require_str(v, name):
    if not isinstance(v, str):
        raise err_validation("%s must be a string" % name)
    return v


def require_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation("%s must be an integer" % name)
    return v


def require_bool(v, name):
    if not isinstance(v, bool):
        raise err_validation("%s must be a boolean" % name)
    return v


def require_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise err_validation("%s must be one of %s" % (name, ",".join(sorted(allowed))))
    return v
