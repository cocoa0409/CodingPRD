"""Shared route helpers: path resolution, listing and owner narrowing."""

from flask import request

import auth
import envelope
import store
from errors import ApiError

NOT_FOUND = {
    "standard": "ERR_STANDARD_NOT_FOUND",
    "definition": "ERR_DEFECT_DEFINITION_NOT_FOUND",
    "property": "ERR_PROPERTY_NOT_FOUND",
    "unit": "ERR_UNIT_NOT_FOUND",
    "inspection": "ERR_INSPECTION_NOT_FOUND",
    "selection": "ERR_SAMPLE_SELECTION_NOT_FOUND",
    "deficiency": "ERR_DEFICIENCY_NOT_FOUND",
    "sweep": "ERR_SWEEP_NOT_FOUND",
    "work_order": "ERR_WORK_ORDER_NOT_FOUND",
    "appeal": "ERR_APPEAL_NOT_FOUND",
    "plan": "ERR_CAP_NOT_FOUND",
    "capital_item": "ERR_CAPITAL_NEED_NOT_FOUND",
}

COLLECTIONS = {
    "standard": store.standards,
    "definition": store.definitions,
    "property": store.properties,
    "unit": store.units,
    "inspection": store.inspections,
    "selection": store.selections,
    "deficiency": store.deficiencies,
    "sweep": store.sweeps,
    "work_order": store.work_orders,
    "appeal": store.appeals,
    "plan": store.plans,
    "capital_item": store.capital_items,
}


def fetch(kind, row_id):
    row = COLLECTIONS[kind].get(row_id)
    if row is None:
        raise ApiError(
            NOT_FOUND[kind], "No %s exists with id %s." % (kind.replace("_", " "), row_id)
        )
    return row


def body_fetch(kind, row_id):
    """Body foreign keys resolve to the same 404 catalogue as path ids."""
    return fetch(kind, row_id)


def query_filter(rows, names):
    """Equality filtering on the declared query parameters."""
    out = rows
    for name in names:
        supplied = request.args.get(name)
        if supplied is None:
            continue
        out = [r for r in out if r.get(name) == supplied]
    return out


def narrow_to_owner(rows, role, user_id, property_getter):
    """Collection listings silently narrow to the caller's own property."""
    if role != auth.OWNER:
        return rows
    return [r for r in rows if property_getter(r) == user_id]


def listing(rows, filters, role=None, user_id=None, property_getter=None):
    limit, offset = envelope.pagination_args(request.args)
    rows = query_filter(list(rows), filters)
    if property_getter is not None:
        rows = narrow_to_owner(rows, role, user_id, property_getter)
    rows = store.by_seq(rows)
    return envelope.page(rows, limit, offset)
