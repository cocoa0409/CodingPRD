"""Core returns: declaration, inspection, dispute and credit issuance."""
from datetime import timedelta

from flask import Blueprint

import calc
from common import (
    ApiError, DB, D, authenticate, f_int, f_str, get_body, must, new_row,
    now_date, num, ok, page, parse_date, public, qp, rhu, scope, sort_rows, touch,
)

bp = Blueprint("core_returns", __name__, url_prefix="/distribution")

CORE_READERS = ["PlatformAdmin", "SalesRep", "WarehouseOperator", "ComplianceOfficer", "Customer"]
COMMITTED = ("SUBMITTED", "INSPECTED", "DISPUTED", "CREDITED")


def _matching_lines(order_id, model_id):
    return [l for l in calc.order_lines(order_id) if l["battery_model_id"] == model_id]


def _earliest_due(lines):
    dues = [l["core_due_by"] for l in lines if l.get("core_due_by")]
    if not dues:
        return None
    return parse_date(sorted(dues)[0])


@bp.post("/core-returns")
def create_core_return():
    user_id, role = authenticate(["SalesRep", "Customer"])
    body = get_body()
    account_id = f_str(body, "account_id")
    order_id = f_str(body, "order_id")
    model_id = f_str(body, "battery_model_id")
    declared = f_int(body, "declared_core_count", minimum=1)
    must("accounts", account_id)
    order = must("orders", order_id)
    model = must("battery_models", model_id)
    scope(role, user_id, account_id)

    if account_id != order["account_id"]:
        raise ApiError("ERR_ACCOUNT_MISMATCH", "account does not own the source order")
    if order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_ORDER_NOT_DELIVERED", "source order is not DELIVERED")

    lines = _matching_lines(order_id, model_id)
    earliest = _earliest_due(lines)
    if earliest is not None:
        deadline = earliest + timedelta(days=calc.CORE_RETURN_GRACE_DAYS)
        if DB.clock.date() > deadline:
            raise ApiError("ERR_CORE_RETURN_WINDOW_CLOSED", "the core return window has closed")

    promised = sum(int(l["core_expected_count"]) for l in lines)
    committed = 0
    for other in DB.core_returns.values():
        if other["order_id"] == order_id and other["battery_model_id"] == model_id \
                and other["status"] in COMMITTED:
            committed += int(other["declared_core_count"])
    if declared > promised - committed:
        raise ApiError("ERR_CORE_COUNT_EXCEEDS_PROMISE", "declared core count exceeds the promise")

    late = bool(earliest is not None and DB.clock.date() > earliest)
    row = new_row({
        "account_id": account_id,
        "order_id": order_id,
        "battery_model_id": model_id,
        "declared_core_count": declared,
        "accepted_core_count": 0,
        "inspection_round": 0,
        "late_return": late,
        "provisional_credit_cents": declared * int(model["core_deposit_cents"]),
        "lead_recovered_kg": 0.0,
        "scrap_value_cents": 0,
        "final_credit_cents": 0,
        "dispute_reason": None,
        "status": "SUBMITTED",
        "disposal_manifest_id": None,
    })
    DB.core_returns[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/core-returns/<core_return_id>")
def read_core_return(core_return_id):
    user_id, role = authenticate(CORE_READERS)
    row = must("core_returns", core_return_id)
    scope(role, user_id, row["account_id"])
    return ok(public(row))


@bp.get("/core-returns")
def list_core_returns():
    user_id, role = authenticate(CORE_READERS)
    rows = list(DB.core_returns.values())
    if role == "Customer":
        requested = qp("account_id")
        if requested is not None and requested != user_id:
            raise ApiError("ERR_ACCOUNT_SCOPE_VIOLATION", "customer may only list its own account")
        rows = [r for r in rows if r["account_id"] == user_id]
    for name in ("account_id", "order_id", "battery_model_id", "disposal_manifest_id", "status"):
        value = qp(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return page(rows, public)


@bp.post("/core-returns/<core_return_id>/inspect")
def inspect_core_return(core_return_id):
    authenticate(["WarehouseOperator"])
    row = must("core_returns", core_return_id)
    body = get_body()
    accepted = f_int(body, "accepted_core_count", minimum=0)
    if accepted > int(row["declared_core_count"]):
        raise ApiError("ERR_INVALID_REQUEST", "accepted_core_count may not exceed declared_core_count")
    if row["status"] not in ("SUBMITTED", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE", "core return is not open for inspection")

    model = DB.battery_models[row["battery_model_id"]]
    row["inspection_round"] = int(row["inspection_round"]) + 1
    row["accepted_core_count"] = accepted
    if accepted >= 1:
        lead, scrap = calc.core_lead_recovery(accepted, model)
        row["lead_recovered_kg"] = lead
        row["scrap_value_cents"] = scrap
        row["status"] = "INSPECTED"
    else:
        row["lead_recovered_kg"] = 0.0
        row["scrap_value_cents"] = 0
        row["final_credit_cents"] = 0
        row["status"] = "REJECTED"
    touch(row)
    return ok(public(row))


@bp.post("/core-returns/<core_return_id>/dispute")
def dispute_core_return(core_return_id):
    user_id, role = authenticate(["Customer", "SalesRep"])
    row = must("core_returns", core_return_id)
    body = get_body()
    reason = f_str(body, "dispute_reason")
    scope(role, user_id, row["account_id"])
    if row["status"] != "INSPECTED":
        raise ApiError("ERR_INVALID_STATE", "core return is not INSPECTED")
    if int(row["inspection_round"]) >= calc.MAX_INSPECTION_ROUNDS:
        raise ApiError("ERR_DISPUTE_ROUNDS_EXHAUSTED", "dispute rounds exhausted")
    row["dispute_reason"] = reason
    row["status"] = "DISPUTED"
    touch(row)
    return ok(public(row))


@bp.post("/core-returns/<core_return_id>/credit")
def credit_core_return(core_return_id):
    authenticate(["SalesRep", "PlatformAdmin"])
    row = must("core_returns", core_return_id)
    get_body()
    if row["status"] != "INSPECTED":
        raise ApiError("ERR_INVALID_STATE", "core return is not INSPECTED")

    model = DB.battery_models[row["battery_model_id"]]
    account = DB.accounts[row["account_id"]]
    final = calc.assayed_final_credit(row, model)
    row["final_credit_cents"] = final
    row["status"] = "CREDITED"
    touch(row)

    balance = int(account["core_deposit_balance_cents"]) - final
    account["core_deposit_balance_cents"] = max(0, balance)
    account["lifetime_lead_recovered_kg"] = num(
        D(account["lifetime_lead_recovered_kg"]) + D(row["lead_recovered_kg"]), 3)
    touch(account)
    calc.apply_credit_release(account)
    return ok(public(row))
