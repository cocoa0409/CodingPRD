"""Shrink recording, verification, dispute, resubmission and voiding."""
from flask import Blueprint

import services
from db import db
from errors import ApiError
from middleware import (ROLE_ADMIN, ROLE_AUDITOR, ROLE_CLERK, ROLE_MANAGER,
                        actor, authenticate)
from records import (department_of_lot, item_of_lot, lot_by_id, new_record,
                     shrink_event_by_id, touch)
from response import created, ok, public
from routes.common import (SHRINK_CAUSE_CODES, SHRINK_ORIGINS, SHRINK_STATUSES,
                           listing, matches)
from util import D, WASTE_HANDLING_PCT, fmt_instant, rhu_int
from validate import (MISSING, field_enum, field_int, field_string, json_body,
                      query_enum, query_string)

bp = Blueprint("shrink", __name__)

READ_ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_CLERK, ROLE_AUDITOR)


def _cost_value_cents(quantity, unit_cost_cents):
    return rhu_int(
        D(quantity) * D(unit_cost_cents) * (D(1) + WASTE_HANDLING_PCT / D(100))
    )


@bp.get("/fresh/shrink-events/<event_id>")
def get_event(event_id):
    authenticate(*READ_ROLES)
    return ok(public(shrink_event_by_id(event_id)))


@bp.get("/fresh/shrink-events")
def list_events():
    authenticate(*READ_ROLES)
    lot_id = query_string("lot_id")
    status = query_enum("status", SHRINK_STATUSES)
    cause = query_enum("cause_code", SHRINK_CAUSE_CODES)
    origin = query_enum("origin", SHRINK_ORIGINS)
    rows = [
        e for e in db.shrink_events.values()
        if matches(e, "lot_id", lot_id)
        and matches(e, "status", status)
        and matches(e, "cause_code", cause)
        and matches(e, "origin", origin)
    ]
    return listing(rows)


@bp.post("/fresh/shrink-events")
def create_event():
    authenticate(ROLE_CLERK, ROLE_MANAGER)
    body = json_body()
    lot_id = field_string(body, "lot_id", required=True, max_len=200)
    cause = field_enum(body, "cause_code", SHRINK_CAUSE_CODES, required=True)
    quantity = field_int(body, "quantity_units", required=True, minimum=1)
    note = field_string(body, "note", default=None, nullable=True, min_len=1,
                        max_len=240)
    lot = lot_by_id(lot_id)
    item = item_of_lot(lot)
    if cause == "SAMPLING" and not item["sampling_allowed"]:
        raise ApiError("ERR_SAMPLING_NOT_ALLOWED",
                       "This item does not permit sampling shrink")
    if quantity > lot["quantity_on_hand"]:
        raise ApiError("ERR_INSUFFICIENT_UNITS",
                       "The write-off exceeds the units on hand")
    event = new_record(db.shrink_events, {
        "lot_id": lot["id"],
        "cause_code": cause,
        "quantity_units": quantity,
        "note": note,
        "unit_cost_cents_snapshot": item["unit_cost_cents"],
        "cost_value_cents": _cost_value_cents(quantity,
                                              item["unit_cost_cents"]),
        "retail_value_cents": quantity * lot["current_price_cents"],
        "recorded_by_user_id": actor(),
        "verified_by_user_id": None,
        "origin": "MANUAL",
        "status": "RECORDED",
        "verified_at": None,
        "posted_at": None,
    })
    return created(public(event))


