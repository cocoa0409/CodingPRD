"""Auth header handling, request-body validation and pagination (PRD 2.1-2.3, 2.9)."""

import json

from flask import request

from db import DB
from errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_MISSING_AUTH_HEADERS,
    ApiError,
)

DECLARED_ROLES = (
    "Member",
    "Underwriter",
    "BenefitsAdmin",
    "ComplianceOfficer",
    "PlatformAdmin",
    "Anonymous",
)

ENTITY_BACKED_ROLES = ("Member",)


def auth(roles):
    """Validation rungs 1 and 2: headers present, role declared and permitted."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError(ERR_MISSING_AUTH_HEADERS)
    if not role or not str(role).strip():
        raise ApiError(ERR_MISSING_AUTH_HEADERS)
    if role not in DECLARED_ROLES or role not in roles:
        raise ApiError(ERR_FORBIDDEN_ROLE)
    return str(user_id), role


def require_owner(user_id, member_id):
    """Ownership guard: the acting identity must be the owning member."""
    if user_id != member_id:
        raise ApiError(ERR_FORBIDDEN_ROLE)


def raw_body():
    """Parse the JSON body; no body at all is treated as an empty body, because
    several declared endpoints carry no input fields at all."""
    body = request.get_json(silent=True)
    if body is None and request.data:
        body = _first_json_object(request.get_data(cache=True))
    if body is None:
        if request.data:
            raise ApiError(ERR_INVALID_REQUEST)
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST)
    return body


def _first_json_object(raw):
    """Recover the first JSON object from a payload, tolerating trailing noise."""
    try:
        text = raw.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return None
    decoder = json.JSONDecoder()
    index = 0
    length = len(text)
    while index < length:
        while index < length and text[index] in " \t\r\n":
            index += 1
        if index >= length:
            return None
        try:
            value, end = decoder.raw_decode(text, index)
        except ValueError:
            return None
        if isinstance(value, dict):
            return value
        index = end
    return None


def reject_unknown(body, allowed):
    for key in body.keys():
        if key not in allowed:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "Unknown field %r in the request body." % (key,),
            )


def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise ApiError(ERR_INVALID_REQUEST)


def as_string(body, name, required=True, default=None, allow_empty=False):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field %r is required." % (name,))
        return default
    value = body[name]
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field %r must be a string." % (name,))
    if not allow_empty and value == "":
        raise ApiError(ERR_INVALID_REQUEST, "Field %r must be non-empty." % (name,))
    return value


def as_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field %r is required." % (name,))
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST, "Field %r must be an integer." % (name,))
    if minimum is not None and value < minimum:
        raise ApiError(ERR_INVALID_REQUEST, "Field %r is below its minimum." % (name,))
    if maximum is not None and value > maximum:
        raise ApiError(ERR_INVALID_REQUEST, "Field %r is above its maximum." % (name,))
    return value


def as_bool(body, name, required=False, default=False):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST)
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST)
    return value


def as_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field %r is required." % (name,))
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field %r is outside its declared enumeration." % (name,),
        )
    return value


def as_timestamp(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST)
        return default
    value = body[name]
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST)
    from timeutil import parse_ts

    if parse_ts(value) is None:
        raise ApiError(ERR_INVALID_REQUEST)
    return value


def paginate(items):
    """Sort is the caller's responsibility; here we only slice."""
    raw_limit = request.args.get("limit")
    limit = 10
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST)
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST)
    raw_offset = request.args.get("offset")
    offset = 0
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST)
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST)
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def query_filter(items, mapping):
    """Apply equality filters whose query parameters are present."""
    out = items
    for param, field in mapping.items():
        value = request.args.get(param)
        if value is not None and value != "":
            out = [row for row in out if str(row.get(field)) == value]
    return out


def request_version(name):
    """Read an optional concurrency-guard version from the request body."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None
    value = body.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST)
    return value


def new_record(**fields):
    from db import stamp_create

    record = {"id": DB.next_id()}
    record.update(fields)
    stamp_create(record, DB.clock())
    return record