"""§2.2 API Response Structure."""

import random
import string

from flask import jsonify

import clock
import common

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    body = "".join(random.choice(_ALPHABET) for _ in range(18))
    return "req_" + body


def _meta(extra=None):
    meta = {
        common.META_REQUEST_ID: request_id(),
        common.META_REQUEST_TIMESTAMP: clock.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, response_type="object", pagination=None):
    body = {
        common.RESPONSE_META: _meta(pagination),
        common.RESPONSE_TYPE: response_type,
        common.RESPONSE_DATA: data,
    }
    return jsonify(body)


def object_response(data, status=200):
    return success(data, "object"), status


def array_response(rows, limit, offset, total_count, status=200):
    pagination = {
        common.PAGINATION_FIELDS[0]: limit,
        common.PAGINATION_FIELDS[1]: offset,
        common.PAGINATION_FIELDS[2]: total_count,
        common.PAGINATION_FIELDS[3]: offset + len(rows) < total_count,
    }
    return success(rows, "array", pagination), status


def error_response(error_id, message, status):
    body = {
        common.RESPONSE_META: _meta(),
        common.RESPONSE_TYPE: "error",
        common.RESPONSE_DATA: {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status