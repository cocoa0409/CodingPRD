"""Shared helpers: entity construction, pagination, OCC, parsing."""
import uuid

from flask import request

from db import db, _parse_iso, _format_iso
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_STALE_VERSION
from response import success_list


def new_id():
    return str(uuid.uuid4())


def touch(entity, bump_version=True):
    """Refresh updated_at and (optionally) increment version on a mutated entity."""
    entity["updated_at"] = db.now_iso()
    if bump_version and "version" in entity:
        entity["version"] += 1


def base_entity(has_version=True):
    now = db.now_iso()
    e = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
    }
    if has_version:
        e["version"] = 1
    return e


def get_body():
    """Return the JSON request body as a dict; {} for empty bodies on POST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "Malformed JSON payload", 400)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Payload must be a JSON object", 400)
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {f}", 400)


def get_pagination():
    """Parse limit/offset query params with defaults limit=10, min 1, max 100."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, "limit must be between 1 and 100", 400)
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)
    return limit, offset


def list_response(collection, filters=None):
    """Sort by created_at ascending, apply equality filters, paginate, respond.

    filters: dict of field_name -> raw query string value (None = skip).
    """
    items = sorted(collection.values(),
                   key=lambda e: (e["created_at"], e["id"]))
    if filters:
        for field, raw in filters.items():
            if raw is None:
                continue
            items = [e for e in items if _matches(e.get(field), raw)]
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list(page, limit, offset, total)


def _matches(value, raw):
    if isinstance(value, bool):
        return raw.lower() in ("true", "1") == value
    if isinstance(value, int):
        try:
            return value == int(raw)
        except ValueError:
            return False
    return str(value) == raw


def lookup(collection, entity_id, what="Resource"):
    e = collection.get(entity_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, f"{what} does not exist", 404)
    return e


def check_occ(body, occ_field, entity):
    """If the OCC field is present in the body, compare against entity version.

    Per skill guidance: when the field is omitted, skip the check. On mismatch,
    ERR_STALE_VERSION (412).
    """
    if occ_field in body and body[occ_field] is not None:
        try:
            expected = int(body[occ_field])
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST,
                           f"{occ_field} must be an integer", 400)
        if expected != entity.get("version"):
            raise ApiError(ERR_STALE_VERSION,
                           f"{occ_field} does not match current version", 412)


def parse_datetime_field(value, name):
    try:
        return _parse_iso(value)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST,
                       f"{name} must be an ISO 8601 timestamp", 400)


def iso(dt):
    return _format_iso(dt)
