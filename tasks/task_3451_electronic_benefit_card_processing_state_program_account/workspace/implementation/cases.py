"""Case accounts, purses, ledger and posting reads."""
import re

from flask import Blueprint

from errors import ApiError
from state import DB
from domain import (
    new_entity, touch, post_entry, ser_case, ser_purse, ser_entry, ser_posting,
    ser_card, ser_claim, case_purses, case_cards, case_claims, case_postings,
    ledger_balance,
)
from contracts import _create_purse
from util import (
    authed, body, req_str, ok_object, list_response, sort_created,
    cardholder_owns, query_filter,
)

bp = Blueprint("cases", __name__, url_prefix="/ebt")

CASE_ID_RE = re.compile(r"^[0-9]{10}$")


def get_case(cid):
    c = DB.cases.get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "case account not found")
    return c


def get_purse(pid):
    p = DB.purses.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "purse not found")
    return p


@bp.get("/case-accounts")
def list_cases():
    authed(["StateAdmin", "CardholderServices"])
    rows = list(DB.cases.values())
    contract_id = query_filter("contract_id")
    if contract_id is not None:
        rows = [c for c in rows if c["contract_id"] == contract_id]
    status = query_filter("account_status")
    if status is not None:
        rows = [c for c in rows if c["account_status"] == status]
    return list_response(sort_created(rows), ser_case)


@bp.post("/case-accounts")
def create_case():
    authed(["StateAdmin"])
    b = body()
    contract_id = req_str(b, "contract_id")
    case_identifier = req_str(b, "case_identifier")
    head = req_str(b, "head_of_household_name")
    contract = DB.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "contract_id does not exist")
    if contract["contract_status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "case creation requires contract ACTIVE")
    if not CASE_ID_RE.match(case_identifier):
        raise ApiError("ERR_CASE_IDENTIFIER_INVALID",
                       "case_identifier must be exactly 10 decimal digits")
    if any(c["contract_id"] == contract_id and c["case_identifier"] == case_identifier
           for c in DB.cases.values()):
        raise ApiError("ERR_CASE_IDENTIFIER_DUPLICATE",
                       "case_identifier already exists within the contract")
    case = new_entity()
    case.update({
        "contract_id": contract_id,
        "case_identifier": case_identifier,
        "head_of_household_name": head,
        "account_status": "OPEN",
    })
    DB.cases[case["id"]] = case
    for prog in DB.programs.values():
        if prog["contract_id"] == contract_id and prog["program_status"] == "ACTIVE":
            _create_purse(case["id"], prog["id"])
    return ok_object(ser_case(case), 201)


@bp.get("/case-accounts/<cid>")
def read_case(cid):
    role, uid = authed(["StateAdmin", "CardholderServices", "Cardholder"])
    case = get_case(cid)
    cardholder_owns(role, uid, case["id"])
    return ok_object(ser_case(case))


@bp.post("/case-accounts/<cid>/status")
def case_status(cid):
    authed(["StateAdmin"])
    case = get_case(cid)
    b = body()
    to = req_str(b, "to")
    if to not in ("OPEN", "SUSPENDED", "DORMANT", "CLOSED"):
        raise ApiError("ERR_INVALID_REQUEST", "unknown target status")
    if "expected_case_account_version" not in b or b["expected_case_account_version"] is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "expected_case_account_version is required")
    expected = b["expected_case_account_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST",
                       "expected_case_account_version must be an integer")
    if expected != case["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_case_account_version does not match the case's version")
    cur = case["account_status"]
    allowed = {
        ("OPEN", "SUSPENDED"), ("SUSPENDED", "OPEN"),
        ("OPEN", "CLOSED"), ("SUSPENDED", "CLOSED"), ("DORMANT", "CLOSED"),
    }
    if (cur, to) not in allowed:
        raise ApiError("ERR_INVALID_STATE", f"cannot transition case {cur} -> {to}")
    if to == "CLOSED":
        if any(cl["case_account_id"] == case["id"]
               and cl["investigation_status"] in ("FILED", "UNDER_INVESTIGATION")
               for cl in DB.claims.values()):
            raise ApiError("ERR_CASE_HAS_OPEN_CLAIMS", "case has open claims")
        for purse in case_purses(case["id"]):
            if ledger_balance(purse["id"]) != 0:
                raise ApiError("ERR_CASE_BALANCE_NONZERO",
                               "every purse must have ledger balance zero to close")
    case["account_status"] = to
    touch(case)
    if to == "CLOSED":
        import util
        now = util.now_dt()
        for purse in case_purses(case["id"]):
            if purse["purse_status"] in ("OPEN", "FROZEN"):
                purse["purse_status"] = "CLOSED"
                touch(purse)
            for posting in DB.postings.values():
                if posting["purse_id"] != purse["id"]:
                    continue
                if posting["posting_status"] == "SCHEDULED":
                    posting["posting_status"] = "FORFEITED"
                    posting["resolved_at"] = now
                    touch(posting)
                    post_entry(purse["id"], "FORFEIT_DEBIT", posting["amount_cents"],
                               posting_id=posting["id"], memo="forfeiture", at=now)
                elif posting["posting_status"] == "AVAILABLE":
                    posting["posting_status"] = "FORFEITED"
                    posting["resolved_at"] = now
                    touch(posting)
        for card in case_cards(case["id"]):
            if card["card_status"] in ("ISSUED", "MAILED", "ACTIVE", "PIN_LOCKED"):
                card["card_status"] = "DEACTIVATED"
                touch(card)
    return ok_object(ser_case(case))


