"""Response envelope helpers, auth, time helpers, pagination, validation helpers."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from flask import request

from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    bad_request,
    forbidden,
)


VALID_ROLES = {
    "NetworkPlanner",
    "PlatformContractManager",
    "StudioRelationshipManager",
    "PostProductionScheduler",
    "QualityAssuranceReviewer",
    "ReleaseScheduler",
    "BoxOfficeAnalyst",
    "ExhibitorFinanceUser",
    "FieldEngineer",
}


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:24]


def iso_now_wall() -> str:
    """Wall-clock timestamp for envelope meta (three fractional digits, UTC, Z suffix)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_format(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso_datetime(value: Any, field_name: str) -> datetime:
    """Parse an ISO-8601 datetime string; reject anything else."""
    if not isinstance(value, str):
        raise bad_request(ERR_INVALID_REQUEST, f"{field_name} must be an ISO 8601 datetime string")
    s = value.strip()
    if not s:
        raise bad_request(ERR_INVALID_REQUEST, f"{field_name} must not be empty")
    # Normalize trailing Z
    if s.endswith("Z"):
        s2 = s[:-1] + "+00:00"
    else:
        s2 = s
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise bad_request(ERR_INVALID_REQUEST, f"{field_name} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def success_object(data: Any, status_code: int = 200):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": iso_now_wall(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return body, status_code


def success_list(items: list, total_count: int, limit: int, offset: int):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": iso_now_wall(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return body, 200


def error_body(error_id: str, message: str):
    return {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": iso_now_wall(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def require_auth():
    """Validate X-User-ID and X-User-Role headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise bad_request(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required",
        )
    if role not in VALID_ROLES:
        raise bad_request(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            f"Unrecognized role: {role}",
        )
    return user_id, role


def require_role(*allowed: str):
    user_id, role = require_auth()
    if role not in allowed:
        raise forbidden(f"Role {role} is not permitted to perform this operation")
    return user_id, role


# ---------------------------------------------------------------------------
# Body / field validation
# ---------------------------------------------------------------------------

def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        # Allow empty body on POST transitions that take no input
        if request.content_length in (None, 0):
            return {}
        raise bad_request(ERR_INVALID_REQUEST, "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise bad_request(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def req_str(body: dict, field: str) -> str:
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise bad_request(ERR_INVALID_REQUEST, f"{field} is required and must be a non-empty string")
    return v


def opt_str(body: dict, field: str) -> Optional[str]:
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise bad_request(ERR_INVALID_REQUEST, f"{field} must be a string")
    return v


def req_int(body: dict, field: str) -> int:
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request(ERR_INVALID_REQUEST, f"{field} is required and must be an integer")
    return v


def req_number(body: dict, field: str):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise bad_request(ERR_INVALID_REQUEST, f"{field} is required and must be a number")
    return v


def req_bool(body: dict, field: str) -> bool:
    v = body.get(field)
    if not isinstance(v, bool):
        raise bad_request(ERR_INVALID_REQUEST, f"{field} is required and must be a boolean")
    return v


def opt_bool(body: dict, field: str, default: bool = False) -> bool:
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise bad_request(ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return v


def req_list(body: dict, field: str) -> list:
    v = body.get(field)
    if not isinstance(v, list):
        raise bad_request(ERR_INVALID_REQUEST, f"{field} is required and must be an array")
    return v


def req_obj(body: dict, field: str) -> dict:
    v = body.get(field)
    if not isinstance(v, dict):
        raise bad_request(ERR_INVALID_REQUEST, f"{field} is required and must be an object")
    return v


def req_enum(body: dict, field: str, allowed: Iterable[str]) -> str:
    v = body.get(field)
    if not isinstance(v, str) or v not in set(allowed):
        raise bad_request(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(set(allowed))}")
    return v


def opt_enum(body: dict, field: str, allowed: Iterable[str], default: Optional[str]) -> Optional[str]:
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in set(allowed):
        raise bad_request(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(set(allowed))}")
    return v


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination():
    """Return (limit, offset) using scaffold defaults: limit default 10, min 1, max 100."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            raise bad_request(ERR_INVALID_REQUEST, "limit must be >= 1")
        if limit > 100:
            raise bad_request(ERR_INVALID_REQUEST, "limit must be <= 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise bad_request(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int):
    total = len(items)
    page = items[offset: offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Resource helpers
# ---------------------------------------------------------------------------

def touch(entity: dict):
    """Refresh updated_at and increment version."""
    entity["updated_at"] = iso_now_wall()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity: dict, with_version: bool = True):
    now = iso_now_wall()
    entity["id"] = new_id()
    entity["created_at"] = now
    if with_version:
        entity["updated_at"] = now
        entity["version"] = 1


def sort_by_created(items: list) -> list:
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
