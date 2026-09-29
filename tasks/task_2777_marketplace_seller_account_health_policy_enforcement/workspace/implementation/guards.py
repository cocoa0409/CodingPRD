"""Row lookups (PRD 2.9) and the ban gate (PRD 2.5)."""

import db
from errors import ApiError


def _get(table, row_id, error_id):
    if not isinstance(row_id, str) or row_id not in table:
        raise ApiError(error_id)
    return table[row_id]


def seller(row_id):
    return _get(db.SELLERS, row_id, "ERR_SELLER_NOT_FOUND")


def policy_rule(row_id):
    return _get(db.POLICY_RULES, row_id, "ERR_POLICY_RULE_NOT_FOUND")


def listing(row_id):
    return _get(db.LISTINGS, row_id, "ERR_LISTING_NOT_FOUND")


def violation(row_id):
    return _get(db.VIOLATIONS, row_id, "ERR_VIOLATION_NOT_FOUND")


def evaluation(row_id):
    return _get(db.HEALTH_EVALUATIONS, row_id, "ERR_EVALUATION_NOT_FOUND")


def action(row_id):
    return _get(db.ENFORCEMENT_ACTIONS, row_id, "ERR_ACTION_NOT_FOUND")


def plan(row_id):
    return _get(db.PLANS_OF_ACTION, row_id, "ERR_POA_NOT_FOUND")


def appeal(row_id):
    return _get(db.APPEALS, row_id, "ERR_APPEAL_NOT_FOUND")


def hold(row_id):
    return _get(db.DISBURSEMENT_HOLDS, row_id, "ERR_HOLD_NOT_FOUND")


def link(row_id):
    return _get(db.RELATED_ACCOUNT_LINKS, row_id, "ERR_LINK_NOT_FOUND")


def body_fk(table, value, error_id):
    """A body foreign key: resolved only once it is a non-empty string, so a
    missing or wrongly typed field falls through to the request-shape step."""
    if not isinstance(value, str) or value == "":
        return None
    if value not in table:
        raise ApiError(error_id)
    return table[value]


def ensure_not_banned(seller_row):
    if seller_row.get("ban_reason") or seller_row["enforcement_state"] == "BANNED":
        raise ApiError("ERR_SELLER_BANNED")
