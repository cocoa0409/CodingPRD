"""Shared route helpers: entity creation, getters, serialization, validation primitives."""
import uuid
from datetime import date

from db import db, _parse_dt
from errors import fail
from common import now_iso, touch, refresh_consent


def new_entity(extra=None):
    ts = now_iso()
    e = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    if extra:
        e.update(extra)
    return e


def get_or_404(table, entity_id, label="resource"):
    ent = table.get(entity_id)
    if ent is None:
        fail("ERR_NOT_FOUND", f"{label} not found")
    return ent


def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v == "":
        fail("ERR_INVALID_REQUEST", f"{field} is required")
    return v


def opt_str(data, field):
    v = data.get(field)
    if v is not None and not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", f"{field} must be a string")
    return v


def req_int(data, field):
    v = data.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", f"{field} is required and must be an integer")
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", f"{field} is required and must be a boolean")
    return v


def req_num(data, field):
    v = data.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        fail("ERR_INVALID_REQUEST", f"{field} is required and must be a number")
    return v


def req_enum(data, field, values):
    v = data.get(field)
    if v not in values:
        fail("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(values)}")
    return v


def opt_enum(data, field, values):
    v = data.get(field)
    if v is not None and v not in values:
        fail("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(values)}")
    return v


def parse_date(s, field):
    try:
        return date.fromisoformat(str(s))
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 date")


def member_view(m):
    return m


def consent_view(c):
    refresh_consent(c)
    return c
