"""Response envelope helpers per PRD §2.2 and the scaffold response_envelope."""
import secrets

from flask import jsonify

from helpers import iso
from storage import store


def _meta():
    return {
        'api_request_id': 'req_' + secrets.token_hex(12),
        'api_request_timestamp': iso(store.now()),
    }


def ok(data, code=200):
    """Single-resource (or empty-object) success envelope."""
    return jsonify({'meta': _meta(), 'response_type': 'object', 'data': data}), code


def ok_list(items, limit, offset, total_count):
    """List envelope: pagination fields live in meta."""
    meta = _meta()
    meta['limit'] = limit
    meta['offset'] = offset
    meta['total_count'] = total_count
    meta['has_more'] = offset + limit < total_count
    return jsonify({'meta': meta, 'response_type': 'array', 'data': items}), 200


def error_resp(error_id, status, message):
    return jsonify({
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }), status
