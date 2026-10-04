"""Envelope, pagination, auth, and request-shape validation helpers.

All structural names (headers, envelope fields, pagination params) follow
SCAFFOLD.yaml response_envelope and PRD section 2 verbatim.
"""
import re
import secrets
import uuid
from datetime import datetime, timezone, date

from flask import request, jsonify

from errors import (
    ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE, ERR_INVALID_REQUEST,
)

ROLES = (
    'SupplyChainAdmin', 'RegulatorySpecialist', 'ManufacturingPlanner',
    'QualityManager', 'ConversionManager', 'Clinician',
    'FacilitySupplyDirector', 'GPOAnalyst',
)

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def wall_ts():
    """Server wall-clock timestamp: ISO8601 UTC with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime('%Y-%m-%dT%H:%M:%S.') + '{:03d}Z'.format(now.microsecond // 1000)


def base_resource():
    ts = wall_ts()
    return {'id': str(uuid.uuid4()), 'created_at': ts, 'updated_at': ts, 'version': 1}


# ---------------------------------------------------------------- envelope
def success(data, code=200, response_type='object', page_meta=None):
    meta = {
        'api_request_id': 'req_' + secrets.token_hex(12),
        'api_request_timestamp': wall_ts(),
    }
    if page_meta:
        meta.update(page_meta)
    payload = {'meta': meta, 'response_type': response_type, 'data': data}
    return jsonify(payload), code


def list_response(items):
    """Paginate a pre-filtered, pre-sorted list per PRD 2.2/2.3."""
    try:
        limit = int(request.args.get('limit', 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': (offset + len(page)) < total,
    }
    return success(page, 200, 'array', meta)


def error_body(error_id, message):
    return {
        'meta': {
            'api_request_id': 'req_' + secrets.token_hex(12),
            'api_request_timestamp': wall_ts(),
        },
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }


# -------------------------------------------------------------------- auth
def auth():
    """Priority 1: both headers present and role is a declared role name."""
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       'Missing X-User-ID/X-User-Role headers or undeclared role')
    return uid, role


def require_roles(role, allowed):
    """Priority 2: acting role is listed in the endpoint's roles."""
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403,
                       'Role {} is not authorized for this endpoint'.format(role))


# ------------------------------------------------------- request validation
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, 'Request body must be a JSON object')
    return data


def required(body, name):
    if name not in body or body[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Missing required field: {}'.format(name))
    return body[name]


def v_str(v, name, non_empty=False):
    if not isinstance(v, str) or (non_empty and not v):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Field {} must be a{} string'.format(name, ' non-empty' if non_empty else ''))
    return v


def v_int(v, name, minimum=None, maximum=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, 'Field {} must be an integer'.format(name))
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Field {} must be >= {}'.format(name, minimum))
    if maximum is not None and v > maximum:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Field {} must be <= {}'.format(name, maximum))
    return v


def v_bool(v, name):
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, 'Field {} must be a boolean'.format(name))
    return v


def v_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, 'Field {} must be a number'.format(name))
    return v


def v_enum(v, name, members):
    if not isinstance(v, str) or v not in members:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Field {} must be one of {}'.format(name, ', '.join(members)))
    return v


def v_date(v, name):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Field {} must be an ISO date (YYYY-MM-DD)'.format(name))
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Field {} is not a valid calendar date'.format(name))


def v_datetime(v, name):
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Field {} must be an ISO8601 datetime string'.format(name))
    try:
        dt = datetime.fromisoformat(v.replace('Z', '+00:00'))
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Field {} is not a valid ISO8601 datetime'.format(name))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def v_arr(v, name, min_len=0, max_len=None):
    if not isinstance(v, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, 'Field {} must be an array'.format(name))
    if len(v) < min_len:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Field {} must contain at least {} item(s)'.format(name, min_len))
    if max_len is not None and len(v) > max_len:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Field {} must contain at most {} item(s)'.format(name, max_len))
    return v
