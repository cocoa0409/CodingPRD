"""Branches, rooms, procured inventory and the logical clock."""

from flask import Blueprint

import derive
import lookup
import services
import store
import validate
from core import clock
from errors import ApiError
from web import Arr, Empty, Obj, endpoint

bp = Blueprint("reference", __name__)

MANAGER = ("ProgramManager",)
STAFF = ("ProgramManager", "ProgramCoordinator")
STAFF_AND_SCREENER = ("ProgramManager", "ProgramCoordinator", "ScreeningOfficer")
EVERY_ROLE = (
    "ProgramManager",
    "ProgramCoordinator",
    "ScreeningOfficer",
    "Reader",
)

ROOM_FEATURES = (
    "WHEELCHAIR_ACCESSIBLE",
    "HEARING_LOOP",
    "ADJUSTABLE_LIGHTING",
    "QUIET_ZONE",
)
ROOM_STATUSES = ("AVAILABLE", "OUT_OF_SERVICE")
LOT_CATEGORIES = ("PRIZE", "SUPPLY")


# ------------------------------------------------------------------ branches

@bp.route("/library/branches/<branch_id>", methods=["GET"])
@endpoint(STAFF_AND_SCREENER)
def get_branch(user_id, role, branch_id):
    return Obj("branches", lookup.branch(branch_id))


@bp.route("/library/branches", methods=["POST"])
@endpoint(MANAGER, mutating=True)
def create_branch(user_id, role):
    payload = validate.body()
    name = validate.string_field(payload, "name")
    code = validate.branch_code(validate.string_field(payload, "branch_code"))
    capacity = validate.integer_field(
        payload, "overlapping_program_capacity", minimum=1
    )
    fee_cap = validate.integer_field(
        payload, "per_program_fee_cap_cents", minimum=0
    )
    for existing in store.DB["branches"].values():
        if existing["branch_code"] == code:
            raise ApiError("ERR_BRANCH_CODE_DUPLICATE")
    branch = store.new_entity(
        "branches",
        {
            "name": name,
            "branch_code": code,
            "overlapping_program_capacity": capacity,
            "per_program_fee_cap_cents": fee_cap,
            "programs_over_budget_count": 0,
        },
    )
    return Obj("branches", branch, 201)


# --------------------------------------------------------------------- rooms

@bp.route("/library/rooms/<room_id>", methods=["GET"])
@endpoint(STAFF)
def get_room(user_id, role, room_id):
    return Obj("rooms", lookup.room(room_id))


@bp.route("/library/rooms", methods=["GET"])
@endpoint(STAFF)
def list_rooms(user_id, role):
    from flask import request

    rooms = store.all_of("rooms")
    branch_id = request.args.get("branch_id")
    status = request.args.get("status")
    if branch_id is not None:
        rooms = [r for r in rooms if r["branch_id"] == branch_id]
    if status is not None:
        rooms = [r for r in rooms if r["status"] == status]
    return Arr("rooms", rooms)


@bp.route("/library/branches/<branch_id>/rooms", methods=["POST"])
@endpoint(MANAGER, mutating=True)
def create_room(user_id, role, branch_id):
    payload = validate.body()
    room_name = validate.string_field(payload, "room_name")
    capacity = validate.integer_field(payload, "capacity_seats", minimum=1)
    setup = validate.integer_field(payload, "min_setup_minutes", minimum=0)
    teardown = validate.integer_field(payload, "min_teardown_minutes", minimum=0)
    features = validate.enum_array_field(
        payload, "accessibility_features", ROOM_FEATURES, default=[]
    )
    status = validate.enum_field(
        payload, "status", ROOM_STATUSES, required=False, default="AVAILABLE"
    )
    branch = lookup.branch(branch_id)
    room = store.new_entity(
        "rooms",
        {
            "branch_id": branch["id"],
            "room_name": room_name,
            "capacity_seats": capacity,
            "min_setup_minutes": setup,
            "min_teardown_minutes": teardown,
            "accessibility_features": features,
            "status": status,
        },
    )
    return Obj("rooms", room, 201)


# ------------------------------------------------------------- inventory lots

@bp.route("/library/inventory-lots/<lot_id>", methods=["GET"])
@endpoint(STAFF)
def get_lot(user_id, role, lot_id):
    return Obj("lots", lookup.lot(lot_id))


@bp.route("/library/inventory-lots", methods=["GET"])
@endpoint(STAFF)
def list_lots(user_id, role):
    from flask import request

    lots = store.all_of("lots")
    branch_id = request.args.get("branch_id")
    category = request.args.get("category")
    sku = request.args.get("sku")
    status = request.args.get("status")
    if branch_id is not None:
        lots = [l for l in lots if l["branch_id"] == branch_id]
    if category is not None:
        lots = [l for l in lots if l["category"] == category]
    if sku is not None:
        lots = [l for l in lots if l["sku"] == sku]
    if status is not None:
        lots = [l for l in lots if derive.lot_status(l) == status]
    return Arr("lots", lots)


@bp.route("/library/inventory-lots", methods=["POST"])
@endpoint(MANAGER, mutating=True)
def create_lot(user_id, role):
    payload = validate.body()
    branch_id = validate.string_field(payload, "branch_id")
    category = validate.enum_field(payload, "category", LOT_CATEGORIES)
    sku = validate.string_field(payload, "sku")
    unit_cost = validate.integer_field(payload, "unit_cost_cents", minimum=0)
    quantity = validate.integer_field(payload, "quantity_procured", minimum=1)
    reuse_pool = validate.boolean_field(payload, "reuse_pool")
    description = validate.string_field(
        payload, "description", required=False, default=None
    )
    branch = lookup.branch(branch_id)
    lot = store.new_entity(
        "lots",
        {
            "branch_id": branch["id"],
            "category": category,
            "sku": sku,
            "description": description,
            "unit_cost_cents": unit_cost,
            "quantity_procured": quantity,
            "reuse_pool": reuse_pool,
            "quantity_reserved": 0,
            "quantity_issued": 0,
        },
    )
    # Procuring a prize lot immediately serves the waiting readers.
    if category == "PRIZE":
        services.promote_deferred_awards(lot)
    return Obj("lots", lot, 201)


# --------------------------------------------------------------------- clock

@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(EVERY_ROLE)
def set_clock(user_id, role):
    payload = validate.body()
    current_utc = validate.instant_field(payload, "current_utc")
    clock.set(current_utc)
    # Setting the clock mutates no entity and recomputes nothing eagerly.
    return Empty(200)
