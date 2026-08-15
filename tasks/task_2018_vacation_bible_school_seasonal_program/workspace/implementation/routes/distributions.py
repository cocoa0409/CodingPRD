"""Supply distributions: plan / issue / cancel (PRD §3.6)."""

from flask import Blueprint, request

import clock
import store
from auth import authenticate, require_role
from derived import (
    distribution_view,
    blocked_allergens,
    reserved_quantity,
)
from envelope import ok_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ALLERGEN_CONFLICT,
    ERR_CROSS_PROGRAM_REFERENCE,
    ERR_INSUFFICIENT_STOCK,
)
from routes.common import paginate, empty_body, guard_program_writable
from validate import Field, get_body, validate_body, bad

bp = Blueprint("distributions", __name__)

_CREATE_SPEC = {
    "supply_item_id": Field("str", required=True),
    "classroom_id": Field("str", required=True),
    "program_day_id": Field("str", required=True),
    "quantity": Field("int", required=True),
}


def get_distribution_or_404(distribution_id):
    dist = store.get("supply_distributions", distribution_id)
    if dist is None:
        raise_err(ERR_NOT_FOUND, "supply distribution not found")
    return dist


@bp.post("/vbs/supply-distributions")
def create_distribution():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    if data["quantity"] < 1:
        bad("quantity must be >= 1")
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator")
    # P3 existence in payload order: item, classroom, day.
    item = store.get("supply_items", data["supply_item_id"])
    if item is None:
        raise_err(ERR_NOT_FOUND, "supply item not found")
    classroom = store.get("classrooms", data["classroom_id"])
    if classroom is None:
        raise_err(ERR_NOT_FOUND, "classroom not found")
    day = store.get("program_days", data["program_day_id"])
    if day is None:
        raise_err(ERR_NOT_FOUND, "program day not found")
    # P5 safety: the allergen gate fires ahead of state and business checks.
    if item["category"] == "SNACK":
        blocked = blocked_allergens(classroom["id"])
        if set(item["allergen_tags"]) & blocked:
            raise_err(ERR_ALLERGEN_CONFLICT, "snack allergens conflict with enrolled children's plans")
    # P6: archived programs are read-only; the day must be SCHEDULED or OPEN.
    for pid in {item["program_id"], classroom["program_id"], day["program_id"]}:
        guard_program_writable(store.get("programs", pid))
    if day["status"] not in ("SCHEDULED", "OPEN"):
        raise_err(ERR_INVALID_STATE, "distributions may only target a SCHEDULED or OPEN day")
    # P9: item, classroom and day must all belong to the same program.
    if not (item["program_id"] == classroom["program_id"] == day["program_id"]):
        raise_err(ERR_CROSS_PROGRAM_REFERENCE, "item, classroom and day must share one program")
    # P10: stock.
    available = item["quantity_on_hand"] - reserved_quantity(item)
    if data["quantity"] > available:
        raise_err(ERR_INSUFFICIENT_STOCK, "quantity exceeds available stock")
    dist = store.new_record(
        supply_item_id=item["id"],
        classroom_id=classroom["id"],
        program_day_id=day["id"],
        quantity=data["quantity"],
        status="PLANNED",
        issued_at=None,
    )
    store.put("supply_distributions", dist)
    return ok_object(distribution_view(dist), status=201)


@bp.post("/vbs/supply-distributions/<distribution_id>/issue")
def issue_distribution(distribution_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator")
    dist = get_distribution_or_404(distribution_id)
    item = store.get("supply_items", dist["supply_item_id"])
    guard_program_writable(store.get("programs", item["program_id"]) if item else None)
    if dist["status"] != "PLANNED":
        raise_err(ERR_INVALID_STATE, "only a PLANNED distribution may be issued")
    if item is not None:
        item["quantity_on_hand"] -= dist["quantity"]
        store.touch(item)
    dist["status"] = "ISSUED"
    dist["issued_at"] = clock.now()
    store.touch(dist)
    return ok_object(distribution_view(dist))


@bp.post("/vbs/supply-distributions/<distribution_id>/cancel")
def cancel_distribution(distribution_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator")
    dist = get_distribution_or_404(distribution_id)
    item = store.get("supply_items", dist["supply_item_id"])
    guard_program_writable(store.get("programs", item["program_id"]) if item else None)
    if dist["status"] != "PLANNED":
        raise_err(ERR_INVALID_STATE, "only a PLANNED distribution may be cancelled")
    dist["status"] = "CANCELLED"
    store.touch(dist)
    return ok_object(distribution_view(dist))


@bp.get("/vbs/supply-distributions/<distribution_id>")
def get_distribution(distribution_id):
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator", "SafetyOfficer")
    return ok_object(distribution_view(get_distribution_or_404(distribution_id)))


@bp.get("/vbs/supply-distributions")
def list_distributions():
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator", "SafetyOfficer")
    items = list(store.all_of("supply_distributions"))
    supply_item_id = request.args.get("supply_item_id")
    classroom_id = request.args.get("classroom_id")
    program_day_id = request.args.get("program_day_id")
    status = request.args.get("status")
    if supply_item_id is not None:
        items = [d for d in items if d["supply_item_id"] == supply_item_id]
    if classroom_id is not None:
        items = [d for d in items if d["classroom_id"] == classroom_id]
    if program_day_id is not None:
        items = [d for d in items if d["program_day_id"] == program_day_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return paginate(items, distribution_view)
