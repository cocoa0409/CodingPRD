"""Shared route helpers."""

from flask import jsonify

from response import success, success_array, success_object


def ok(payload, status=200):
    return jsonify(success_object(payload)), status


def ok_array(items):
    """A list result from an endpoint that declares no pagination parameters.

    PRD 2.2: response_type is "array" for a list of resources. Pagination fields
    appear in meta only for the list endpoints that accept limit/offset.
    """
    return jsonify(success(list(items), "array")), 200


def ok_list(items, limit, offset, total_count):
    return jsonify(success_array(items, limit, offset, total_count)), 200


def paginate(records, limit, offset, sort_key=None):
    rows = list(records)
    if sort_key is not None:
        rows.sort(key=sort_key)
    total_count = len(rows)
    return rows[offset:offset + limit], total_count