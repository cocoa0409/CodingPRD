"""Response envelope helpers (PRD 2.2, 2.3)."""
import random
import string

from flask import jsonify

import clock
from constants import (
    ENV_DATA, ENV_META, ENV_RESPONSE_TYPE, ERROR_ID_FIELD, ERROR_MESSAGE_FIELD,
    META_REQUEST_ID, META_REQUEST_TIMESTAMP, PAGE_HAS_MORE, PAGE_LIMIT,
    PAGE_OFFSET, PAGE_TOTAL_COUNT, REQUEST_ID_PREFIX, RESPONSE_TYPE_ARRAY,
    RESPONSE_TYPE_ERROR, RESPONSE_TYPE_OBJECT,
)

_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return REQUEST_ID_PREFIX + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {
        META_REQUEST_ID: _request_id(),
        META_REQUEST_TIMESTAMP: clock.now_iso(),
    }


def object_response(payload, status=200):
    body = {
        ENV_META: _meta(),
        ENV_RESPONSE_TYPE: RESPONSE_TYPE_OBJECT,
        ENV_DATA: payload,
    }
    return jsonify(body), status


def list_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta[PAGE_LIMIT] = limit
    meta[PAGE_OFFSET] = offset
    meta[PAGE_TOTAL_COUNT] = total_count
    meta[PAGE_HAS_MORE] = offset + len(items) < total_count
    body = {
        ENV_META: meta,
        ENV_RESPONSE_TYPE: RESPONSE_TYPE_ARRAY,
        ENV_DATA: items,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        ENV_META: _meta(),
        ENV_RESPONSE_TYPE: RESPONSE_TYPE_ERROR,
        ENV_DATA: {ERROR_ID_FIELD: error_id, ERROR_MESSAGE_FIELD: message},
    }
    return jsonify(body), status
