"""Shared helpers: ids, timestamps, pagination, serialization, auth."""
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import request

from errors import unauthenticated, unauthorized, validation, ERR_NOT_FOUND, ApiError
from store import now_iso

ROLES = [
    "PlatformAdmin",
    "BrandManager",
    "CampaignManager",
    "CarrierReviewer",
    "NumberProvisioner",
    "ComplianceOfficer",
    "DeliverabilityAnalyst",
    "SystemDriver",
]


def new_id():
    return str(uuid.uuid4())


def parse_iso(value):
    """Parse an ISO 8601 timestamp (accepts trailing Z). Returns aware datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return "%s.%03dZ" % (base, dt.microsecond // 1000)


def now_dt():
    return parse_iso(now_iso())


def require_auth(allowed_roles):
    """Validate X-User-ID / X-User-Role and endpoint role permission."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise unauthenticated()
    if role not in allowed_roles:
        raise unauthorized()
    return role


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise validation("Request body must be a JSON object")
    return body


def pagination_params():
    """Parse limit/offset query params with PRD defaults; 400 on invalid."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise validation("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise validation("offset must be an integer")
    if limit < 1 or limit > 100:
        raise validation("limit must be between 1 and 100")
    if offset < 0:
        raise validation("offset must be non-negative")
    return limit, offset


def day_of(iso_str):
    """Return YYYY-MM-DD of an ISO timestamp."""
    return parse_iso(iso_str).strftime("%Y-%m-%d")


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise validation("Missing required field: %s" % f)


def require_nonempty(body, fields):
    for f in fields:
        v = body.get(f)
        if not isinstance(v, str) or v.strip() == "":
            raise validation("Field must be a non-empty string: %s" % f)


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise validation("Field %s must be one of %s" % (field, ", ".join(allowed)))
    return v


def sort_by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))


def touch(entity):
    """Refresh updated_at and bump version on entities that carry them."""
    if "version" in entity:
        entity["version"] += 1
    if "updated_at" in entity:
        entity["updated_at"] = now_iso()


def find_or_404(collection, entity_id, account_id=None):
    ent = collection.get(entity_id)
    if ent is None:
        raise ApiError(ERR_NOT_FOUND, "Resource not found", 404)
    if account_id is not None and ent.get("account_id") != account_id:
        raise ApiError(ERR_NOT_FOUND, "Resource not found under account", 404)
    return ent
