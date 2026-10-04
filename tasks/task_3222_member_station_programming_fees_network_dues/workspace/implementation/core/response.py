"""The success envelope: meta / response_type / data."""
from flask import jsonify

from . import config as C


def _meta(extra=None):
    meta = {
        "api_request_id": C.new_request_id(),
        "api_request_timestamp": C.envelope_ts(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200, meta_extra=None):
    return jsonify({
        "meta": _meta(meta_extra),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def array_response(items, meta=None, status=200):
    return jsonify({
        "meta": _meta(meta),
        "response_type": "array",
        "data": items,
    }), status


def empty_response(status=200, meta_extra=None):
    return jsonify({
        "meta": _meta(meta_extra),
        "response_type": "object",
        "data": {},
    }), status