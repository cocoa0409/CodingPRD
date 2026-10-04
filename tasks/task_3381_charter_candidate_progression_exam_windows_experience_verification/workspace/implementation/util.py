"""HTTP-layer helpers: response envelope, auth context, payload validation,
pagination."""
import uuid
from flask import request, jsonify
from store import wall_iso, parse_dt, parse_date
from errors import fail

ROLES = ('Candidate', 'ProgramAdmin', 'Proctor', 'ExperienceReviewer',
         'ReferenceProvider', 'ConductInvestigator', 'ConductAdjudicator')


def _meta(pagination=None):
    m = {'api_request_id': 'req_' + uuid.uuid4().hex[:24],
         'api_request_timestamp': wall_iso()}
    if pagination:
        m.update(pagination)
    return m


def ok(data, code=200):
    return jsonify({'meta': _meta(), 'response_type': 'object', 'data': data}), code


def ok_list(items, total, limit, offset):
    pg = {'limit': limit, 'offset': offset, 'total_count': total,
          'has_more': offset + len(items) < total}
    return jsonify({'meta': _meta(pg), 'response_type': 'array', 'data': items}), 200


def error_response(err):
    body = {'meta': _meta(), 'response_type': 'error',
            'data': {'error_id': err.error_id, 'message': err.message}}
    return jsonify(body), err.status


def ctx(allowed_roles):
    """Validation pipeline stages 1-2: header presence/role validity, then
    role authorization for the endpoint."""
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        fail('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER')
    if role not in allowed_roles:
        fail('ERR_FORBIDDEN_ROLE')
    return uid, role


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail('ERR_INVALID_REQUEST')
    return data


def get_path(collection, key, error_id):
    ent = collection.get(key)
    if ent is None:
        fail(error_id)
    return ent


def check_unknown(body, allowed):
    for k in body:
        if k not in allowed:
            fail('ERR_INVALID_REQUEST')


def req_field(body, name):
    if name not in body or body[name] is None:
        fail('ERR_INVALID_REQUEST')
    return body[name]


def opt_field(body, name):
    v = body.get(name)
    return v if v is not None else None


def as_str(v):
    if not isinstance(v, str):
        fail('ERR_INVALID_REQUEST')
    return v


def as_int(v):
    if isinstance(v, bool) or not isinstance(v, int):
        fail('ERR_INVALID_REQUEST')
    return v


def as_bool(v):
    if not isinstance(v, bool):
        fail('ERR_INVALID_REQUEST')
    return v


def as_num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail('ERR_INVALID_REQUEST')
    return v


def as_enum(v, values):
    if not isinstance(v, str) or v not in values:
        fail('ERR_INVALID_REQUEST')
    return v


def as_date(v):
    try:
        return parse_date(v)
    except Exception:
        fail('ERR_INVALID_REQUEST')


def as_dt(v):
    try:
        return parse_dt(v)
    except Exception:
        fail('ERR_INVALID_REQUEST')


def sorted_by_creation(items):
    return sorted(items, key=lambda e: (e['created_at'], e['_seq']))


def list_response(items, serializer):
    """PRD 2.3: limit default 10, min 1, max 100; offset default 0; sorted by
    created_at ascending; pagination fields live in meta."""
    limit = 10
    offset = 0
    q = request.args
    if 'limit' in q:
        try:
            limit = int(q['limit'])
        except (TypeError, ValueError):
            fail('ERR_INVALID_REQUEST')
        if limit < 1 or limit > 100:
            fail('ERR_INVALID_REQUEST')
    if 'offset' in q:
        try:
            offset = int(q['offset'])
        except (TypeError, ValueError):
            fail('ERR_INVALID_REQUEST')
        if offset < 0:
            fail('ERR_INVALID_REQUEST')
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serializer(x) for x in page], total, limit, offset)
