"""RebateProgram / ProgramItem routes (PRD 3.2)."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import (FINANCE_ADMIN, FRAUD_ANALYST, GUEST_SERVICE,
                        STORE_ADMIN, authenticate, get_body, opt_int,
                        query_param, req_int, req_number, req_string,
                        req_date_string)
from response import object_response
from routes.common import paginated
from serialize import program_out, program_item_out
from services import lookup, temporal

bp = Blueprint("programs", __name__)

READ_ROLES = [STORE_ADMIN, GUEST_SERVICE, FRAUD_ANALYST, FINANCE_ADMIN]


def _load_program(store_id, program_id):
    """Existence + nesting (ladder 3) then lazy auto-close (PRD 3.2)."""
    lookup.store(store_id)
    return temporal.refresh_program_status(
        lookup.program_in_store(store_id, program_id))


# ---------------------------------------------------------------------------
# Store-scoped program surface
# ---------------------------------------------------------------------------
@bp.route("/stores/<store_id>/rebate-programs", methods=["POST"])
def create_program(store_id):
    authenticate([STORE_ADMIN])
    store = lookup.store(store_id)
    body = get_body()

    name = req_string(body, "name")
    week_start = req_date_string(body, "week_start_date")
    week_end = req_date_string(body, "week_end_date")

    program = db.base_record()
    program.update({
        "store_id": store["id"],
        "name": name,
        "week_start_date": week_start.isoformat(),
        "week_end_date": week_end.isoformat(),
        "status": "DRAFT",
    })
    db.programs[program["id"]] = program
    return object_response(program_out(program), 201)


@bp.route("/stores/<store_id>/rebate-programs", methods=["GET"])
def list_programs(store_id):
    authenticate(READ_ROLES)
    lookup.store(store_id)
    temporal.refresh_store_programs(store_id)
    status = query_param("status")
    records = [p for p in db.ordered(db.programs) if p["store_id"] == store_id]
    if status is not None:
        records = [p for p in records if p["status"] == status]
    return paginated(records, program_out)


@bp.route("/stores/<store_id>/rebate-programs/<program_id>", methods=["GET"])
def get_program(store_id, program_id):
    authenticate(READ_ROLES)
    return object_response(program_out(_load_program(store_id, program_id)))


@bp.route("/stores/<store_id>/rebate-programs/<program_id>/items",
          methods=["POST"])
def add_program_item(store_id, program_id):
    authenticate([STORE_ADMIN])
    program = _load_program(store_id, program_id)
    body = get_body()

    sku = req_string(body, "sku")
    rebate_pct = req_number(body, "rebate_pct", minimum=0, maximum=1,
                            minimum_exclusive=True)

    excluded_categories = body.get("excluded_categories")
    if excluded_categories is None:
        excluded_categories = []
    if not isinstance(excluded_categories, list) or any(
            not isinstance(c, str) for c in excluded_categories):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'excluded_categories' must be an array of "
                       "strings")

    min_quantity = opt_int(body, "min_quantity", default=1, minimum=1)

    per_receipt_cap_cents = None
    if "per_receipt_cap_cents" in body and body["per_receipt_cap_cents"] is not None:
        per_receipt_cap_cents = req_int(body, "per_receipt_cap_cents",
                                        minimum=1)

    if program["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "Items may only be added to a DRAFT program")

    item = db.base_record()
    item.update({
        "store_id": store_id,
        "program_id": program["id"],
        "sku": sku,
        "rebate_pct": rebate_pct,
        "excluded_categories": excluded_categories,
        "min_quantity": min_quantity,
        "per_receipt_cap_cents": per_receipt_cap_cents,
    })
    db.program_items[item["id"]] = item
    return object_response(program_item_out(item), 201)


@bp.route("/stores/<store_id>/rebate-programs/<program_id>/items",
          methods=["GET"])
def list_program_items(store_id, program_id):
    authenticate(READ_ROLES)
    program = _load_program(store_id, program_id)
    items = [i for i in db.ordered(db.program_items)
             if i["program_id"] == program["id"]]
    return paginated(items, program_item_out)


@bp.route("/stores/<store_id>/rebate-programs/<program_id>/activate",
          methods=["POST"])
def activate_program(store_id, program_id):
    authenticate([STORE_ADMIN])
    store = lookup.store(store_id)
    program = _load_program(store_id, program_id)
    get_body()

    if program["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a DRAFT program may be activated")

    # PRD 3.2 pins the activation check order: empty -> overlap -> past.
    items = [i for i in db.program_items.values()
             if i["program_id"] == program["id"]]
    if not items:
        raise ApiError("ERR_PROGRAM_EMPTY",
                       "Program activation requires at least one program item")

    start = temporal.week_open(program)
    end = temporal.week_close(program)
    for other in db.programs.values():
        if other["id"] == program["id"] or other["store_id"] != store_id:
            continue
        temporal.refresh_program_status(other)
        if other["status"] != "ACTIVE":
            continue
        o_start = temporal.week_open(other)
        o_end = temporal.week_close(other)
        # Adjacency (end == other's start) is NOT an overlap.
        if start < o_end and o_start < end:
            raise ApiError("ERR_PROGRAM_WEEK_OVERLAP",
                           "Another ACTIVE program overlaps this advertised "
                           "week")

    if db.clock_now() >= end:
        raise ApiError("ERR_PROGRAM_WEEK_PAST",
                       "The advertised week has already fully passed")

    program["status"] = "ACTIVE"
    db.touch(program)
    return object_response(program_out(program))


@bp.route("/stores/<store_id>/rebate-programs/<program_id>/close",
          methods=["POST"])
def close_program(store_id, program_id):
    authenticate([STORE_ADMIN])
    program = _load_program(store_id, program_id)
    get_body()

    if program["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an ACTIVE program may be closed")

    program["status"] = "CLOSED"
    db.touch(program)
    return object_response(program_out(program))


# ---------------------------------------------------------------------------
# Flat canonical reads
# ---------------------------------------------------------------------------
@bp.route("/rebate-programs", methods=["GET"])
def list_all_programs():
    authenticate(READ_ROLES)
    for prog in list(db.programs.values()):
        temporal.refresh_program_status(prog)
    return paginated(db.ordered(db.programs), program_out)


@bp.route("/rebate-programs/<program_id>", methods=["GET"])
def get_program_flat(program_id):
    authenticate(READ_ROLES)
    program = temporal.refresh_program_status(lookup.program(program_id))
    return object_response(program_out(program))


@bp.route("/program-items", methods=["GET"])
def list_all_program_items():
    authenticate(READ_ROLES)
    program_id = query_param("program_id")
    items = db.ordered(db.program_items)
    if program_id is not None:
        items = [i for i in items if i["program_id"] == program_id]
    return paginated(items, program_item_out)


@bp.route("/program-items/<item_id>", methods=["GET"])
def get_program_item_flat(item_id):
    authenticate(READ_ROLES)
    return object_response(program_item_out(lookup.program_item(item_id)))
