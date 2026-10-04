"""Response envelope helpers — exact field names from SCAFFOLD response_envelope."""
import random
import string

from flask import jsonify

import db
from errors import ApiError


def _request_id():
    return 'req_' + ''.join(random.choices(string.ascii_letters + string.digits, k=16))


def _meta():
    return {
        'api_request_id': _request_id(),
        'api_request_timestamp': db.wall_now_iso(),
    }


def ok(data, status=200):
    body = {'meta': _meta(), 'response_type': 'object', 'data': data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, total_count, limit, offset, status=200):
    m = _meta()
    m['limit'] = limit
    m['offset'] = offset
    m['total_count'] = total_count
    m['has_more'] = (offset + len(items)) < total_count
    body = {'meta': m, 'response_type': 'array', 'data': items}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def err(error_id, status, message):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def api_error(e):
    return err(e.error_id, e.http_status, e.message)


def parse_pagination(args):
    """limit: default 10, min 1, max 100; offset: default 0, min 0."""
    raw_limit = args.get('limit')
    raw_offset = args.get('offset')
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'limit must be an integer')
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'offset must be an integer')
    if limit < 1 or limit > 100:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'limit must be between 1 and 100')
    if offset < 0:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'offset must be >= 0')
    return limit, offset
