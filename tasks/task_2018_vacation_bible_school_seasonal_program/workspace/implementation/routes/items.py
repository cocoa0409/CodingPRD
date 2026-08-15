"""Supply items: stock room (PRD §3.6)."""

from flask import Blueprint, request

import store
from auth import authenticate, require_role
from derived import supply_item_view
from envelope import ok_object
from errors import raise_err, ERR_NOT_FOUND
from routes.common import paginate, guard_program_writable
from validate import Field, get_body, validate_body, bad

bp = Blueprint("items", __name__)

_CREATE_SPEC = {
    "program_id": Field("str", required=True),
    "name": Field("str", required=True),
    "category": Field("enum", enum={"SNACK", "CRAFT"}, required=True),
    "unit": Field("str", required=True),
    "quantity_on_hand": Field("int", required=True),
    "allergen_tags": Field("allergens", default=list),
    "restock_threshold": Field("int", default=0),
}

_RESTOCK_SPEC = {
    "additional_quantity": Field("int", required=True),
}


def get_item_or_404(item_id):
    item = store.get("supply_items", item_id)
    if item is None:
        raise_err(ERR_NOT_FOUND, "supply item not found")
    return item


@bp.post("/vbs/supply-items")
def create_item():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    if data["quantity_on_hand"] < 0:
        bad("quantity_on_hand must be >= 0")
    if data["restock_threshold"] < 0:
        bad("restock_threshold must be >= 0")
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    program = store.get("programs", data["program_id"])
    if program is None:
        raise_err(ERR_NOT_FOUND, "program not found")
    guard_program_writable(program)
    item = store.new_record(
        program_id=program["id"],
        name=data["name"],
        category=data["category"],
        unit=data["unit"],
        quantity_on_hand=data["quantity_on_hand"],
        allergen_tags=list(data["allergen_tags"]),
        restock_threshold=data["restock_threshold"],
    )
    store.put("supply_items", item)
    return ok_object(supply_item_view(item), status=201)


@bp.get("/vbs/supply-items/<item_id>")
def get_item(item_id):
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator", "SafetyOfficer")
    return ok_object(supply_item_view(get_item_or_404(item_id)))


@bp.get("/vbs/supply-items")
def list_items():
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator", "SafetyOfficer")
    items = list(store.all_of("supply_items"))
    program_id = request.args.get("program_id")
    category = request.args.get("category")
    if program_id is not None:
        items = [i for i in items if i["program_id"] == program_id]
    if category is not None:
        items = [i for i in items if i["category"] == category]
    return paginate(items, supply_item_view)


@bp.post("/vbs/supply-items/<item_id>/restock")
def restock_item(item_id):
    body = get_body()
    data = validate_body(body, _RESTOCK_SPEC)
    if data["additional_quantity"] < 1:
        bad("additional_quantity must be >= 1")
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    item = get_item_or_404(item_id)
    guard_program_writable(store.get("programs", item["program_id"]))
    item["quantity_on_hand"] += data["additional_quantity"]
    store.touch(item)
    return ok_object(supply_item_view(item))
