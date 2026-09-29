"""Authentication, role gating, body parsing and pagination.

Ranks 1, 2 and 5 of the failure ladder (PRD section 2.8).
"""

import json
from decimal import Decimal

from flask import request

from errors import ApiError

ROLES = (
    "LabelAdmin",
    "DistributionPartner",
    "RoyaltyAnalyst",
    "BusinessAffairs",
    "Artist",
)

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    if value.strip() == "":
        return None
    return value.strip()


def authenticate(allowed_roles):
    """Rank 1 then rank 2: identity before role."""
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return Caller(user_id, role)


def parse_body():
    """Rank 5 entry point.  Decimal-preserving parse so that a JSON literal
    such as 0.1500 keeps its four decimal places (PRD section 2.6)."""
    raw = request.get_data(cache=False, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 and is non-negative."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        text = raw_limit.strip()
        if text == "" or not _is_int(text):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        limit = int(text)
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        text = raw_offset.strip()
        if text == "" or not _is_int(text):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        offset = int(text)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be non-negative.")
    return limit, offset


def _is_int(text):
    body = text[1:] if text[:1] in ("+", "-") else text
    return body.isdigit() and body != ""


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total
