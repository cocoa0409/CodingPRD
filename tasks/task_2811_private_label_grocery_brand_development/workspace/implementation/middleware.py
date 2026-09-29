"""Auth header extraction, role checking, body and query well-formedness."""
from flask import request

from db import parse_dt
from errors import fail

ROLE_PROGRAM_DIRECTOR = "ProgramDirector"
ROLE_SOURCING_MANAGER = "SourcingManager"
ROLE_QUALITY_AUDITOR = "QualityAuditor"
ROLE_REGULATORY_REVIEWER = "RegulatoryReviewer"
ROLE_PACKAGING_DESIGNER = "PackagingDesigner"
ROLE_SUPPLIER_USER = "SupplierUser"

ALL_ROLES = (
    ROLE_PROGRAM_DIRECTOR,
    ROLE_SOURCING_MANAGER,
    ROLE_QUALITY_AUDITOR,
    ROLE_REGULATORY_REVIEWER,
    ROLE_PACKAGING_DESIGNER,
    ROLE_SUPPLIER_USER,
)
KNOWN_ROLES = frozenset(ALL_ROLES)


def authenticate(allowed_roles):
    """PRD 2.9 checks 1-3: headers present, role known, role authorised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        fail("ERR_MISSING_AUTH_HEADERS")
    if role not in KNOWN_ROLES:
        fail("ERR_UNKNOWN_ROLE")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
    return user_id, role


class Field(object):
    """One declared body field."""

    def __init__(self, kind, required=False, enum=None, check=None, detail=None):
        self.kind = kind
        self.required = required
        self.enum = enum
        self.check = check
        self.detail = detail


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def _check_kind(name, kind, value):
    if kind == "string":
        if not isinstance(value, str):
            _bad(name, "must be a string")
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(name, "must be an integer")
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad(name, "must be a number")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad(name, "must be a boolean")
        return value
    if kind == "datetime":
        parsed = parse_dt(value)
        if parsed is None:
            _bad(name, "must be an ISO 8601 UTC datetime")
        return parsed
    return value


def raw_body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def validate_body(schema):
    """PRD 2.9 check 4 for the body.  Returns a dict of parsed values."""
    payload = raw_body()
    for key in payload.keys():
        if key not in schema:
            _bad(key, "is not a recognised field")
    parsed = {}
    for name, spec in schema.items():
        if name not in payload:
            if spec.required:
                _bad(name, "is required")
            parsed[name] = None
            continue
        value = payload[name]
        if value is None:
            _bad(name, "must not be null")
        value = _check_kind(name, spec.kind, value)
        if spec.enum is not None and value not in spec.enum:
            _bad(name, "must be one of %s" % ", ".join(sorted(spec.enum)))
        if spec.check is not None and not spec.check(value):
            _bad(name, spec.detail or "violates its declared constraint")
        parsed[name] = value
    parsed["_supplied"] = set(payload.keys())
    return parsed


def _parse_int_param(name, raw):
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        _bad(name, "must be an integer")
    return -int(digits) if negative else int(digits)


def validate_query(filter_spec, paginated=True):
    """PRD 2.9 check 4 for the query string.  Returns (filters, limit, offset)."""
    args = request.args
    for key in args.keys():
        if key in filter_spec:
            continue
        if paginated and key in ("limit", "offset"):
            continue
        _bad(key, "is not a recognised query parameter")
    limit, offset = 10, 0
    if paginated:
        if "limit" in args:
            limit = _parse_int_param("limit", args.get("limit"))
            if limit < 1 or limit > 100:
                _bad("limit", "must be between 1 and 100 inclusive")
        if "offset" in args:
            offset = _parse_int_param("offset", args.get("offset"))
            if offset < 0:
                _bad("offset", "must not be negative")
    filters = {}
    for name, kind in filter_spec.items():
        if name not in args:
            continue
        raw = args.get(name)
        if kind == "integer":
            filters[name] = _parse_int_param(name, raw)
        elif isinstance(kind, (set, frozenset, tuple)):
            if raw not in kind:
                _bad(name, "must be one of %s" % ", ".join(sorted(kind)))
            filters[name] = raw
        else:
            filters[name] = raw
    return filters, limit, offset
