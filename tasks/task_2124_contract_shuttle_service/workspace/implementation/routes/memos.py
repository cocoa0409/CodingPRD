"""CreditMemo endpoints (PRD 3.7)."""

from flask import Blueprint

import calc
import store
from envelope import created, ok, paginate, pagination
from errors import ApiError
from guards import (ALL_ROLES, authorize, body, equality_filter, id_field,
                    must_exist, validate_body)
from store import touch

bp = Blueprint("memos", __name__)

CREATE_SPEC = [
    id_field("contract_id"),
    {"name": "amount_cents", "kind": "int"},
    {"name": "reason", "kind": "enum",
     "values": ("MISSED_TRIP", "WAIT_SLA_BREACH", "GOODWILL")},
    id_field("trip_id", required=False, nullable=True),
]
VOID_SPEC = [{"name": "voided_reason", "kind": "string", "min_len": 1}]


@bp.post("/credit-memos")
def create_memo():
    authorize(["ClientLiaison"])
    data = validate_body(body(), CREATE_SPEC)
    contract = must_exist(store.contracts, data["contract_id"], "ERR_CONTRACT_NOT_FOUND")
    trip = None
    if data.get("trip_id") is not None:
        trip = must_exist(store.trips, data["trip_id"], "ERR_TRIP_NOT_FOUND")
        if trip["contract_id"] != contract["id"]:
            raise ApiError("ERR_TRIP_CONTRACT_MISMATCH")
    cap = contract["penalty_rate_cents_per_missed_trip"] * calc.MEMO_CAP_MULTIPLIER
    if data["amount_cents"] < 1 or data["amount_cents"] > cap:
        raise ApiError("ERR_MEMO_AMOUNT_EXCEEDS_CAP")

    memo = calc.mint_credit_memo(contract, trip["id"] if trip else None,
                                 data["reason"], data["amount_cents"])
    return created(store.public(memo))


@bp.get("/credit-memos/<mid>")
def get_memo(mid):
    authorize(ALL_ROLES)
    return ok(store.public(must_exist(store.credit_memos, mid, "ERR_MEMO_NOT_FOUND")))


@bp.get("/credit-memos")
def list_memos():
    authorize(ALL_ROLES)
    limit, offset = pagination()
    rows = list(store.credit_memos.values())
    for param in ("contract_id", "trip_id", "applied_report_id", "status", "reason"):
        rows = equality_filter(rows, param, param)
    rows.sort(key=store.sort_key_created)
    return paginate(rows, limit, offset, store.public)


@bp.post("/credit-memos/<mid>/void")
def void_memo(mid):
    authorize(["ContractAdmin"])
    data = validate_body(body(), VOID_SPEC)
    memo = must_exist(store.credit_memos, mid, "ERR_MEMO_NOT_FOUND")
    if memo["status"] != "ISSUED":
        raise ApiError("ERR_MEMO_NOT_ISSUED")

    memo["status"] = "VOIDED"
    memo["voided_reason"] = data["voided_reason"]
    touch(memo)
    contract = store.contracts.get(memo["contract_id"])
    if contract is not None:
        calc.recompute_contract_credit_balance(contract)
    if memo["trip_id"] and memo["reason"] == "MISSED_TRIP":
        trip = store.trips.get(memo["trip_id"])
        if trip is not None and trip["settlement_status"] == "CREDITED":
            trip["settlement_status"] = "UNBILLED"
            touch(trip)
    return ok(store.public(memo))
