"""Auth header extraction, role checking, and request-shape validation."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

from flask import request

from errors import ApiError, unauthenticated, unauthorized, invalid_request, not_found


ROLES = {
    "Admin",
    "SourcingBuyer",
    "SafetyOfficer",
    "PricingLead",
    "AllocationManager",
    "StoreManager",
    "ClubMember",
    "Anonymous",
}


def current_identity() -> Tuple[Optional[str], Optional[str]]:
    """Returns (role, user_id). Raises ERR_UNAUTHENTICATED on violation."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise unauthenticated("Missing or unknown X-User-Role")
    if role != "Anonymous" and (user_id is None or user_id == ""):
        raise unauthenticated("X-User-ID is required for role " + role)
    return role, user_id


def require_roles(allowed: Iterable[str]) -> Tuple[str, Optional[str]]:
    role, user_id = current_identity()
    if role not in set(allowed):
        raise unauthorized("Role %s is not permitted for this endpoint" % role)
    return role, user_id


def get_json_body() -> dict:
    if not request.is_json:
        raise invalid_request("Request body must be JSON")
    body = request.get_json(silent=True)
    if body is None:
        raise invalid_request("Request body must be valid JSON")
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def check_unknown_fields(body: dict, allowed: List[str]) -> None:
    unknown = [k for k in body.keys() if k not in allowed]
    if unknown:
        raise invalid_request("Unknown fields: %s" % ", ".join(sorted(unknown)))


def require_fields(body: dict, fields: List[str]) -> None:
    for f in fields:
        if f not in body or body[f] is None:
            raise invalid_request("Missing required field: %s" % f)


def check_enum(body: dict, field: str, allowed: List[Any]) -> None:
    if field in body and body[field] is not None and body[field] not in allowed:
        raise invalid_request("Invalid value for %s" % field)


def check_int_ge(body: dict, field: str, minimum: int) -> None:
    if field in body and body[field] is not None:
        v = body[field]
        if not isinstance(v, int) or isinstance(v, bool) or v < minimum:
            raise invalid_request("%s must be an integer >= %d" % (field, minimum))


def check_int_range(body: dict, field: str, lo: int, hi: int) -> None:
    if field in body and body[field] is not None:
        v = body[field]
        if not isinstance(v, int) or isinstance(v, bool) or v < lo or v > hi:
            raise invalid_request("%s must be an integer in [%d, %d]" % (field, lo, hi))


def check_string(body: dict, field: str) -> None:
    if field in body and body[field] is not None and not isinstance(body[field], str):
        raise invalid_request("%s must be a string" % field)


def check_bool(body: dict, field: str) -> None:
    if field in body and body[field] is not None and not isinstance(body[field], bool):
        raise invalid_request("%s must be a boolean" % field)


def parse_pagination() -> Tuple[int, int]:
    """Parse limit/offset query params with defaults limit=10, offset=0, bounds 1..100."""
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        raise invalid_request("limit must be an integer")
    try:
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise invalid_request("offset must be >= 0")
    return limit, offset
