"""Skimming claims: filing, freezing, investigation, adjudication, credits."""
from datetime import timedelta

from flask import Blueprint

from errors import ApiError
from state import DB
from domain import (
    new_entity, touch, post_entry, ser_claim, claim_target_purse,
)
from util import authed, body, req_str, req_int, opt_bool, ok_object, now_dt

bp = Blueprint("claims", __name__, url_prefix="/ebt")

TERMINAL_CLAIM_STATES = ("SUBSTANTIATED", "UNSUBSTANTIATED")


def get_claim(cid):
    c = DB.claims.get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "claim not found")
    return c


def _charged_purse_ids(authorization_ids):
    purse_ids = set()
    for e in DB.entries.values():
        if e["reference_id"] in authorization_ids and e["entry_type"] in (
                "PURCHASE_DEBIT", "WITHDRAWAL_DEBIT"):
            purse_ids.add(e["purse_id"])
    return purse_ids


@bp.post("/claims")
def file_claim():
    role, uid = authed(["Cardholder", "CardholderServices"])
    b = body()
    case_id = req_str(b, "case_account_id")
    card_id = req_str(b, "card_id")
    # Pipeline step 4 (ownership) precedes step 5 (body references).
    if role == "Cardholder" and uid != case_id:
        raise ApiError("ERR_FORBIDDEN", "a cardholder may file only for their own case")
    case = DB.cases.get(case_id)
    if case is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "case_account_id does not exist")
    if DB.cards.get(card_id) is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "card_id does not exist")
    authorization_ids = b.get("authorization_ids")
    if not isinstance(authorization_ids, list) \
            or not (1 <= len(authorization_ids) <= 20) \
            or any(not isinstance(a, str) for a in authorization_ids):
        raise ApiError("ERR_INVALID_REQUEST",
                       "authorization_ids must be a list of 1..20 ids")
    claimed = req_int(b, "claimed_amount_cents")
    if claimed <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "claimed_amount_cents must be > 0")
    description = req_str(b, "incident_description")
    freeze = opt_bool(b, "freeze_purse", True)
    txns = []
    for aid in authorization_ids:
        t = DB.txns.get(aid)
        if t is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND",
                           "an authorization_ids element does not exist")
        txns.append(t)
    if case["account_status"] != "OPEN":
        raise ApiError("ERR_CASE_NOT_OPEN", "claim filing requires the case OPEN")
    contract = DB.contracts[case["contract_id"]]
    now = now_dt()
    for t in txns:
        if now > t["created_at"] + timedelta(days=contract["claim_window_days"]):
            raise ApiError("ERR_CLAIM_WINDOW_EXPIRED",
                           "a referenced transaction is older than the claim window")
    for t in txns:
        if t["case_account_id"] != case["id"]:
            raise ApiError("ERR_CLAIM_TXN_CASE_MISMATCH",
                           "a referenced transaction belongs to a different case")
    if claimed > sum(t["total_cents"] for t in txns):
        raise ApiError("ERR_CLAIM_AMOUNT_EXCEEDS_REFERENCED",
                       "claimed_amount_cents exceeds the referenced totals")
    claim = new_entity()
    claim.update({
        "case_account_id": case["id"],
        "card_id": card_id,
        "authorization_ids": list(authorization_ids),
        "claimed_amount_cents": claimed,
        "incident_description": description,
        "freeze_purse": freeze,
        "investigation_status": "FILED",
        "credit_status": "NONE",
        "provisional_credit_cents": 0,
        "provisional_credited_at": None,
        "substantiated_amount_cents": None,
        "filed_by_user_id": uid,
        "filed_by_role": role,
        "decided_by_user_id": None,
        "investigated_at": None,
        "decided_at": None,
        "_frozen_purse_ids": set(),
    })
    DB.claims[claim["id"]] = claim
    if freeze:
        for pid in _charged_purse_ids(set(authorization_ids)):
            purse = DB.purses[pid]
            if purse["purse_status"] == "OPEN":
                purse["purse_status"] = "FROZEN"
                touch(purse)
            purse.setdefault("_freezing_claim_ids", set()).add(claim["id"])
            claim["_frozen_purse_ids"].add(pid)
    return ok_object(ser_claim(claim), 201)


def _unfreeze_claim_purses(claim):
    case = DB.cases[claim["case_account_id"]]
    if case["account_status"] == "CLOSED":
        return
    for pid in claim["_frozen_purse_ids"]:
        purse = DB.purses[pid]
        if purse["purse_status"] != "FROZEN":
            continue
        freezing = purse.get("_freezing_claim_ids", set())
        if all(DB.claims[cid]["investigation_status"] in TERMINAL_CLAIM_STATES
               for cid in freezing):
            purse["purse_status"] = "OPEN"
            touch(purse)


