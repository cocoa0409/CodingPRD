"""Response envelope (scaffold section 1.0 / PRD 2.2) and the error catalog."""
import uuid
from flask import jsonify
import store

# Error catalog (scaffold section 1.6 / PRD section 5) -- id -> http status
ERRORS = {
    'ERR_UNAUTHENTICATED': 401,
    'ERR_UNAUTHORIZED_ROLE': 403,
    'ERR_INVALID_REQUEST': 400,
    'ERR_NOT_FOUND': 404,
    'ERR_INVALID_STATE': 409,
    'ERR_STALE_VERSION': 412,
    'ERR_NESTING_BLACKOUT': 422,
    'ERR_POSTURE_CLOSED': 422,
    'ERR_DETERMINATION_NOT_FINAL': 422,
    'ERR_USE_INCOMPATIBLE': 422,
    'ERR_VOLUNTEER_NOT_CLEARED': 422,
    'ERR_USE_TYPE_MISMATCH': 422,
    'ERR_DUPLICATE_BID': 422,
    'ERR_DUPLICATE_ASSIGNMENT': 422,
    'ERR_PROGRAM_CAPACITY_EXCEEDED': 422,
    'ERR_COMMERCIAL_CAPACITY_EXCEEDED': 422,
    'ERR_UNRESOLVED_COMMENTS': 422,
    'ERR_DATE_RANGE_INVALID': 422,
    'ERR_WINDOW_IN_PAST': 422,
    'ERR_TREATMENT_WINDOW_OVERLAP': 422,
    'ERR_PAYMENT_AMOUNT_MISMATCH': 402,
    'ERR_REFUND_EXCEEDS_PAID': 422,
    'ERR_OUTSTANDING_BALANCE': 422,
    'ERR_OVERPAYMENT': 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=''):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = ERRORS.get(error_id, 500)
        self.message = message or error_id


def fail(error_id, message):
    raise ApiError(error_id, message)


def _meta():
    return {
        'api_request_id': 'req_' + uuid.uuid4().hex,
        'api_request_timestamp': store.now_ts3(),
    }


def ok(data, status=200):
    body = {'meta': _meta(), 'response_type': 'object', 'data': data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, total, limit, offset):
    meta = _meta()
    meta['limit'] = limit
    meta['offset'] = offset
    meta['total_count'] = total
    meta['has_more'] = (offset + len(items)) < total
    body = {'meta': meta, 'response_type': 'array', 'data': items}
    return jsonify(body)


def error_resp(err):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': err.error_id, 'message': err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.status
    return resp
