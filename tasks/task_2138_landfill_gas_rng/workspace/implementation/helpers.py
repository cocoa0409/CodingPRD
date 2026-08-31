"""Path-existence lookups (priority 30) and body foreign keys (priority 50)."""

from flask import request

import store
from errors import fail

_NOT_FOUND = {
    "site": "ERR_SITE_NOT_FOUND",
    "well": "ERR_WELL_NOT_FOUND",
    "work_order": "ERR_WORK_ORDER_NOT_FOUND",
    "plant": "ERR_PLANT_NOT_FOUND",
    "downtime": "ERR_DOWNTIME_EVENT_NOT_FOUND",
    "contract": "ERR_CONTRACT_NOT_FOUND",
    "nomination": "ERR_NOMINATION_NOT_FOUND",
    "batch": "ERR_INJECTION_BATCH_NOT_FOUND",
    "attribute": "ERR_ATTRIBUTE_BATCH_NOT_FOUND",
    "report": "ERR_REPORT_NOT_FOUND",
    "statement": "ERR_ROYALTY_STATEMENT_NOT_FOUND",
}

_COLLECTIONS = {
    "site": lambda: store.sites,
    "well": lambda: store.wells,
    "work_order": lambda: store.work_orders,
    "plant": lambda: store.plants,
    "downtime": lambda: store.downtime_events,
    "contract": lambda: store.contracts,
    "nomination": lambda: store.nominations,
    "batch": lambda: store.injection_batches,
    "attribute": lambda: store.attribute_batches,
    "report": lambda: store.compliance_reports,
    "statement": lambda: store.royalty_statements,
}


def must_find(kind, row_id):
    if not isinstance(row_id, str):
        fail(_NOT_FOUND[kind], "%s does not resolve." % kind)
    row = _COLLECTIONS[kind]().get(row_id)
    if row is None:
        fail(_NOT_FOUND[kind], "The referenced %s does not exist." % kind.replace("_", " "))
    return row


def filter_equal(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
