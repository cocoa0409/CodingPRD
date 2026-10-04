"""Request-level validation helpers: auth gates, body parsing, typed fields,
score-grid checks, pagination (PRD sections 2.1, 2.3, 2.6, 2.8)."""
from decimal import Decimal

from flask import request

import constants as C
import errors as E
from store import parse_iso


def auth_headers():
    """Gate 1: X-User-ID and X-User-Role present and well-formed."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip():
        E.fail(E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
               "X-User-ID header is missing or malformed")
    if role is None or not str(role).strip():
        E.fail(E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
               "X-User-Role header is missing or malformed")
    return str(uid).strip(), str(role).strip()


def require_role(role, allowed):
    """Gate 2: the presented role must be in the endpoint's role list."""
    if role not in allowed:
        E.fail(E.ERR_INSUFFICIENT_PERMISSIONS, 403,
               "Role %s is not authorized for this endpoint" % role)


def body():
    """Parsed JSON object body, or {} when absent/not an object."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def req_field(data, name):
    if name not in data or data[name] is None:
        E.fail(E.ERR_INVALID_REQUEST, 400, "Missing required field: %s" % name)
    return data[name]


def parse_dt_field(value, name):
    try:
        return parse_iso(value)
    except Exception:
        E.fail(E.ERR_INVALID_REQUEST, 400, "%s must be an ISO 8601 datetime" % name)


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        E.fail(E.ERR_INVALID_REQUEST, 400, "%s must be a number" % name)
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        E.fail(E.ERR_INVALID_REQUEST, 400, "%s must be an integer" % name)
    return value


def dec(value):
    """JSON number -> Decimal via str() so binary float noise never enters."""
    return Decimal(str(value))


def validate_score_value(value, name="score"):
    """PRD 2.6: on the 0.25 grid within [0.00, 4.00] else ERR_SCORE_INVALID."""
    raw = as_number(value, name)
    d = dec(raw)
    if not d.is_finite():
        E.fail(E.ERR_SCORE_INVALID, 422, "%s must be a finite number" % name)
    if d < C.SCORE_MIN or d > C.SCORE_MAX:
        E.fail(E.ERR_SCORE_INVALID, 422,
               "%s must be within [0.00, 4.00]" % name)
    steps = d / C.SCORE_STEP
    if steps != steps.to_integral_value():
        E.fail(E.ERR_SCORE_INVALID, 422,
               "%s must be an exact multiple of 0.25" % name)
    return d


def pagination_params():
    """PRD 2.3: limit default 10, min 1, max 100; offset default 0."""
    limit_raw = request.args.get("limit", C.PAGE_LIMIT_DEFAULT)
    offset_raw = request.args.get("offset", C.PAGE_OFFSET_DEFAULT)
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        E.fail(E.ERR_INVALID_REQUEST, 400, "limit must be an integer")
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        E.fail(E.ERR_INVALID_REQUEST, 400, "offset must be an integer")
    if limit < C.PAGE_LIMIT_MIN:
        limit = C.PAGE_LIMIT_MIN
    if limit > C.PAGE_LIMIT_MAX:
        limit = C.PAGE_LIMIT_MAX
    if offset < 0:
        offset = C.PAGE_OFFSET_DEFAULT
    return limit, offset


def paginate(items, limit, offset):
    """Sort by creation order (created_at asc; _seq breaks ties) and slice."""
    ordered = sorted(items, key=lambda x: (x.get("_seq", 0),))
    total = len(ordered)
    return ordered[offset:offset + limit], total
