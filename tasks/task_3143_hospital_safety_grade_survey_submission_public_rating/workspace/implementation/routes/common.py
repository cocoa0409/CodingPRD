"""Shared route helpers."""

from flask import jsonify

from errors import ApiError, ERR_INVALID_REQUEST
from middleware import paginate, query_params
from response import array_response, object_response
from serializers import render, render_payload, sorted_by_created


def ok_object(record):
    return jsonify(object_response(render(record)))


def ok_payload(payload):
    return jsonify(object_response(render_payload(payload)))


def ok_list(records, newest_first=False):
    ordered = sorted_by_created(records, newest_first=newest_first)
    window, limit, offset, total = paginate(ordered)
    return jsonify(array_response(render(window), limit, offset, total))


def ok_list_presorted(records):
    window, limit, offset, total = paginate(records)
    return jsonify(array_response(render(window), limit, offset, total))


def filter_value(name):
    value = query_params().get(name)
    if value is None or str(value) == "":
        return None
    return str(value)


def bool_filter(name):
    value = filter_value(name)
    if value is None:
        return None
    if value.lower() in ("true", "1"):
        return True
    if value.lower() in ("false", "0"):
        return False
    raise ApiError(ERR_INVALID_REQUEST)


def require_str(payload, key):
    value = payload.get(key)
    if not isinstance(value, str) or value.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    return value