"""Standard response envelopes (PRD 2.2, scaffold response_envelope)."""
import uuid

from flask import jsonify

import db


def _meta(pagination=None):
    meta = {
        'api_request_id': 'req_' + uuid.uuid4().hex[:20],
        'api_request_timestamp': db.now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200, response_type='object'):
    body = {'meta': _meta(), 'response_type': response_type, 'data': data}
    return jsonify(body), status


def list_response(items, total_count, limit, offset):
    pagination = {
        'limit': limit,
        'offset': offset,
        'total_count': total_count,
        'has_more': offset + len(items) < total_count,
    }
    body = {'meta': _meta(pagination), 'response_type': 'array', 'data': items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), status
