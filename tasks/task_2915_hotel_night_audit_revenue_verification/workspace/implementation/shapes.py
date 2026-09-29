"""Request-shape validation (PRD 2.12 step 3) and pagination parsing."""
from decimal import Decimal

from flask import request

import db
from errors import ApiError

MISSING = object()


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


class Field(object):
    def __init__(self, name, kind, required=False, enum=None, default=MISSING,
                 gt=None, ge=None, le=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.default = default
        self.gt = gt
        self.ge = ge
        self.le = le


def raw_body():
    """The JSON body as an object. A non-object body is a bad request."""
    if not request.data or request.data.strip() == b"":
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def _coerce(field, value):
    kind = field.kind
    if kind == "string":
        if not isinstance(value, str):
            bad("Field %s must be a string." % field.name)
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            bad("Field %s must be a boolean." % field.name)
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            bad("Field %s must be an integer." % field.name)
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            bad("Field %s must be a number." % field.name)
        return Decimal(str(value))
    if kind == "array":
        if not isinstance(value, list):
            bad("Field %s must be an array." % field.name)
        return value
    if kind == "instant":
        if not isinstance(value, str):
            bad("Field %s must be an ISO-8601 timestamp string." % field.name)
        parsed = db.parse_instant(value)
        if parsed is None:
            bad("Field %s is not a valid ISO-8601 timestamp." % field.name)
        return parsed
    if kind == "date":
        if not isinstance(value, str):
            bad("Field %s must be a YYYY-MM-DD date string." % field.name)
        parsed = db.parse_date_only(value)
        if parsed is None:
            bad("Field %s is not a valid calendar date." % field.name)
        return value
    if kind == "month":
        if not isinstance(value, str) or db.parse_month(value) is None:
            bad("Field %s must be a YYYY-MM month string." % field.name)
        return value
    raise AssertionError("unknown kind " + kind)


def parse(fields, payload=None):
    """Validate a body against a field list. Unknown fields are ignored."""
    body = raw_body() if payload is None else payload
    out = {}
    for field in fields:
        present = field.name in body and body[field.name] is not None
        if not present:
            if field.required:
                if field.name in body:
                    bad("Field %s may not be null." % field.name)
                bad("Field %s is required." % field.name)
            if field.default is not MISSING:
                out[field.name] = field.default
            else:
                out[field.name] = None
            continue
        value = _coerce(field, body[field.name])
        if field.enum is not None and value not in field.enum:
            bad("Field %s must be one of %s." % (field.name, ", ".join(field.enum)))
        if field.gt is not None and value <= _as_num(field.gt):
            bad("Field %s must be greater than %s." % (field.name, field.gt))
        if field.ge is not None and value < _as_num(field.ge):
            bad("Field %s must be at least %s." % (field.name, field.ge))
        if field.le is not None and value > _as_num(field.le):
            bad("Field %s must be at most %s." % (field.name, field.le))
        out[field.name] = value
    out["_present"] = set(k for k in body.keys())
    return out


def _as_num(value):
    if isinstance(value, Decimal) or isinstance(value, int):
        return value
    return Decimal(str(value))


def pagination():
    """limit/offset from the query string (PRD 2.3)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit must be an integer.")
        if limit < 1:
            bad("limit may not be below 1.")
        if limit > 100:
            bad("limit may not exceed 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset must be an integer.")
        if offset < 0:
            bad("offset may not be negative.")
    return limit, offset


def page(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return [serializer(r) for r in window], meta


def q(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_bool(name):
    value = q(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter %s must be a boolean." % name)
