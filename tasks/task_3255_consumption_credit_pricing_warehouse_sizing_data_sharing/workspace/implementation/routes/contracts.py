"""Capacity contracts: activation, renewal, closure and rollover terms."""
from decimal import Decimal

from flask import Blueprint, g, request

from db import db, find
from auth import authorize
from errors import err
from response import success, paged, sort_by_created, pagination
from serializers import contract as ser_contract
from services import engine
from util import now, r6, r2, new_id, overlaps, parse_iso

from routes.common import (body, req_str, req_dec, req_iso, opt_dec, opt_enum,
                           required, MISSING)

bp = Blueprint("contracts", __name__)


def load(contract_id):
    record = find(db.contracts, contract_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "CapacityContract not found.")
    return record


def term_conflicts(account_id, start, end, exclude_id=None):
    for other in db.contracts:
        if other["account_id"] != account_id:
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if overlaps(start, end, other["term_start"], other["term_end"]):
            return True
    return False


@bp.route("/v1/capacity-contracts", methods=["POST"])
def create_contract():
    authorize(g.role, ["FinanceController"])
    data = body()
    account_id = req_str(data, "account_id")
    account = find(db.accounts, account_id)
    if account is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Account not found.")
    term_start = req_iso(data, "term_start")
    term_end = req_iso(data, "term_end")
    base_credits = req_dec(data, "base_credits")
    overage_rate = req_dec(data, "overage_rate_per_credit")
    rollover_cap = req_dec(data, "rollover_cap_credits")
    currency = opt_enum(data, "currency", engine.CURRENCIES, "USD")
    if not term_end > term_start:
        raise err("ERR_TERM_OVERLAP", "term_end must be strictly after term_start.")
    if base_credits <= 0 or rollover_cap <= 0 or overage_rate <= 0:
        raise err("ERR_INVALID_REQUEST",
                  "base_credits, overage_rate_per_credit and rollover_cap_credits must be positive.")
    if term_conflicts(account_id, term_start, term_end):
        raise err("ERR_TERM_OVERLAP",
                  "Contract terms of the same account may not overlap.")
    ts = now()
    record = {
        "id": new_id(),
        "account_id": account_id,
        "term_start": term_start,
        "term_end": term_end,
        "base_credits": base_credits,
        "overage_rate_per_credit": overage_rate,
        "rollover_cap_credits": rollover_cap,
        "currency": currency,
        "status": "DRAFT",
        "drawdown_count": 0,
        "remaining_credits": r6(0),
        "drawn_credits": r6(0),
        "rolled_over_credits": r6(0),
        "base_consumed_credits": r6(0),
        "term_end_remaining_credits": r6(0),
        "activated_by_user_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.contracts.append(record)
    return success(ser_contract(record), 201)


@bp.route("/v1/capacity-contracts", methods=["GET"])
def list_contracts():
    authorize(g.role, ["FinanceController", "PlatformOperator", "DataEngineer"])
    items = sort_by_created(db.contracts)
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id:
        items = [c for c in items if c["account_id"] == account_id]
    if status:
        items = [c for c in items if c["status"] == status]
    limit, offset = pagination()
    return paged([ser_contract(c) for c in items], limit, offset)


@bp.route("/v1/capacity-contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    authorize(g.role, ["FinanceController", "PlatformOperator", "DataEngineer"])
    return success(ser_contract(load(contract_id)))


@bp.route("/v1/capacity-contracts/<contract_id>/activate", methods=["POST"])
def activate(contract_id):
    authorize(g.role, ["FinanceController"])
    contract = load(contract_id)
    if contract["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT contract can be activated.")
    if not contract["term_end"] > contract["term_start"]:
        raise err("ERR_TERM_OVERLAP", "term_end must be strictly after term_start.")
    if contract["base_credits"] <= 0 or contract["rollover_cap_credits"] <= 0:
        raise err("ERR_INVALID_REQUEST", "base_credits and rollover_cap_credits must be positive.")
    contract["status"] = "ACTIVE"
    engine.recompute_contract(contract)
    contract["activated_by_user_id"] = g.user_id
    engine.touch(contract)
    return success(ser_contract(contract))


@bp.route("/v1/capacity-contracts/<contract_id>/renew", methods=["POST"])
def renew(contract_id):
    authorize(g.role, ["FinanceController"])
    contract = load(contract_id)
    data = body()
    new_start = req_iso(data, "new_term_start")
    new_end = req_iso(data, "new_term_end")
    new_base = req_dec(data, "base_credits")
    new_overage = opt_dec(data, "overage_rate_per_credit", None)

    if contract["status"] != "EXPIRED":
        raise err("ERR_INVALID_STATE", "Only an EXPIRED contract can be renewed.")
    if not (new_start == contract["term_end"] and new_end > contract["term_end"]):
        raise err("ERR_TERM_OVERLAP",
                  "Renewal terms must be adjacent and non-overlapping.")
    if new_base <= 0:
        raise err("ERR_INVALID_REQUEST", "base_credits must be positive.")
    if term_conflicts(contract["account_id"], new_start, new_end,
                      exclude_id=contract["id"]):
        raise err("ERR_TERM_OVERLAP",
                  "Renewal terms of the same account may not overlap.")

    prior_rolled = contract["rolled_over_credits"]
    basis = contract["term_end_remaining_credits"]
    pct = r6(basis / contract["rollover_cap_credits"] * Decimal("100")) \
        if contract["rollover_cap_credits"] > 0 else Decimal("0")
    rolled = r6(min(pct * contract["rollover_cap_credits"] / Decimal("100"),
                    contract["rollover_cap_credits"]))

    contract["term_start"] = new_start
    contract["term_end"] = new_end
    contract["base_credits"] = new_base
    if new_overage is not None:
        contract["overage_rate_per_credit"] = new_overage
    contract["rolled_over_credits"] = rolled
    contract["drawdown_count"] = 0
    contract["drawn_credits"] = r6(0)
    contract["base_consumed_credits"] = r6(0)
    contract["term_end_remaining_credits"] = r6(0)
    contract["status"] = "ACTIVE"

    delta = rolled - prior_rolled
    if delta != 0:
        engine.post_ledger(contract["account_id"], "ROLLOVER", "CapacityContract",
                           contract["id"], amount_credits=delta, amount_usd=Decimal("0"))
    engine.recompute_contract(contract)
    engine.touch(contract)
    return success(ser_contract(contract))


@bp.route("/v1/capacity-contracts/<contract_id>/close", methods=["POST"])
def close(contract_id):
    authorize(g.role, ["FinanceController"])
    contract = load(contract_id)
    if contract["status"] not in ("ACTIVE", "EXPIRED", "EXHAUSTED"):
        raise err("ERR_INVALID_STATE", "The contract cannot be closed from its current state.")
    if contract["activated_by_user_id"] is not None and \
            contract["activated_by_user_id"] == g.user_id:
        raise err("ERR_ROLE_CONFLICT",
                  "The operator who activated the contract cannot close it.")
    contract["status"] = "CLOSED"
    engine.touch(contract)
    return success(ser_contract(contract))
