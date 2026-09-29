"""Shared route plumbing: path existence (rung 6) and list handling (PRD 2.3)."""

from auth import scope_to_owner
from envelope import ok_list
from errors import ApiError
from shape import pagination, paginate, query_bool, query_str
from store import order_key, store
from views import view_all

NOT_FOUND = {
    "pilots": "ERR_PILOT_NOT_FOUND",
    "knowledge_tests": "ERR_KNOWLEDGE_TEST_NOT_FOUND",
    "certifications": "ERR_CERTIFICATION_NOT_FOUND",
    "aircraft": "ERR_AIRCRAFT_NOT_FOUND",
    "modules": "ERR_MODULE_NOT_FOUND",
    "zones": "ERR_ZONE_NOT_FOUND",
    "tfrs": "ERR_TFR_NOT_FOUND",
    "authorizations": "ERR_AUTHORIZATION_NOT_FOUND",
    "waivers": "ERR_WAIVER_NOT_FOUND",
    "safety_cases": "ERR_SAFETY_CASE_NOT_FOUND",
    "policies": "ERR_POLICY_NOT_FOUND",
    "flights": "ERR_FLIGHT_NOT_FOUND",
    "reports": "ERR_REPORT_NOT_FOUND",
    "preflight_checks": "ERR_FLIGHT_NOT_FOUND",
}


def find(collection, row_id):
    return store.get(collection, row_id)


def must_exist(collection, row_id):
    row = store.get(collection, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection])
    return row


def string_filters(*names):
    out = {}
    for name in names:
        value = query_str(name)
        if value is not None:
            out[name] = value
    return out


def bool_filters(*names):
    out = {}
    for name in names:
        value = query_bool(name)
        if value is not None:
            out[name] = value
    return out


def collection_response(caller, collection, filters=None, rows=None, descending=False,
                        predicate=None):
    limit, offset = pagination()
    if rows is None:
        rows = store.all(collection)
    if filters:
        rows = [row for row in rows
                if all(row.get(key) == value for key, value in filters.items())]
    if predicate is not None:
        rows = [row for row in rows if predicate(row)]
    rows = scope_to_owner(caller, rows)
    rows = sorted(rows, key=order_key, reverse=descending)
    total = len(rows)
    window = paginate(rows, limit, offset)
    return ok_list(view_all(window), limit, offset, total)
