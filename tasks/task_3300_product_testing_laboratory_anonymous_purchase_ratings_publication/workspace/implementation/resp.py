from flask import jsonify
from store import req_id, wall_iso


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id, message, http_status):
    raise ApiError(error_id, message, http_status)


def ok(data, status=200, pagination=None):
    meta = {
        'api_request_id': req_id(),
        'api_request_timestamp': wall_iso(),
    }
    if pagination:
        meta['limit'] = pagination['limit']
        meta['offset'] = pagination['offset']
        meta['total_count'] = pagination['total_count']
        meta['has_more'] = pagination['has_more']
    body = {
        'meta': meta,
        'response_type': 'array' if isinstance(data, list) else 'object',
        'data': data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message, http_status):
    body = {
        'meta': {
            'api_request_id': req_id(),
            'api_request_timestamp': wall_iso(),
        },
        'response_type': 'error',
        'data': {
            'error_id': error_id,
            'message': message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def parse_pagination(args):
    raw_limit = args.get('limit')
    raw_offset = args.get('offset')
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        err('ERR_INVALID_REQUEST', 'limit must be an integer', 400)
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        err('ERR_INVALID_REQUEST', 'offset must be an integer', 400)
    if limit < 1 or limit > 100:
        err('ERR_INVALID_REQUEST', 'limit must be between 1 and 100', 400)
    if offset < 0:
        err('ERR_INVALID_REQUEST', 'offset must be >= 0', 400)
    return limit, offset


def list_page(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': (offset + limit) < total,
    }
    return page, pagination
