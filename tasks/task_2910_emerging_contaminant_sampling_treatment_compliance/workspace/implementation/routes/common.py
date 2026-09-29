"""Shared route plumbing: path resolution (priority 5) and list pagination."""

import db
from db import store
from errors import ApiError
from response import array_response, object_response
from shape import filter_value, boolean_filter, pagination

NOT_FOUND = {
    "contaminants": "ERR_CONTAMINANT_NOT_FOUND",
    "laboratories": "ERR_LABORATORY_NOT_FOUND",
    "entry_points": "ERR_ENTRY_POINT_NOT_FOUND",
    "samples": "ERR_SAMPLE_NOT_FOUND",
    "lab_results": "ERR_LAB_RESULT_NOT_FOUND",
    "determinations": "ERR_DETERMINATION_NOT_FOUND",
    "notifications": "ERR_NOTIFICATION_NOT_FOUND",
    "evaluations": "ERR_EVALUATION_NOT_FOUND",
    "pilots": "ERR_PILOT_NOT_FOUND",
    "manifests": "ERR_MANIFEST_NOT_FOUND",
    "projects": "ERR_PROJECT_NOT_FOUND",
    "applications": "ERR_APPLICATION_NOT_FOUND",
    "claims": "ERR_CLAIM_NOT_FOUND",
}


def resolve(collection, row_id):
    row = getattr(store, collection).get(row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection])
    return row


def detail(collection, row_id):
    return object_response(db.public(resolve(collection, row_id)))


def page(rows, limit, offset):
    window = rows[offset : offset + limit]
    return array_response([db.public(row) for row in window], limit, offset, len(rows))


def apply_scalar_filters(rows, names):
    """Plain equality filters, applied in the declared order."""
    for name in names:
        value = filter_value(name)
        if value is None:
            continue
        rows = [row for row in rows if row.get(name) == value]
    return rows


def apply_boolean_filters(rows, names):
    for name in names:
        value = boolean_filter(name)
        if value is None:
            continue
        rows = [row for row in rows if row.get(name) is value]
    return rows


def filter_fk(rows, query_name, collection, field=None):
    """A foreign-key filter must resolve to an existing row (priority 8)."""
    value = filter_value(query_name)
    if value is None:
        return rows
    resolve(collection, value)
    key = field or query_name
    return [row for row in rows if row.get(key) == value]


__all__ = [
    "resolve",
    "detail",
    "page",
    "apply_scalar_filters",
    "apply_boolean_filters",
    "filter_fk",
    "pagination",
    "filter_value",
    "boolean_filter",
]
