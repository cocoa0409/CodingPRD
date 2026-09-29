"""Response envelope helpers (PRD 2.2, 2.3)."""
import json
import random
import string
from decimal import Decimal

from flask import Response, request

import db as store
from errors import ApiError, bad_request

META_KEY = "meta"
TYPE_KEY = "response_type"
DATA_KEY = "data"
REQUEST_ID_KEY = "api_request_id"
REQUEST_TS_KEY = "api_request_timestamp"
ERROR_ID_KEY = "error_id"
ERROR_MESSAGE_KEY = "message"

LIMIT_KEY = "limit"
OFFSET_KEY = "offset"
TOTAL_KEY = "total_count"
HAS_MORE_KEY = "has_more"

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

_ID_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


class _Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            exponent = o.as_tuple().exponent
            if isinstance(exponent, int) and exponent >= 0:
                return int(o)
            return float(o)
        return json.JSONEncoder.default(self, o)


def _emit(payload, http_status):
    body = json.dumps(payload, cls=_Encoder)
    return Response(body, status=http_status, mimetype="application/json")


def _base_meta():
    return {
        REQUEST_ID_KEY: _request_id(),
        REQUEST_TS_KEY: store.iso(store.db.now()),
    }


def object_response(data, http_status=200):
    payload = {
        META_KEY: _base_meta(),
        TYPE_KEY: "object",
        DATA_KEY: data if data is not None else {},
    }
    return _emit(payload, http_status)


def created_response(data):
    return object_response(data, 201)


def list_response(items, limit, offset, total_count, has_more):
    meta = _base_meta()
    meta[LIMIT_KEY] = limit
    meta[OFFSET_KEY] = offset
    meta[TOTAL_KEY] = total_count
    meta[HAS_MORE_KEY] = has_more
    payload = {
        META_KEY: meta,
        TYPE_KEY: "array",
        DATA_KEY: {
            "items": items,
            TOTAL_KEY: total_count,
            HAS_MORE_KEY: has_more,
        },
    }
    return _emit(payload, 200)


def error_response(error):
    payload = {
        META_KEY: _base_meta(),
        TYPE_KEY: "error",
        DATA_KEY: {
            ERROR_ID_KEY: error.error_id,
            ERROR_MESSAGE_KEY: error.message,
        },
    }
    return _emit(payload, error.http_status)


def _read_int_param(name, default, minimum, maximum):
    raw = request.args.get(name, None)
    if raw is None:
        return default
    text = raw.strip()
    if text == "":
        raise bad_request("Query parameter '%s' must be an integer." % name)
    try:
        value = int(text, 10)
    except (TypeError, ValueError):
        raise bad_request("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad_request("Query parameter '%s' is below the permitted minimum."
                          % name)
    if maximum is not None and value > maximum:
        raise bad_request("Query parameter '%s' exceeds the permitted maximum."
                          % name)
    return value


def read_pagination():
    limit = _read_int_param(LIMIT_KEY, DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT)
    offset = _read_int_param(OFFSET_KEY, DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginated(rows, serializer):
    limit, offset = read_pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return list_response([serializer(r) for r in page], limit, offset, total,
                         has_more)


def json_body():
    """Parse the JSON body leniently; header checks run before this."""
    data = request.get_json(silent=True)
    if data is None:
        if not (request.data or b"").strip():
            return {}
        raise bad_request("Request body is not valid JSON.")
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object.")
    return data