@bp.post("/fresh/shrink-events/<event_id>/verify")
def verify(event_id):
    authenticate(ROLE_MANAGER)
    json_body()
    event = shrink_event_by_id(event_id)
    if event["status"] != "RECORDED":
        raise ApiError("ERR_SHRINK_NOT_VERIFIABLE",
                       "Only a RECORDED shrink event may be verified")
    if actor() == event["recorded_by_user_id"]:
        raise ApiError("ERR_SHRINK_SELF_VERIFICATION",
                       "The recorder of a shrink event may not verify it")
    lot = db.lots[event["lot_id"]]
    quantity = event["quantity_units"]
    if quantity > lot["quantity_on_hand"]:
        raise ApiError("ERR_INSUFFICIENT_UNITS",
                       "The write-off no longer fits inside the units on hand")
    department = department_of_lot(lot)
    event["verified_by_user_id"] = actor()
    event["verified_at"] = fmt_instant(db.now())
    event["cost_value_cents"] = _cost_value_cents(
        quantity, event["unit_cost_cents_snapshot"])
    event["status"] = "VERIFIED"
    touch(event)
    # hop 1: the units move
    lot["units_shrunk"] = lot["units_shrunk"] + quantity
    lot["quantity_on_hand"] = lot["quantity_on_hand"] - quantity
    # hops 2 and 3: depletion voids the labels
    if event["origin"] != "WITHDRAWAL_AUTO":
        services.deplete_if_empty(lot)
    services.refresh_expected_sell_through(lot)
    touch(lot)
    services.recompute_liability(department)
    # hop 4: the department's posture
    services.recompute_shrink_ratio(department)
    services.recompute_posture(department)
    return ok(public(event))


@bp.post("/fresh/shrink-events/<event_id>/dispute")
def dispute(event_id):
    authenticate(ROLE_MANAGER, ROLE_AUDITOR)
    body = json_body()
    field_string(body, "dispute_note", default=None, nullable=True, min_len=1,
                 max_len=240)
    event = shrink_event_by_id(event_id)
    status = event["status"]
    compensating = status == "VERIFIED" and event["origin"] == "MANUAL"
    if status != "RECORDED" and not compensating:
        raise ApiError("ERR_SHRINK_NOT_VERIFIABLE",
                       "This shrink event may not be disputed")
    event["status"] = "DISPUTED"
    event["verified_by_user_id"] = None
    event["verified_at"] = None
    touch(event)
    if compensating:
        lot = db.lots[event["lot_id"]]
        department = department_of_lot(lot)
        quantity = event["quantity_units"]
        lot["units_shrunk"] = lot["units_shrunk"] - quantity
        lot["quantity_on_hand"] = lot["quantity_on_hand"] + quantity
        if lot["status"] == "DEPLETED":
            lot["status"] = "MARKED_DOWN" if lot["current_rung_index"] >= 0 \
                else "FRESH"
        services.refresh_expected_sell_through(lot)
        touch(lot)
        services.recompute_liability(department)
        services.recompute_shrink_ratio(department)
        services.recompute_posture(department)
    return ok(public(event))


@bp.post("/fresh/shrink-events/<event_id>/resubmit")
def resubmit(event_id):
    authenticate(ROLE_CLERK)
    body = json_body()
    quantity = field_int(body, "quantity_units", required=True, minimum=1)
    note = field_string(body, "note", default=MISSING, nullable=True,
                        min_len=1, max_len=240)
    event = shrink_event_by_id(event_id)
    if event["status"] != "DISPUTED":
        raise ApiError("ERR_SHRINK_NOT_DISPUTED",
                       "Only a DISPUTED shrink event may be resubmitted")
    lot = db.lots[event["lot_id"]]
    if quantity > lot["quantity_on_hand"]:
        raise ApiError("ERR_INSUFFICIENT_UNITS",
                       "The corrected write-off exceeds the units on hand")
    event["quantity_units"] = quantity
    if note is not MISSING:
        event["note"] = note
    event["recorded_by_user_id"] = actor()
    event["retail_value_cents"] = quantity * lot["current_price_cents"]
    event["cost_value_cents"] = _cost_value_cents(
        quantity, event["unit_cost_cents_snapshot"])
    event["status"] = "RECORDED"
    touch(event)
    return ok(public(event))


@bp.post("/fresh/shrink-events/<event_id>/void")
def void(event_id):
    authenticate(ROLE_MANAGER)
    json_body()
    event = shrink_event_by_id(event_id)
    if event["status"] != "DISPUTED":
        raise ApiError("ERR_SHRINK_NOT_DISPUTED",
                       "Only a DISPUTED shrink event may be voided")
    event["status"] = "VOIDED"
    touch(event)
    return ok(public(event))
