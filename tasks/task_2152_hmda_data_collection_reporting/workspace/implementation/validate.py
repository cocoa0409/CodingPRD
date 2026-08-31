"""Ladder step 5: body shape and pagination bounds (PRD 2.3 / 2.9)."""

import re
from datetime import datetime, timezone

from flask import request

import constants as C
import store
from errors import fail

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO 8601 datetime string.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    if not _ISO_RE.match(value.strip()):
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def json_body():
    """Return the request body as a dict; anything that is not a JSON object is malformed."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class Field(object):
    def __init__(self, name, kind, required=False, enum=None, minimum=None,
                 maximum=None, member_enum=None, nullable=True):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.member_enum = member_enum
        self.nullable = nullable


def check(body, fields):
    """Validate the body against the field specs; returns the coerced values.

    Datetime fields come back as aware UTC datetimes.  Absent fields are simply
    missing from the returned dict, so callers can distinguish absent from null.
    """
    out = {}
    for spec in fields:
        if spec.name not in body:
            if spec.required:
                fail("ERR_INVALID_REQUEST", "Missing required field '%s'." % spec.name)
            continue
        value = body[spec.name]
        if value is None:
            if spec.required or not spec.nullable:
                fail("ERR_INVALID_REQUEST", "Field '%s' may not be null." % spec.name)
            out[spec.name] = None
            continue
        out[spec.name] = _coerce(spec, value)
    return out


def _coerce(spec, value):
    kind = spec.kind
    if kind == "string":
        if not isinstance(value, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % spec.name)
        if spec.enum is not None and value not in spec.enum:
            fail("ERR_INVALID_REQUEST", "Field '%s' has an unknown value." % spec.name)
        return value
    if kind == "integer":
        if not _is_int(value):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % spec.name)
        if spec.minimum is not None and value < spec.minimum:
            fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % spec.name)
        if spec.maximum is not None and value > spec.maximum:
            fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % spec.name)
        return value
    if kind == "number":
        if not _is_number(value):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % spec.name)
        if spec.minimum is not None and value < spec.minimum:
            fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % spec.name)
        if spec.maximum is not None and value > spec.maximum:
            fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % spec.name)
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % spec.name)
        return value
    if kind == "array":
        if not isinstance(value, list):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % spec.name)
        if spec.member_enum is not None:
            for member in value:
                if not isinstance(member, str) or member not in spec.member_enum:
                    fail("ERR_INVALID_REQUEST",
                         "Field '%s' carries an unknown member." % spec.name)
        return value
    if kind == "datetime":
        parsed = parse_iso(value)
        if parsed is None:
            fail("ERR_INVALID_REQUEST", "Field '%s' is not a valid ISO 8601 datetime." % spec.name)
        return parsed
    raise AssertionError("unknown kind %s" % kind)


# ---------------------------------------------------------------------------
# Pagination and filters
# ---------------------------------------------------------------------------

def pagination():
    """limit/offset per PRD 2.3; out-of-bounds values are ERR_INVALID_REQUEST."""
    limit = C.PAGINATION_DEFAULT_LIMIT
    offset = C.PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if str(limit) != raw_limit.strip():
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < C.PAGINATION_MIN_LIMIT or limit > C.PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_REQUEST", "limit is outside the permitted bounds.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if str(offset) != raw_offset.strip():
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def enum_filter(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Unknown value for filter '%s'." % name)
    return value


def bool_filter(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Filter '%s' must be a boolean." % name)


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return [serializer(row) for row in window], total


def lookup(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        fail(error_id)
    return row
