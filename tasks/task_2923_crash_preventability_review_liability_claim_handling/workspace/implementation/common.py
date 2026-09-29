"""Shared route helpers: lookups, list plumbing and cascade utilities."""

import calc
from envelope import ok_list
from errors import fail
from shape import pagination
from store import db, ordered, touch

NOT_FOUND = {
    "terminals": "ERR_TERMINAL_NOT_FOUND",
    "drivers": "ERR_DRIVER_NOT_FOUND",
    "crashes": "ERR_CRASH_NOT_FOUND",
    "evidence_items": "ERR_EVIDENCE_ITEM_NOT_FOUND",
    "review_cases": "ERR_REVIEW_CASE_NOT_FOUND",
    "claims": "ERR_CLAIM_NOT_FOUND",
    "policy_layers": "ERR_POLICY_LAYER_NOT_FOUND",
    "demands": "ERR_DEMAND_NOT_FOUND",
    "disciplinary_actions": "ERR_DISCIPLINARY_ACTION_NOT_FOUND",
    "subrogation_demands": "ERR_SUBROGATION_DEMAND_NOT_FOUND",
}

LABEL = {
    "terminals": "Terminal",
    "drivers": "Driver",
    "crashes": "Crash",
    "evidence_items": "Evidence item",
    "review_cases": "Review case",
    "claims": "Claim",
    "policy_layers": "Policy layer",
    "demands": "Demand",
    "disciplinary_actions": "Disciplinary action",
    "subrogation_demands": "Subrogation demand",
}


def lookup(collection_name, entity_id):
    collection = getattr(db, collection_name)
    row = collection.get(entity_id)
    if row is None:
        fail(NOT_FOUND[collection_name],
             "%s '%s' was not found" % (LABEL[collection_name], entity_id))
    return row


def paginate(items, serializer):
    limit, offset = pagination()
    total = len(items)
    window = items[offset:offset + limit]
    return ok_list([serializer(row) for row in window], limit, offset, total)


def match(row, criteria):
    for key, value in criteria.items():
        if row.get(key) != value:
            return False
    return True


def filtered(collection_name, criteria, extra=None):
    result = []
    for row in getattr(db, collection_name).values():
        if not match(row, criteria):
            continue
        if extra is not None and not extra(row):
            continue
        result.append(row)
    return ordered(result)


# ---------------------------------------------------------------------------
# Cascade utilities
# ---------------------------------------------------------------------------
def claim_for_crash(crash_id):
    for row in db.claims.values():
        if row["crash_id"] == crash_id:
            return row
    return None


def review_case_for_crash(crash_id):
    for row in db.review_cases.values():
        if row["crash_id"] == crash_id:
            return row
    return None


def statement_exists(crash_id):
    for row in db.driver_statements.values():
        if row["crash_id"] == crash_id:
            return True
    return False


def driver_actions(driver_id):
    return ordered([a for a in db.disciplinary_actions.values()
                    if a["driver_id"] == driver_id])


def retraining_pending(driver_id, exclude_id=None):
    for action in driver_actions(driver_id):
        if action["id"] == exclude_id:
            continue
        if action["status"] == "ISSUED" and action["retraining_status"] == "PENDING":
            return True
    return False
