"""Credit drawdowns: the BASE/ROLLOVER/OVERAGE waterfall and its compensation."""
from decimal import Decimal

from flask import Blueprint, g, request

from db import db, find
from auth import authorize
from errors import err
from response import success, paged_cursor, sort_by_created
from serializers import drawdown as ser_drawdown
from services import engine
from util import now, r6, r2, new_id, as_int

from routes.common import body, req_str, req_dec, req_enum

bp = Blueprint("drawdowns", __name__)

MAX_AMOUNT = Decimal("1000")


def load(drawdown_id):
    record = find(db.drawdowns, drawdown_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "CreditDrawdown not found.")
    return record


@bp.route("/v1/credit-drawdowns", methods=["POST"])
def create_drawdown():
    authorize(g.role, ["DataEngineer", "FinanceController"])
    data = body()
    contract_id = req_str(data, "contract_id")
    contract = find(db.contracts, contract_id)
    if contract is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "CapacityContract not found.")
    warehouse_id = req_str(data, "warehouse_id")
    warehouse = find(db.warehouses, warehouse_id)
    if warehouse is None:
        raise err("ERR_REFERENCE_INVALID", "warehouse_id does not resolve.")
    if warehouse["account_id"] != contract["account_id"]:
        raise err("ERR_REFERENCE_INVALID",
                  "The warehouse is not owned by the contract's account.")
    amount = req_dec(data, "amount_credits")
    source_kind = req_enum(data, "source_kind", engine.SOURCES)
    idem = req_str(data, "idempotency_key")
    expected = data.get("expected_contract_version")

    if amount <= 0:
        raise err("ERR_DRAWDOWN_AMOUNT_RANGE",
                  "amount_credits must be strictly positive.")

    for existing in engine.child_drawdowns(contract_id):
        if existing["idempotency_key"] == idem:
            return success(ser_drawdown(existing), 201)

    if contract["status"] == "DRAFT":
        raise err("ERR_INVALID_STATE", "A DRAFT contract draws nothing.")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", "expected_contract_version is required.")
    if expected != contract["version"]:
        raise err("ERR_STALE_VERSION", "The contract version has advanced.")

    account = find(db.accounts, contract["account_id"])
    if account["account_state"] == "DRAINING":
        raise err("ERR_ACCOUNT_DRAINING", "The owning account is DRAINING.")

    # The contract credit ceiling is §2.10's ninth layer; the single-drawdown
    # amount bounds are its thirteenth, so the ceiling is evaluated first and an
    # earlier layer always wins. §3.4: "A drawdown that would push
    # `drawn_credits` past `base_credits` plus `rolled_over_credits` plus the
    # `rollover_cap_credits` of the active term is refused outright with
    # `ERR_CONTRACT_CREDIT_EXHAUSTED` rather than being silently clipped".
    ceiling = (contract["base_credits"] + contract["rolled_over_credits"]
               + contract["rollover_cap_credits"])
    if contract["drawn_credits"] + amount > ceiling:
        raise err("ERR_CONTRACT_CREDIT_EXHAUSTED",
                  "The drawdown would breach the contract's allowance plus rollover ceiling.")
    if amount > MAX_AMOUNT:
        raise err("ERR_DRAWDOWN_AMOUNT_RANGE",
                  "amount_credits must be at most 1000.")

    ts = now()
    record = {
        "id": new_id(),
        "contract_id": contract_id,
        "warehouse_id": warehouse_id,
        "amount_credits": amount,
        "source_kind": source_kind,
        "status": "ACTIVE",
        "idempotency_key": idem,
        "outcome": "BASE",
        "overage_usd": r2(0),
        "base_portion": r6(0),
        "overage_credits": r6(0),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.drawdowns.append(record)

    base_portion, _roll, overage_credits, overage_usd, outcome = \
        engine.segment_drawdown(contract, record)
    record["base_portion"] = r6(base_portion)
    record["overage_credits"] = r6(overage_credits)
    record["outcome"] = outcome
    record["overage_usd"] = overage_usd

    contract["drawn_credits"] = r6(contract["drawn_credits"] + amount)
    contract["base_consumed_credits"] = r6(contract["base_consumed_credits"] + base_portion)
    contract["drawdown_count"] = len(engine.child_drawdowns(contract_id))
    engine.recompute_contract(contract)
    engine.refresh_contract_posture(contract)
    engine.touch(contract)

    within_allowance = amount - overage_credits
    engine.post_ledger(account["id"], "CONSUMPTION", "CreditDrawdown", record["id"],
                       amount_credits=r6(within_allowance))
    if overage_credits > 0:
        engine.post_ledger(account["id"], "OVERAGE", "CreditDrawdown", record["id"],
                           amount_usd=overage_usd)
    return success(ser_drawdown(record), 201)


@bp.route("/v1/credit-drawdowns", methods=["GET"])
def list_drawdowns():
    authorize(g.role, ["DataEngineer", "FinanceController", "PlatformOperator"])
    items = sort_by_created(db.drawdowns)
    contract_id = request.args.get("contract_id")
    warehouse_id = request.args.get("warehouse_id")
    source_kind = request.args.get("source_kind")
    status = request.args.get("status")
    if contract_id:
        items = [d for d in items if d["contract_id"] == contract_id]
    if warehouse_id:
        items = [d for d in items if d["warehouse_id"] == warehouse_id]
    if source_kind:
        items = [d for d in items if d["source_kind"] == source_kind]
    if status:
        items = [d for d in items if d["status"] == status]

    raw_limit = request.args.get("limit")
    try:
        limit = 10 if raw_limit in (None, "") else int(raw_limit)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")

    cursor = request.args.get("cursor")
    start = 0
    if cursor not in (None, ""):
        for index, row in enumerate(items):
            if row["id"] == cursor:
                start = index + 1
                break
    page = items[start:start + limit]
    has_more = start + limit < len(items)
    next_cursor = page[-1]["id"] if page and has_more else None
    return paged_cursor([ser_drawdown(d) for d in page], limit, len(items),
                        has_more, next_cursor, offset=start)


@bp.route("/v1/credit-drawdowns/<drawdown_id>", methods=["GET"])
def get_drawdown(drawdown_id):
    authorize(g.role, ["DataEngineer", "FinanceController", "PlatformOperator"])
    return success(ser_drawdown(load(drawdown_id)))


@bp.route("/v1/credit-drawdowns/<drawdown_id>/reverse", methods=["POST"])
def reverse(drawdown_id):
    authorize(g.role, ["FinanceController"])
    record = load(drawdown_id)
    contract = find(db.contracts, record["contract_id"])
    if contract is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "CapacityContract not found.")
    if record["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE drawdown can be reversed.")
    if contract["status"] not in ("ACTIVE", "EXHAUSTED", "CLOSED"):
        raise err("ERR_INVALID_STATE", "The contract does not admit a reversal.")

    record["status"] = "REVERSED"
    contract["drawn_credits"] = r6(max(Decimal("0"),
                                       contract["drawn_credits"] - record["amount_credits"]))
    contract["base_consumed_credits"] = r6(max(
        Decimal("0"), contract["base_consumed_credits"] - record["base_portion"]))
    engine.recompute_contract(contract)
    engine.refresh_contract_posture(contract)
    engine.touch(record)
    engine.touch(contract)

    within = record["amount_credits"] - record.get("overage_credits", Decimal("0"))
    engine.post_ledger(contract["account_id"], "CONSUMPTION", "CreditDrawdown",
                       record["id"], amount_credits=r6(-within))
    return success(ser_drawdown(record))