@bp.get("/case-accounts/<cid>/cards")
def list_case_cards(cid):
    role, uid = authed(["StateAdmin", "CardholderServices", "Cardholder"])
    case = get_case(cid)
    cardholder_owns(role, uid, case["id"])
    return list_response(sort_created(case_cards(cid)), ser_card)


@bp.get("/case-accounts/<cid>/claims")
def list_case_claims(cid):
    role, uid = authed(["StateAdmin", "CardholderServices", "Cardholder"])
    case = get_case(cid)
    cardholder_owns(role, uid, case["id"])
    return list_response(sort_created(case_claims(cid)), ser_claim)


@bp.get("/purses")
def list_purses():
    role, uid = authed(["StateAdmin", "CardholderServices", "Cardholder"])
    rows = list(DB.purses.values())
    case_filter = query_filter("case_account_id")
    if role == "Cardholder":
        if case_filter is not None and case_filter != uid:
            raise ApiError("ERR_FORBIDDEN")
        rows = [p for p in rows if p["case_account_id"] == uid]
    elif case_filter is not None:
        rows = [p for p in rows if p["case_account_id"] == case_filter]
    program_filter = query_filter("program_id")
    if program_filter is not None:
        rows = [p for p in rows if p["program_id"] == program_filter]
    status_filter = query_filter("purse_status")
    if status_filter is not None:
        rows = [p for p in rows if p["purse_status"] == status_filter]
    return list_response(sort_created(rows), ser_purse)


@bp.get("/purses/<pid>")
def read_purse(pid):
    role, uid = authed(["StateAdmin", "CardholderServices", "Cardholder"])
    purse = get_purse(pid)
    cardholder_owns(role, uid, purse["case_account_id"])
    return ok_object(ser_purse(purse))


@bp.get("/purses/<pid>/ledger")
def purse_ledger(pid):
    role, uid = authed(["StateAdmin", "CardholderServices", "Cardholder"])
    purse = get_purse(pid)
    cardholder_owns(role, uid, purse["case_account_id"])
    from domain import purse_entries
    rows = purse_entries(pid)
    entry_type = query_filter("entry_type")
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    return list_response(rows, ser_entry)


@bp.get("/purses/<pid>/postings")
def purse_postings(pid):
    role, uid = authed(["StateAdmin", "CardholderServices", "Cardholder"])
    purse = get_purse(pid)
    cardholder_owns(role, uid, purse["case_account_id"])
    rows = [p for p in DB.postings.values() if p["purse_id"] == pid]
    rows.sort(key=lambda p: (p["available_at"], p["created_at"], p["_seq"]))
    status_filter = query_filter("posting_status")
    if status_filter is not None:
        rows = [p for p in rows if p["posting_status"] == status_filter]
    return list_response(rows, ser_posting)
