from flask import jsonify, request
from store import new_request_id, iso_now, ApiError

ROLES = {'PlatformBillingOperator', 'OrgAdmin', 'FinanceAnalyst', 'LinkedAccountManager'}


def meta_block():
    return {
        'api_request_id': new_request_id(),
        'api_request_timestamp': iso_now(),
    }


def success(data, status=200, response_type='object', page=None):
    body = {
        'meta': meta_block(),
        'response_type': response_type,
        'data': data,
    }
    if page is not None:
        body['meta']['limit'] = page['limit']
        body['meta']['offset'] = page['offset']
        body['meta']['total_count'] = page['total_count']
        body['meta']['has_more'] = page['has_more']
    return jsonify(body), status


def err_response(e):
    body = {
        'meta': meta_block(),
        'response_type': 'error',
        'data': {'error_id': e.error_id, 'message': e.message},
    }
    return jsonify(body), e.http_status


def parse_pagination():
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError('ERR_INVALID_REQUEST', 400, 'invalid limit')
        if limit < 1 or limit > 100:
            raise ApiError('ERR_INVALID_REQUEST', 400, 'limit out of range')
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError('ERR_INVALID_REQUEST', 400, 'invalid offset')
        if offset < 0:
            raise ApiError('ERR_INVALID_REQUEST', 400, 'offset out of range')
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    window = items[offset:offset + limit]
    has_more = (offset + len(window)) < total
    return window, {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': has_more,
    }


def list_success(items, limit, offset):
    window, page = paginate(items, limit, offset)
    return success(window, status=200, response_type='array', page=page)
