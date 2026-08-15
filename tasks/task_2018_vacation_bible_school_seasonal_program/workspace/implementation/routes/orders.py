"""Supply orders: kit ordering against the program budget (PRD §3.6)."""

from flask import Blueprint, request

import store
from auth import authenticate, require_role
from derived import supply_order_view, kit_required_final, budget_remaining_cents
from envelope import ok_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_KIT_QUANTITY_SHORT,
    ERR_BUDGET_EXCEEDED,
)
from routes.common import paginate, empty_body, guard_program_writable
from validate import Field, get_body, validate_body, bad

bp = Blueprint("orders", __name__)

_CREATE_SPEC = {
    "program_id": Field("str", required=True),
    "kit_name": Field("str", required=True),
    "vendor": Field("str", required=True),
    "quantity": Field("int", required=True),
    "unit_cost_cents": Field("int", required=True),
}

_PATCH_SPEC = {
    "kit_name": Field("str"),
    "vendor": Field("str"),
    "quantity": Field("int"),
    "unit_cost_cents": Field("int"),
}


def get_order_or_404(order_id):
    order = store.get("supply_orders", order_id)
    if order is None:
        raise_err(ERR_NOT_FOUND, "supply order not found")
    return order


@bp.post("/vbs/supply-orders")
def create_order():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    if data["quantity"] < 1:
        bad("quantity must be >= 1")
    if data["unit_cost_cents"] < 0:
        bad("unit_cost_cents must be >= 0")
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    program = store.get("programs", data["program_id"])
    if program is None:
        raise_err(ERR_NOT_FOUND, "program not found")
    guard_program_writable(program)
    order = store.new_record(
        program_id=program["id"],
        kit_name=data["kit_name"],
        vendor=data["vendor"],
        quantity=data["quantity"],
        unit_cost_cents=data["unit_cost_cents"],
        status="DRAFT",
    )
    store.put("supply_orders", order)
    return ok_object(supply_order_view(order), status=201)


@bp.patch("/vbs/supply-orders/<order_id>")
def patch_order(order_id):
    body = get_body()
    data = validate_body(body, _PATCH_SPEC)
    if "quantity" in data and data["quantity"] < 1:
        bad("quantity must be >= 1")
    if "unit_cost_cents" in data and data["unit_cost_cents"] < 0:
        bad("unit_cost_cents must be >= 0")
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    order = get_order_or_404(order_id)
    guard_program_writable(store.get("programs", order["program_id"]))
    if order["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "only a DRAFT order may be edited")
    for key in ("kit_name", "vendor", "quantity", "unit_cost_cents"):
        if key in data:
            order[key] = data[key]
    store.touch(order)
    return ok_object(supply_order_view(order))


@bp.post("/vbs/supply-orders/<order_id>/submit")
def submit_order(order_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    order = get_order_or_404(order_id)
    program = store.get("programs", order["program_id"])
    guard_program_writable(program)
    if order["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "only a DRAFT order may be submitted")
    if order["quantity"] < kit_required_final(program):
        raise_err(ERR_KIT_QUANTITY_SHORT, "quantity is below the final kit requirement")
    order["status"] = "SUBMITTED"
    store.touch(order)
    return ok_object(supply_order_view(order))


@bp.post("/vbs/supply-orders/<order_id>/return-for-revision")
def return_order(order_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    order = get_order_or_404(order_id)
    guard_program_writable(store.get("programs", order["program_id"]))
    if order["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "only a SUBMITTED order may be returned for revision")
    order["status"] = "DRAFT"
    store.touch(order)
    return ok_object(supply_order_view(order))


@bp.post("/vbs/supply-orders/<order_id>/approve")
def approve_order(order_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    order = get_order_or_404(order_id)
    program = store.get("programs", order["program_id"])
    guard_program_writable(program)
    if order["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "only a SUBMITTED order may be approved")
    total = order["quantity"] * order["unit_cost_cents"]
    if total > budget_remaining_cents(program):
        raise_err(ERR_BUDGET_EXCEEDED, "order total exceeds the remaining budget")
    order["status"] = "APPROVED"
    store.touch(order)
    return ok_object(supply_order_view(order))


@bp.post("/vbs/supply-orders/<order_id>/cancel")
def cancel_order(order_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    order = get_order_or_404(order_id)
    guard_program_writable(store.get("programs", order["program_id"]))
    if order["status"] not in ("DRAFT", "SUBMITTED"):
        raise_err(ERR_INVALID_STATE, "only a DRAFT or SUBMITTED order may be cancelled")
    order["status"] = "CANCELLED"
    store.touch(order)
    return ok_object(supply_order_view(order))


@bp.get("/vbs/supply-orders/<order_id>")
def get_order(order_id):
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator")
    return ok_object(supply_order_view(get_order_or_404(order_id)))


@bp.get("/vbs/supply-orders")
def list_orders():
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator")
    items = list(store.all_of("supply_orders"))
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [o for o in items if o["program_id"] == program_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return paginate(items, supply_order_view)
