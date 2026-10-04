"""Shared helpers: serialization, validation, common fields."""
from __future__ import annotations

import uuid

import db
from errors import invalid_request


def new_id() -> str:
    return str(uuid.uuid4())


def stamp_new(obj: dict, common: bool = True) -> None:
    """Add id/created_at (+updated_at/version for common-field resources)."""
    now_iso = db.fmt_clock(db.now())
    obj["id"] = new_id()
    obj["created_at"] = now_iso
    if common:
        obj["updated_at"] = now_iso
        obj["version"] = 1


def touch(obj: dict) -> None:
    obj["updated_at"] = db.fmt_clock(db.now())
    obj["version"] = obj.get("version", 1) + 1


def body() -> dict:
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("request body must be a JSON object")
    return data


def require_str(data: dict, field: str) -> str:
    v = data.get(field)
    if not isinstance(v, str) or not v:
        raise invalid_request(f"missing or ill-typed field: {field}")
    return v


def require_int(data: dict, field: str, minimum: int | None = None,
                maximum: int | None = None) -> int:
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"missing or ill-typed field: {field}")
    if minimum is not None and v < minimum:
        raise invalid_request(f"field below minimum: {field}")
    if maximum is not None and v > maximum:
        raise invalid_request(f"field above maximum: {field}")
    return v


def require_enum(data: dict, field: str, values: set) -> str:
    v = data.get(field)
    if not isinstance(v, str) or v not in values:
        raise invalid_request(f"field {field} must be one of {sorted(values)}")
    return v


def require_number(data: dict, field: str, lo: float | None = None,
                   hi: float | None = None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"missing or ill-typed field: {field}")
    if lo is not None and v < lo:
        raise invalid_request(f"field below minimum: {field}")
    if hi is not None and v > hi:
        raise invalid_request(f"field above maximum: {field}")
    return v


def require_datetime(data: dict, field: str):
    v = data.get(field)
    if not isinstance(v, str):
        raise invalid_request(f"missing or ill-typed field: {field}")
    try:
        return db.parse_iso(v)
    except Exception:
        raise invalid_request(f"invalid datetime: {field}")


def sort_by_created(items: list) -> list:
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))


# --- serializers (return copies so callers can't mutate the store) ---

def org_view(org: dict, preview: bool = False) -> dict:
    out = dict(org)
    if preview:
        from services.domain import preview_tier
        out["tier"] = preview_tier(org)
    return out


def simple_view(obj: dict) -> dict:
    return dict(obj)