@bp.post("/claims/<cid>/status")
def claim_status(cid):
    role, uid = authed(["CardholderServices", "StateAdmin"])
    claim = get_claim(cid)
    b = body()
    to = req_str(b, "to")
    if to not in ("FILED", "UNDER_INVESTIGATION", "SUBSTANTIATED", "UNSUBSTANTIATED"):
        raise ApiError("ERR_INVALID_REQUEST", "unknown target status")
    if to == "UNDER_INVESTIGATION":
        if role != "CardholderServices":
            raise ApiError("ERR_FORBIDDEN",
                           "only CardholderServices may move a claim to UNDER_INVESTIGATION")
    elif to in ("SUBSTANTIATED", "UNSUBSTANTIATED"):
        if role != "StateAdmin":
            raise ApiError("ERR_FORBIDDEN", "only StateAdmin adjudicates claims")
    else:
        raise ApiError("ERR_INVALID_STATE", "claims cannot transition to FILED")
    cur = claim["investigation_status"]
    now = now_dt()
    if to == "UNDER_INVESTIGATION":
        if cur != "FILED":
            raise ApiError("ERR_INVALID_STATE",
                           f"cannot move a {cur} claim to UNDER_INVESTIGATION")
        if claim["filed_by_role"] == "CardholderServices" \
                and claim["filed_by_user_id"] == uid:
            raise ApiError("ERR_SOD_VIOLATION",
                           "the filer may not investigate their own claim")
        claim["investigation_status"] = "UNDER_INVESTIGATION"
        claim["investigated_at"] = now
        touch(claim)
        return ok_object(ser_claim(claim))
    # adjudication
    if cur != "UNDER_INVESTIGATION":
        raise ApiError("ERR_INVALID_STATE",
                       f"cannot adjudicate a claim in {cur}")
    case = DB.cases[claim["case_account_id"]]
    contract = DB.contracts[case["contract_id"]]
    if to == "SUBSTANTIATED":
        amount = req_int(b, "substantiated_amount_cents")
        if amount <= 0 or amount > claim["claimed_amount_cents"]:
            raise ApiError("ERR_INVALID_REQUEST",
                           "substantiated_amount_cents must be > 0 and <= claimed amount")
        final = min(amount, claim["claimed_amount_cents"])
        claim["substantiated_amount_cents"] = amount
        purse = claim_target_purse(claim)
        provisional = claim["provisional_credit_cents"] \
            if claim["credit_status"] == "PROVISIONAL" else 0
        delta = final - provisional
        if purse is not None and delta > 0:
            post_entry(purse["id"], "CLAIM_CREDIT", delta,
                       reference_id=claim["id"], memo="claim credit", at=now)
        elif purse is not None and delta < 0:
            post_entry(purse["id"], "CLAIM_REVERSAL_DEBIT", -delta,
                       reference_id=claim["id"], memo="claim reversal", at=now)
        claim["credit_status"] = "FINAL"
        claim["investigation_status"] = "SUBSTANTIATED"
        claim["decided_by_user_id"] = uid
        claim["decided_at"] = now
        touch(claim)
        _unfreeze_claim_purses(claim)
        # retailer integrity cascade
        retailer_ids = []
        for aid in claim["authorization_ids"]:
            t = DB.txns.get(aid)
            if t and t["retailer_id"] not in retailer_ids:
                retailer_ids.append(t["retailer_id"])
        for rid in retailer_ids:
            retailer = DB.retailers.get(rid)
            if retailer is None:
                continue
            retailer["skimming_incident_count"] += 1
            if retailer["skimming_incident_count"] >= contract["skimming_suspend_threshold"] \
                    and retailer["retailer_status"] == "APPROVED":
                retailer["retailer_status"] = "SUSPENDED"
                retailer["_suspended_at"] = now
            touch(retailer)
        return ok_object(ser_claim(claim))
    # UNSUBSTANTIATED
    if claim["credit_status"] == "PROVISIONAL":
        purse = claim_target_purse(claim)
        if purse is not None and claim["provisional_credit_cents"] > 0:
            post_entry(purse["id"], "PROVISIONAL_REVERSAL_DEBIT",
                       claim["provisional_credit_cents"],
                       reference_id=claim["id"], memo="provisional reversal", at=now)
        claim["credit_status"] = "REVERSED"
    claim["investigation_status"] = "UNSUBSTANTIATED"
    claim["decided_by_user_id"] = uid
    claim["decided_at"] = now
    touch(claim)
    _unfreeze_claim_purses(claim)
    return ok_object(ser_claim(claim))
