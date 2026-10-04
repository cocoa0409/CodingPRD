"""Shared route helpers: pagination, filtering, lookups and body parsing."""

from flask import request

from core import constants as C
from core.db import all_rows, find, ordered, paginate, store
from core.errors import ApiError
from core.response import send_list
from core.validate import body_object, reject_unknown


def pagination_args():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = C.PAGINATION_DEFAULT_LIMIT
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        offset = C.PAGINATION_DEFAULT_OFFSET
    if limit < C.PAGINATION_MIN_LIMIT:
        limit = C.PAGINATION_MIN_LIMIT
    if limit > C.PAGINATION_MAX_LIMIT:
        limit = C.PAGINATION_MAX_LIMIT
    if offset < 0:
        offset = C.PAGINATION_DEFAULT_OFFSET
    return limit, offset


def _matches(value, raw):
    if isinstance(value, bool):
        lowered = str(raw).strip().lower()
        if lowered in ("true", "1", "yes"):
            return value is True
        if lowered in ("false", "0", "no"):
            return value is False
        return False
    if value is None:
        return str(raw).strip().lower() in ("none", "null", "")
    return str(value) == str(raw)


def filter_rows(rows, mapping):
    """mapping: query-parameter name -> row field name."""
    for param, field in mapping.items():
        if param in request.args:
            raw = request.args.get(param)
            rows = [row for row in rows if _matches(row.get(field), raw)]
    return rows


def list_response(rows, serializer):
    ordered_rows = ordered(rows)
    limit, offset = pagination_args()
    page, total = paginate(ordered_rows, limit, offset)
    return send_list([serializer(row) for row in page], limit, offset, total)


def fetch(collection, row_id, error_id):
    row = find(collection, row_id)
    if row is None:
        raise ApiError(error_id, "The requested resource does not exist.")
    return row


def body(declared_fields):
    payload = body_object(request.get_json(silent=True))
    reject_unknown(payload, set(declared_fields))
    return payload


def clients():
    return store.clients


def engagement_client(engagement):
    if engagement is None:
        return None
    return store.clients.get(engagement.get("client_id"))


def engagement_of(assignment):
    return store.engagements.get(assignment.get("engagement_id"))
