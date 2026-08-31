"""UPS service contracts: opening, sizing and attachment."""
from flask import Blueprint

import calc
from common import (
    ApiError, DB, authenticate, f_enum, f_enum_list, f_int, f_num, f_str,
    get_body, must, new_row, now_ts, ok, page, public, qp, scope, sort_rows, touch,
)

bp = Blueprint("contracts", __name__, url_prefix="/distribution")

CONTRACT_READERS = ["PlatformAdmin", "SalesRep", "ComplianceOfficer", "Customer"]


@bp.post("/service-contracts")
def create_contract():
    user_id, role = authenticate(["SalesRep", "Customer"])
    body = get_body()
    account_id = f_str(body, "account_id")
    tier = f_enum(body, "coverage_tier", ("BRONZE", "SILVER", "GOLD"))
    load_watts = f_num(body, "load_watts", exclusive_min=0)
    runtime = f_int(body, "required_runtime_minutes", minimum=1)
    voltage = f_num(body, "system_voltage", exclusive_min=0)
    ambient = f_num(body, "ambient_temp_c")
    chemistries = f_enum_list(body, "allowed_chemistries", calc.CHEMISTRIES)
    must("accounts", account_id)
    scope(role, user_id, account_id)

    row = new_row({
        "account_id": account_id,
        "order_id": None,
        "coverage_tier": tier,
        "load_watts": load_watts,
        "required_runtime_minutes": runtime,
        "system_voltage": voltage,
        "ambient_temp_c": ambient,
        "allowed_chemistries": list(chemistries),
        "dc_load_amps": 0.0,
        "required_peukert_ah": 0.0,
        "temp_derate_factor": 0.0,
        "sized_battery_model_id": None,
        "sized_string_count": 0,
        "sized_units_per_string": 0,
        "sized_unit_count": 0,
        "covered_value_cents": 0,
        "monthly_fee_cents": 0,
        "prepay_total_cents": 0,
        "attached_at": None,
        "status": "DRAFT",
    })
    DB.service_contracts[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/service-contracts/<contract_id>")
def read_contract(contract_id):
    user_id, role = authenticate(CONTRACT_READERS)
    row = must("service_contracts", contract_id)
    scope(role, user_id, row["account_id"])
    return ok(public(row))


@bp.get("/service-contracts")
def list_contracts():
    user_id, role = authenticate(CONTRACT_READERS)
    rows = list(DB.service_contracts.values())
    if role == "Customer":
        requested = qp("account_id")
        if requested is not None and requested != user_id:
            raise ApiError("ERR_ACCOUNT_SCOPE_VIOLATION", "customer may only list its own account")
        rows = [r for r in rows if r["account_id"] == user_id]
    for name in ("account_id", "order_id", "sized_battery_model_id", "status"):
        value = qp(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return page(rows, public)


@bp.post("/service-contracts/<contract_id>/size")
def size_contract(contract_id):
    authenticate(["SalesRep", "PlatformAdmin"])
    row = must("service_contracts", contract_id)
    get_body()
    if row["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "contract is not in DRAFT")
    sized = calc.size_contract(row)
    row.update(sized)
    row["status"] = "SIZED"
    touch(row)
    return ok(public(row))


@bp.post("/service-contracts/<contract_id>/attach")
def attach_contract(contract_id):
    authenticate(["SalesRep"])
    row = must("service_contracts", contract_id)
    body = get_body()
    order_id = f_str(body, "order_id")
    expected_version = f_int(body, "expected_order_version")
    order = must("orders", order_id)

    if expected_version != int(order["version"]):
        raise ApiError("ERR_STALE_VERSION", "expected_order_version does not match the order")
    if row["status"] != "SIZED":
        raise ApiError("ERR_INVALID_STATE", "contract is not SIZED")
    if order["fulfillment_status"] not in ("SUBMITTED", "ALLOCATED"):
        raise ApiError("ERR_INVALID_STATE", "order is not open for contract attachment")
    if order["account_id"] != row["account_id"]:
        raise ApiError("ERR_ACCOUNT_MISMATCH", "order belongs to a different account")

    for other in sort_rows(list(DB.service_contracts.values())):
        if other["id"] == row["id"]:
            continue
        if other.get("order_id") == order_id and other["status"] in ("ATTACHED", "ACTIVE"):
            other["status"] = "SUPERSEDED"
            touch(other)

    account = DB.accounts[order["account_id"]]
    previous_total = int(order["total_cents"])
    order["service_contract_fee_cents"] = int(row["prepay_total_cents"])
    order["total_cents"] = calc.assemble_total(order)
    touch(order)
    calc.adjust_receivable(account, int(order["total_cents"]) - previous_total)

    row["order_id"] = order_id
    row["attached_at"] = now_ts()
    row["status"] = "ATTACHED"
    touch(row)
    return ok(public(row))
