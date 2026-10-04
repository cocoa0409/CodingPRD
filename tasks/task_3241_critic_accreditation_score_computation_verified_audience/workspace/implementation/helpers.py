"""Shared helpers: JSON body parsing, pagination, entity lifecycle."""
import uuid
from flask import request
from errors import err
from db import db, now_iso


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    return body[name]


def parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def new_entity(store, fields):
    """Create and store a new entity with common fields."""
    ent = dict(fields)
    ent["id"] = uuid.uuid4().hex
    ts = now_iso()
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    store[ent["id"]] = ent
    return ent


def touch(ent):
    """Refresh updated_at and bump version on mutation."""
    ent["updated_at"] = now_iso()
    ent["version"] = ent.get("version", 1) + 1


def get_or_404(store, entity_id, label="Resource"):
    ent = store.get(entity_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", "%s not found: %s" % (label, entity_id))
    return ent


def list_page(store, view_fn, filters=None):
    """Sorted-by-created_at list with pagination envelope inputs."""
    items = [e for e in store.values() if filters is None or filters(e)]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return [view_fn(e) for e in page], limit, offset, total
