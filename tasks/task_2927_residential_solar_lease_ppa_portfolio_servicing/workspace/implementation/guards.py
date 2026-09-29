"""Ladder rungs 4-10 helpers shared by every route module (PRD §2.10)."""
from core import ApiError, store

NOT_FOUND = {
    "homeowners": "ERR_HOMEOWNER_NOT_FOUND",
    "tariffs": "ERR_TARIFF_NOT_FOUND",
    "agreements": "ERR_AGREEMENT_NOT_FOUND",
    "periods": "ERR_PERIOD_NOT_FOUND",
    "true_ups": "ERR_TRUE_UP_NOT_FOUND",
    "outage_events": "ERR_OUTAGE_EVENT_NOT_FOUND",
    "truck_rolls": "ERR_TRUCK_ROLL_NOT_FOUND",
    "roof_work_orders": "ERR_ROOF_WORK_ORDER_NOT_FOUND",
    "transfer_cases": "ERR_TRANSFER_CASE_NOT_FOUND",
    "ucc_filings": "ERR_UCC_FILING_NOT_FOUND",
    "elections": "ERR_ELECTION_NOT_FOUND",
    "warranty_claims": "ERR_WARRANTY_CLAIM_NOT_FOUND",
}

NOT_ACTIVE_STATES = ("DRAFT", "PREPAID_CLOSED", "PURCHASED_CLOSED")
OPEN_TRANSFER_STATUSES = ("INITIATED", "CREDIT_REVIEW", "CREDIT_APPROVED", "TITLE_CLEARED")
TERMINAL_TRANSFER_STATUSES = ("CLOSED", "CANCELLED", "CREDIT_DECLINED")


def lookup(collection, row_id):
    """Rungs 4 and 5: resolve an id or raise the collection's not-found code."""
    table = getattr(store, collection)
    row = table.get(row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection],
                       "No %s row with id %r." % (collection, row_id))
    return row


def homeowner_scope(role, user_id, agreement):
    """Rung 6."""
    if role != "Homeowner":
        return
    if agreement is None or agreement.get("homeowner_id") != user_id:
        raise ApiError("ERR_NOT_AGREEMENT_HOMEOWNER",
                       "This agreement does not belong to the acting homeowner.")


def require_child_write_allowed(ag):
    """Rung 8's ERR_AGREEMENT_NOT_ACTIVE, then rung 10's decommission lockout.

    REMOVED_CLOSED and RELOCATED_CLOSED deliberately fall through rung 8 and are
    reported by the rung-10 lockout instead (PRD §2.10).
    """
    if ag["lifecycle_state"] in NOT_ACTIVE_STATES:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE",
                       "The agreement's lifecycle_state is %s."
                       % ag["lifecycle_state"])


def require_not_decommissioned(ag):
    """Rung 10."""
    if ag["service_status"] == "DECOMMISSIONED":
        raise ApiError("ERR_AGREEMENT_DECOMMISSIONED",
                       "The agreement's asset is decommissioned.")


def bad_state(message="The target is not in a state from which this transition exists."):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


def open_transfers(agreement_id):
    return [c for c in store.transfer_cases.values()
            if c["agreement_id"] == agreement_id
            and c["status"] in OPEN_TRANSFER_STATUSES]


def agreement_rows(agreement_id, collection):
    return [r for r in getattr(store, collection).values()
            if r.get("agreement_id") == agreement_id]


def homeowner_agreement_ids(user_id):
    return set(a["id"] for a in store.agreements.values()
               if a.get("homeowner_id") == user_id)
