"""Shared helpers: id minting, common-field stamping, pagination, payload parsing."""
import uuid

from flask import request

import errors
from db import wall_now_iso


def new_id():
    return str(uuid.uuid4())


def stamp_new(entity, common=True):
    ts = wall_now_iso()
    entity["created_at"] = ts
    if common:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def touch(entity):
    """updated_at + version increment on every mutation (common_fields entities)."""
    entity["updated_at"] = wall_now_iso()
    entity["version"] = int(entity.get("version", 1)) + 1
    return entity


def body():
    """JSON request body, tolerant of empty bodies."""
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise errors.validation("Request body must be a JSON object")
    return data


def pagination_args():
    """limit/offset with defaults 10/0, min 1, max 100."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        raise errors.validation("limit must be an integer")
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise errors.validation("offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.validation("limit must be between 1 and 100")
    if offset < 0:
        raise errors.validation("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending, then apply offset/limit."""
    ordered = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    total = len(ordered)
    return ordered[offset:offset + limit], total


def req_str(data, name):
    v = data.get(name)
    if not isinstance(v, str) or not v.strip():
        raise errors.validation(f"{name} is required and must be a non-empty string")
    return v


def req_int(data, name):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"{name} is required and must be an integer")
    return v


def opt_bool(data, name, default=False):
    v = data.get(name, default)
    if not isinstance(v, bool):
        raise errors.validation(f"{name} must be a boolean")
    return v


def req_enum(data, name, allowed):
    v = req_str(data, name)
    if v not in allowed:
        raise errors.validation(f"{name} must be one of {sorted(allowed)}")
    return v
