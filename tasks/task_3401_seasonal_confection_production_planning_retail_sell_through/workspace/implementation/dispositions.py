"""DispositionOrder routes: propose, read, list, approve (segregation of
duties + cannibalization guard), execute (consume quarantined lots, settle
recovered value per channel)."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db, touch
from domain import (
    DISPOSITION_CHANNELS, MIN_MARKDOWN_PCT, MAX_MARKDOWN_PCT,
    CANNIBALIZATION_FLOOR, SECONDARY_RECOVERY_PCT, round_cents,
    get_disposition, ser_disposition, quarantined_units_at, lot_draw_order,
)
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_PROGRAM_NOT_FOUND, ERR_PRODUCT_NOT_FOUND,
    ERR_WAREHOUSE_NOT_FOUND, ERR_INVALID_STATE, ERR_BRAND_PROTECTION,
    ERR_PRODUCT_PROGRAM_MISMATCH, ERR_MARKDOWN_OUT_OF_RANGE,
    ERR_DISPOSITION_EXCEEDS_QUARANTINE, ERR_SEGREGATION_OF_DUTIES,
    ERR_CANNIBALIZATION_GUARD, ERR_DISPOSITION_WINDOW_CLOSED,
)
from middleware import authorize, ROLE_CATEGORY_MANAGER, ROLE_LOGISTICS_COORDINATOR, ALL_ROLES
from programs import _create_entity
from respond import ok, created, ok_list, paginate, parse_pagination
from validate import json_body, v_str, v_int, v_enum, v_num

bp = Blueprint("dispositions", __name__)

APPROVE_DECISIONS = ("APPROVE", "REJECT")


@bp.post("/confection/disposition-orders")
def propose_disposition():
    data = json_body()
    program_id = v_str(data, "program_id")
    product_id = v_str(data, "product_id")
    warehouse_id = v_str(data, "warehouse_id")
    units = v_int(data, "units", min_v=1)
    channel = v_enum(data, "channel", DISPOSITION_CHANNELS)
    markdown_pct = v_num(data, "markdown_pct", required=False)

    actor = authorize(ROLE_CATEGORY_MANAGER)

    # Body FKs in declared input order: program_id, product_id, warehouse_id.
    program = db.programs.get(program_id)
    if program is None:
        raise ApiError(404, ERR_PROGRAM_NOT_FOUND,
                       "SeasonalProgram %s does not exist" % program_id)
    product = db.products.get(product_id)
    if product is None:
        raise ApiError(404, ERR_PRODUCT_NOT_FOUND,
                       "Product %s does not exist" % product_id)
    if warehouse_id not in db.warehouses:
        raise ApiError(404, ERR_WAREHOUSE_NOT_FOUND,
                       "Warehouse %s does not exist" % warehouse_id)

    # State (priority 7): the program must be in DISPOSITION.
    if program["status"] != "DISPOSITION":
        raise ApiError(409, ERR_INVALID_STATE,
                       "dispositions may only be proposed while the program is in DISPOSITION")

    # Safety (priority 8): brand protection is absolute.
    if channel == "SECONDARY" and product["brand_protected"]:
        raise ApiError(422, ERR_BRAND_PROTECTION,
                       "a brand_protected product may never be diverted to the SECONDARY channel")

    # Structural (priority 10), in the PRD 3.9 prose order.
    if product["kind"] != "SEASONAL" or product["program_id"] != program["id"]:
        raise ApiError(422, ERR_PRODUCT_PROGRAM_MISMATCH,
                       "the product must be a SEASONAL product of this program")
    if units > quarantined_units_at(product_id, warehouse_id):
        raise ApiError(422, ERR_DISPOSITION_EXCEEDS_QUARANTINE,
                       "units exceed the quarantined stock of the product at the warehouse")
    if channel == "MARKDOWN":
        if markdown_pct is None:
            raise ApiError(422, ERR_MARKDOWN_OUT_OF_RANGE,
                           "markdown_pct is required for a MARKDOWN disposition")
        if markdown_pct < MIN_MARKDOWN_PCT or markdown_pct > MAX_MARKDOWN_PCT:
            raise ApiError(422, ERR_MARKDOWN_OUT_OF_RANGE,
                           "markdown_pct must lie in [0.10, 0.70]")

    order = _create_entity(db.dispositions, {
        "program_id": program_id,
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "units": units,
        "channel": channel,
        "markdown_pct": float(markdown_pct) if markdown_pct is not None else None,
        "_markdown_pct": markdown_pct,
        "proposed_by_user_id": actor.user_id,
        "approved_by_user_id": None,
        "recovered_value_cents": None,
        "status": "PROPOSED",
    })
    return created(ser_disposition(order))


@bp.get("/confection/disposition-orders/<order_id>")
def read_disposition(order_id):
    authorize(*ALL_ROLES)
    return ok(ser_disposition(get_disposition(order_id)))


@bp.get("/confection/disposition-orders")
def list_dispositions():
    limit, offset = parse_pagination()
    authorize(*ALL_ROLES)
    items = list(db.dispositions.values())
    for param in ("program_id", "product_id", "warehouse_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [d for d in items if d[param] == val]
    page, total, limit, offset = paginate(items, limit, offset)
    return ok_list([ser_disposition(d) for d in page], total, limit, offset)


@bp.post("/confection/disposition-orders/<order_id>/approve")
def approve_disposition(order_id):
    data = json_body()
    decision = v_enum(data, "decision", APPROVE_DECISIONS)

    actor = authorize(ROLE_CATEGORY_MANAGER)
    order = get_disposition(order_id)

    # State (priority 7).
    if order["status"] != "PROPOSED":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only a PROPOSED disposition order can be approved or rejected")

    # Safety (priority 8): segregation of duties, for APPROVE and REJECT alike.
    if actor.user_id == order["proposed_by_user_id"]:
        raise ApiError(403, ERR_SEGREGATION_OF_DUTIES,
                       "the approver must differ from the proposer")

    # Structural (priority 10): the cannibalization guard gates MARKDOWN
    # approval only, and only when at least one sell-through report exists.
    if decision == "APPROVE" and order["channel"] == "MARKDOWN":
        raws = [Decimal(str(r["cannibalization_raw"])) for r in db.reports.values()
                if r["program_id"] == order["program_id"]]
        if raws:
            average = sum(raws) / Decimal(len(raws))
            if average < CANNIBALIZATION_FLOOR:
                raise ApiError(422, ERR_CANNIBALIZATION_GUARD,
                               "average cannibalization_raw for the program is below the 0.85 floor")

    order["approved_by_user_id"] = actor.user_id
    order["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    touch(order)
    return ok(ser_disposition(order))


@bp.post("/confection/disposition-orders/<order_id>/execute")
def execute_disposition(order_id):
    authorize(ROLE_LOGISTICS_COORDINATOR)
    order = get_disposition(order_id)

    # State (priority 7).
    if order["status"] != "APPROVED":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only an APPROVED disposition order can be executed")

    program = db.programs[order["program_id"]]

    # Temporal (priority 9): after destroy_by_on only DESTRUCTION may execute.
    if order["channel"] in ("MARKDOWN", "SECONDARY") and db.clock > program["_destroy_by_dt"]:
        raise ApiError(422, ERR_DISPOSITION_WINDOW_CLOSED,
                       "the logical clock has passed destroy_by_on; only DESTRUCTION may execute")

    # Re-verify the quarantined stock is still sufficient before consuming.
    if order["units"] > quarantined_units_at(order["product_id"], order["warehouse_id"]):
        raise ApiError(422, ERR_DISPOSITION_EXCEEDS_QUARANTINE,
                       "units exceed the quarantined stock of the product at the warehouse")

    # Consume QUARANTINED lots in created_at ASC, lot_code ASC order; a lot
    # hitting zero becomes DISPOSITIONED.
    candidates = [l for l in db.lots.values()
                  if l["warehouse_id"] == order["warehouse_id"]
                  and l["product_id"] == order["product_id"]
                  and l["status"] == "QUARANTINED" and l["units_on_hand"] > 0]
    remaining = order["units"]
    for lot in lot_draw_order(candidates):
        if remaining == 0:
            break
        take = min(lot["units_on_hand"], remaining)
        lot["units_on_hand"] -= take
        remaining -= take
        if lot["units_on_hand"] == 0:
            lot["status"] = "DISPOSITIONED"
        touch(lot)

    # Recovered value by channel. MARKDOWN rounds per unit FIRST, then
    # multiplies (PRD 2.6 / 3.9 pinned order).
    price = Decimal(program["retail_price_cents"])
    if order["channel"] == "MARKDOWN":
        unit_after = (price * (Decimal("1") - order["_markdown_pct"])).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
        recovered = int(unit_after) * order["units"]
    elif order["channel"] == "SECONDARY":
        recovered = round_cents(Decimal(order["units"]) * price * SECONDARY_RECOVERY_PCT)
    else:  # DESTRUCTION
        recovered = 0

    order["recovered_value_cents"] = recovered
    order["status"] = "EXECUTED"
    touch(order)
    return ok(ser_disposition(order))
