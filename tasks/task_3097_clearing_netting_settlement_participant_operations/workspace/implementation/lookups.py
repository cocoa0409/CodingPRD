"""Lookup, relationship and comparison-tuple helpers.

Path identifiers are resolved left to right (PRD 2.11) and a body-referenced
participant or security that does not resolve reports its specific error id.
"""

from db import db
from errors import (
    api_error,
    ERR_RESOURCE_NOT_FOUND,
    ERR_PARTICIPANT_NOT_FOUND,
    ERR_SECURITY_NOT_FOUND,
)


# ---------------------------------------------------------------------------
# Path lookups (ERR_RESOURCE_NOT_FOUND for a path-level miss)
# ---------------------------------------------------------------------------
def get_participant(pid):
    rec = db.participants.get(pid)
    if rec is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return rec


def get_security(sid):
    rec = db.securities.get(sid)
    if rec is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return rec


def get_window(wid):
    rec = db.settlement_windows.get(wid)
    if rec is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return rec


def get_deposit(did):
    rec = db.deposits.get(did)
    if rec is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return rec


def get_trade(tid):
    rec = db.trade_submissions.get(tid)
    if rec is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return rec


def get_net_position(nid):
    rec = db.net_positions.get(nid)
    if rec is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return rec


def get_custody_account(aid):
    rec = db.custody_accounts.get(aid)
    if rec is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return rec


def get_corporate_action(aid):
    rec = db.corporate_actions.get(aid)
    if rec is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return rec


def get_clearing_fund(fid):
    rec = db.clearing_funds.get(fid)
    if rec is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return rec


def get_fund_component(cid):
    rec = db.fund_components.get(cid)
    if rec is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return rec


def get_proceeding(pid):
    rec = db.default_proceedings.get(pid)
    if rec is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return rec


# ---------------------------------------------------------------------------
# Body lookups (ERR_PARTICIPANT_NOT_FOUND / ERR_SECURITY_NOT_FOUND)
# ---------------------------------------------------------------------------
def require_body_participant(pid):
    rec = db.participants.get(pid)
    if rec is None:
        raise api_error(ERR_PARTICIPANT_NOT_FOUND)
    return rec


def require_body_security(sid):
    rec = db.securities.get(sid)
    if rec is None:
        raise api_error(ERR_SECURITY_NOT_FOUND)
    return rec


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------
def deposit_of(participant_id):
    for deposit in db.deposits.values():
        if deposit["participant_id"] == participant_id:
            return deposit
    return None


def find_window(security_id, settlement_date, *, only_open=False):
    """The window for (security_id, settlement_date) among non-CLOSED rows."""
    for window in db.settlement_windows.values():
        if window["security_id"] != security_id:
            continue
        if window["settlement_date"] != settlement_date:
            continue
        if window["status"] == "CLOSED":
            continue
        if only_open and window["status"] != "OPEN":
            continue
        return window
    return None


def windows_of_security(security_id):
    return [w for w in db.settlement_windows.values() if w["security_id"] == security_id]


def net_positions_of_window(window_id):
    return [np for np in db.net_positions.values() if np["window_id"] == window_id]


def net_positions_of_participant(participant_id):
    return [np for np in db.net_positions.values() if np["participant_id"] == participant_id]


def deposits_of_participant(participant_id):
    return [d for d in db.deposits.values() if d["participant_id"] == participant_id]


def custody_accounts_of(participant_id):
    return [a for a in db.custody_accounts.values() if a["participant_id"] == participant_id]


def postings_of_deposit(deposit_id):
    return [t for t in db.deposit_transactions.values() if t["deposit_id"] == deposit_id]


def postings_of_participant(participant_id):
    return [t for t in db.deposit_transactions.values() if t["participant_id"] == participant_id]


def components_of_fund(fund_id):
    return [c for c in db.fund_components.values() if c["clearing_fund_id"] == fund_id]


def components_of_participant(participant_id):
    return [c for c in db.fund_components.values() if c["participant_id"] == participant_id]


def proceedings_of_participant(participant_id):
    return [p for p in db.default_proceedings.values() if p["participant_id"] == participant_id]


def loss_allocations_of_proceeding(proceeding_id):
    return [a for a in db.loss_allocations.values() if a["default_proceeding_id"] == proceeding_id]


def loss_allocations_of_component(component_id):
    return [a for a in db.loss_allocations.values() if a["fund_component_id"] == component_id]


def bids_of_proceeding(proceeding_id):
    return [b for b in db.bids.values() if b["default_proceeding_id"] == proceeding_id]


# ---------------------------------------------------------------------------
# Comparison tuple (PRD 2.6)
# ---------------------------------------------------------------------------
def is_contra(candidate, trade):
    """A non-CANCELLED submission matching the five-term comparison tuple.

    Terms: the party pair (reversed), the instrument, the opposite side, the
    exact quantity and the exact trade_date.
    """
    if candidate["id"] == trade["id"]:
        return False
    if candidate["lock_status"] == "CANCELLED":
        return False
    return (
        candidate["counterparty_participant_id"] == trade["participant_id"]
        and candidate["participant_id"] == trade["counterparty_participant_id"]
        and candidate["security_id"] == trade["security_id"]
        and candidate["side"] != trade["side"]
        and candidate["quantity"] == trade["quantity"]
        and candidate["trade_date"] == trade["trade_date"]
    )


def contras_of(trade):
    return [
        candidate
        for candidate in db.trade_submissions.values()
        if is_contra(candidate, trade)
    ]


def tuple_rows(trade):
    """Every non-CANCELLED row of the comparison tuple, the trade included."""
    rows = [trade] if trade["lock_status"] != "CANCELLED" else []
    rows.extend(contras_of(trade))
    return rows


def recompute_allegations(trade):
    trade["allegations_received"] = len(contras_of(trade))
    return trade["allegations_received"]


def is_settled_trade(trade):
    return trade["lock_status"] == "LOCKED_IN" and trade["match_status"] in ("MATCHED", "UNRESOLVED")


def trade_sort_key(trade):
    return (trade["trade_date"], trade["created_at"])