"""Auth context, request body parsing, schema validation, pagination.

Implements PRD §2.8 tier 1 (header presence), the role-membership half of
tier 2, tier 4 (request schema: required fields, no unknown fields, enum
membership, positive amounts), and §2.3 pagination parsing.
"""
from flask import request

from constants import (
    AUTH_USER_ID_HEADER,
    AUTH_USER_ROLE_HEADER,
    DECLARED_ROLES,
    PAGE_DEFAULT_LIMIT,
    PAGE_DEFAULT_OFFSET,
    PAGE_MAX_LIMIT,
    PAGE_MIN_LIMIT,
)
from errors import err_forbidden, err_invalid_request, err_missing_context
from util import parse_datetime


class AuthContext:
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Tier 1: both headers present and the role is one of the seven declared
    (System is never callable, so it is not in DECLARED_ROLES)."""
    user_id = request.headers.get(AUTH_USER_ID_HEADER)
    role = request.headers.get(AUTH_USER_ROLE_HEADER)
    if not user_id or not role or role not in DECLARED_ROLES:
        raise err_missing_context()
    return AuthContext(user_id, role)


def require_roles(ctx, *roles):
    """Tier 2, role-membership half."""
    if ctx.role not in roles:
        raise err_forbidden()
    return ctx


def get_body():
    """Request JSON body as a dict. Missing/empty body reads as {}."""
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    data = request.get_json(silent=True, force=True)
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def spec_field(name, kind, required=False, enum=None, gt=None, ge=None, le=None):
    return {
        "name": name,
        "kind": kind,
        "required": required,
        "enum": enum,
        "gt": gt,
        "ge": ge,
        "le": le,
    }


def validate_body(body, spec):
    """Tier 4 schema validation.

    spec is a list of spec_field dicts. kinds: str, int, num, bool, dt, enum.
    Unknown fields are rejected. None (or absence) satisfies optional fields.
    """
    allowed = {f["name"] for f in spec}
    unknown = sorted(str(k) for k in body.keys() if k not in allowed)
    if unknown:
        raise err_invalid_request("Unknown field(s): " + ", ".join(unknown))
    out = {}
    for f in spec:
        name = f["name"]
        raw = body.get(name)
        if raw is None:
            if f["required"]:
                raise err_invalid_request("Missing required field: " + name)
            out[name] = None
            continue
        kind = f["kind"]
        if kind == "str":
            if not isinstance(raw, str):
                raise err_invalid_request("Field " + name + " must be a string")
            value = raw
        elif kind == "int":
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise err_invalid_request("Field " + name + " must be an integer")
            value = raw
        elif kind == "num":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise err_invalid_request("Field " + name + " must be a number")
            value = raw
        elif kind == "bool":
            if not isinstance(raw, bool):
                raise err_invalid_request("Field " + name + " must be a boolean")
            value = raw
        elif kind == "dt":
            if not isinstance(raw, str):
                raise err_invalid_request("Field " + name + " must be an ISO 8601 datetime string")
            value = parse_datetime(raw)
            if value is None:
                raise err_invalid_request("Field " + name + " must be an ISO 8601 datetime string")
        elif kind == "enum":
            choices = f["enum"] or ()
            if not isinstance(raw, str) or raw not in choices:
                raise err_invalid_request("Field " + name + " must be one of: " + ", ".join(choices))
            value = raw
        else:
            value = raw
        if f["gt"] is not None and not (value > f["gt"]):
            raise err_invalid_request("Field " + name + " must be greater than " + str(f["gt"]))
        if f["ge"] is not None and not (value >= f["ge"]):
            raise err_invalid_request("Field " + name + " must be at least " + str(f["ge"]))
        if f["le"] is not None and not (value <= f["le"]):
            raise err_invalid_request("Field " + name + " must be at most " + str(f["le"]))
        out[name] = value
    return out


def parse_pagination():
    """§2.3: limit defaults to 10 (min 1, max 100), offset defaults to 0.
    Out-of-range values clamp to the declared bounds; non-integers are 400."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("Query parameter limit must be an integer")
        limit = max(PAGE_MIN_LIMIT, min(PAGE_MAX_LIMIT, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("Query parameter offset must be an integer")
        offset = max(PAGE_DEFAULT_OFFSET, offset)
    return limit, offset


def list_page(items):
    """Sort by created_at ascending (insertion order as deterministic final
    tie-break), apply offset/limit, and return the page plus page metadata."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = parse_pagination()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
