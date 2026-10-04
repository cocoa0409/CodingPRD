"""Request-shape gate, authentication, authorization and listing helpers.

Validation structure follows the ladder in SCAFFOLD §1.4 as described by
PRD §2.11: the request-shape gate runs before everything; authentication is
rung 1, authorization rung 2.
"""

from flask import request

from db import ROLES, DB
from errors import (
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    fail,
)

SYSTEM_FIELD_NAMES = ("id", "created_at", "updated_at", "version")

_AUTH_HEADER_HINTS = ("x-user-id", "x-user-role")


def actor():
    """Authenticate the caller; returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        fail(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required.")
    uid = uid.strip()
    role = role.strip()
    if not uid or role not in ROLES:
        fail(ERR_UNAUTHENTICATED, "The supplied role is not a recognised role.")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        fail(ERR_UNAUTHORIZED, "Role %s is not authorised for this operation." % role)


def payload():
    """Strict body gate: unknown keys, system fields and malformed JSON fail."""
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data(cache=True, as_text=True)
        if raw and raw.strip() and raw.strip() != "null":
            fail(ERR_INVALID_REQUEST, "Request body is not a valid JSON object.")
        data = {}
    if not isinstance(data, dict):
        fail(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    for key in data:
        if key in SYSTEM_FIELD_NAMES:
            fail(
                ERR_INVALID_REQUEST,
                "Field '%s' is server-managed and may not be supplied." % key,
            )
        if key.lower().startswith(_AUTH_HEADER_HINTS):
            fail(ERR_INVALID_REQUEST, "Field '%s' is not a recognised input." % key)
    return data


def body_fields(spec, data, required=True):
    """Extract the declared fields, rejecting unknown keys.

    `spec` is a list of (name, kind, required) where kind is one of
    "string", "int", "number", "array", "datetime", "enum".
    """
    allowed = {name for name, _kind, _req in spec}
    for key in data:
        if key in allowed:
            continue
        if key in (
            "expected_facility_version",
            "expected_staff_version",
            "expected_ehr_implementation_version",
        ):
            # PRD §2.7: only the three named write operations carry a
            # version field; a version supplied anywhere else is refused.
            fail(
                ERR_INVALID_REQUEST,
                "Field '%s' is not accepted by this endpoint." % key,
            )
        fail(ERR_INVALID_REQUEST, "Field '%s' is not a recognised input." % key)

    out = {}
    for name, kind, req in spec:
        if name not in data:
            if req and required:
                fail(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
            out[name] = None
            continue
        out[name] = _coerce(name, kind, data[name])
    return out


def _coerce(name, kind, value):
    if kind == "array":
        if not isinstance(value, list):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be an array." % name)
        for item in value:
            if not isinstance(item, str):
                fail(ERR_INVALID_REQUEST, "Field '%s' must be an array of strings." % name)
        return list(value)
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be a number." % name)
        return value
    if kind == "datetime":
        if not isinstance(value, str):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 string." % name)
        return value
    if kind == "enum":
        if not isinstance(value, str):
            fail(ERR_INVALID_REQUEST, "Field '%s' must be a string." % name)
        return value
    if not isinstance(value, str):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a string." % name)
    return value


def enum_member(name, value, allowed):
    if value not in allowed:
        fail(
            ERR_INVALID_REQUEST,
            "Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))),
        )
    return value


def positive_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)
    if value < 0:
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a non-negative integer." % name)
    return value


# --------------------------------------------------------------------------
# Pagination & filtering
# --------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail(ERR_INVALID_REQUEST, "Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail(ERR_INVALID_REQUEST, "Query parameter 'offset' must not be negative.")
    return limit, offset


def filter_args(names):
    """Return {name: value} for those query parameters present in the request."""
    out = {}
    for name in names:
        if name in request.args and request.args.get(name) != "":
            out[name] = request.args.get(name)
    return out


def collection(rows, limit, offset):
    rows = sorted(rows, key=lambda r: DB.creation_sequence.get(r["id"], 0))
    total = len(rows)
    window = rows[offset: offset + limit]
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, page