"""Response envelope helpers (PRD 2.2 / 2.3).

Success: {"meta": {api_request_id, api_request_timestamp[, pagination]},
          "response_type": "object"|"array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import random
import string

from flask import jsonify

import store
from timeutil import render_identity


def _request_id():
    return 'req_' + ''.join(random.choices(string.ascii_letters + string.digits, k=16))


def _meta():
    return {
        'api_request_id': _request_id(),
        'api_request_timestamp': render_identity(store.clock_now()),
    }


def ok(data, status=200):
    return jsonify({'meta': _meta(), 'response_type': 'object', 'data': data}), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta['limit'] = limit
    meta['offset'] = offset
    meta['total_count'] = total_count
    meta['has_more'] = (offset + len(items)) < total_count
    return jsonify({'meta': meta, 'response_type': 'array', 'data': items}), 200


def error_resp(error_id, http_status, message):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), http_status
