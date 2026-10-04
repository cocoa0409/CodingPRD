from flask import jsonify

from helpers import req_id
import store


def success(status, data, response_type, pagination=None):
    meta = {
        "api_request_id": req_id(),
        "api_request_timestamp": store.now_iso_ms(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_envelope(error_id, message, status):
    meta = {
        "api_request_id": req_id(),
        "api_request_timestamp": store.now_iso_ms(),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
