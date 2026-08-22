"""Lots: creation from accepted fruit and the cellar production axis."""

from decimal import Decimal

from flask import Blueprint

import calc
import domain
from auth import ALL_ROLES, CELLAR_SUPERVISOR, guard, scope
from envelope import respond
from errors import (
    ApiError,
    ERR_CROSS_CONTRACT_REFERENCE,
    ERR_INSUFFICIENT_LOT_VOLUME,
    ERR_LOT_NOT_HOUSED,
    ERR_NO_ELIGIBLE_INTAKES,
)
from helpers import declared, run_list
from store import db, iso, new_entity, rhu, touch
from validation import v_enum, v_int, v_number, v_string, v_string_array

D = Decimal
bp = Blueprint("lots", __name__)

LOT_ACTIONS = {
    "START_FERMENTATION": [CELLAR_SUPERVISOR],
    "PRESS": [CELLAR_SUPERVISOR],
    "START_AGING": [CELLAR_SUPERVISOR],
}


@bp.route("/lots", methods=["POST"])
def create_lot():
    ctx = guard([CELLAR_SUPERVISOR])
    body = ctx.body
    contract_id = v_string(body, "contract_id")
    lot_code = v_string(body, "lot_code")
    vintage_year = v_int(body, "vintage_year")
    intake_ids = v_string_array(body, "intake_ids")

    # Rung 15 -- body foreign keys, left to right.
    domain.get_contract(contract_id)
    intakes = [domain.get_intake(iid) for iid in intake_ids]

    # Rung 60 -- cross-aggregate ownership.
    for intake in intakes:
        if intake["contract_id"] != contract_id:
            raise ApiError(ERR_CROSS_CONTRACT_REFERENCE,
                           "An intake belongs to a different contract.")

    # Rung 78 -- eligibility.
    if not intakes:
        raise ApiError(ERR_NO_ELIGIBLE_INTAKES, "intake_ids must not be empty.")
    for intake in intakes:
        if intake["status"] != "ACCEPTED":
            raise ApiError(ERR_NO_ELIGIBLE_INTAKES,
                           "Intake '%s' is not ACCEPTED." % intake["id"])

    composition = calc.lot_composition(intakes)
    lot = new_entity({
        "contract_id": contract_id,
        "current_vessel_id": None,
        "parent_lot_id": None,
        "lot_code": lot_code,
        "vintage_year": vintage_year,
        "varietal": composition["varietal"],
        "appellation": composition["appellation"],
        "varietal_label": composition["varietal_label"],
        "appellation_label": composition["appellation_label"],
        "volume_gallons": composition["volume_gallons"],
        "loss_gallons": D(0),
        "brix_at_crush": composition["brix_at_crush"],
        "alcohol_pct": None,
        "origin": "INTAKE",
        "production_status": "JUICE",
        "bond_status": "IN_BOND",
        "aging_start_at": None,
        "aging_days": 0,
        "cases_bottled": 0,
        "source_intake_ids": list(intake_ids),
        "component_manifest": [],
        "_aging_dt": None,
        "_created_volume": composition["volume_gallons"],
    })
    db.lots[lot["id"]] = lot

    for intake in intakes:
        intake["status"] = "ASSIGNED"
        intake["lot_id"] = lot["id"]
        touch(intake)

    client = db.clients.get(domain.lot_client_id(lot))
    if client is not None:
        touch(client)
    return respond(domain.serialize_lot(lot), 201)


@bp.route("/lots/<lot_id>", methods=["GET"])
def read_lot(lot_id):
    ctx = guard(ALL_ROLES, read_body=False)
    lot = domain.get_lot(lot_id)
    scope(ctx, domain.lot_client_id(lot))
    return respond(domain.serialize_lot(lot))


@bp.route("/lots", methods=["GET"])
def list_lots():
    ctx = guard(ALL_ROLES, read_body=False)
    return run_list(db.lots.values(), ctx, domain.serialize_lot,
                    owner_fn=domain.lot_client_id,
                    filters=(("contract_id", "contract_id"),
                             ("current_vessel_id", "current_vessel_id"),
                             ("parent_lot_id", "parent_lot_id"),
                             ("production_status", "production_status"),
                             ("bond_status", "bond_status"),
                             ("origin", "origin")))


@bp.route("/lots/<lot_id>/traceability", methods=["GET"])
def lot_traceability(lot_id):
    ctx = guard(ALL_ROLES, read_body=False)
    lot = domain.get_lot(lot_id)
    scope(ctx, domain.lot_client_id(lot))
    return respond(domain.traceability(lot))


@bp.route("/lots/<lot_id>/transitions", methods=["POST"])
def lot_transitions(lot_id):
    ctx = guard([CELLAR_SUPERVISOR], LOT_ACTIONS)
    body = ctx.body
    action = v_enum(body, "action", set(LOT_ACTIONS))

    loss_gallons = None
    if action == "PRESS":
        loss_gallons = v_number(body, "loss_gallons", ge=0)

    lot = domain.get_lot(lot_id)

    if action == "START_FERMENTATION":
        declared(lot["production_status"] == "JUICE")
        # Rung 40 -- the lot must be housed.
        if lot["current_vessel_id"] is None:
            raise ApiError(ERR_LOT_NOT_HOUSED, "The lot is not housed in a vessel.")
        lot["production_status"] = "FERMENTING"
        touch(lot)
    elif action == "PRESS":
        declared(lot["production_status"] == "FERMENTING")
        # Rung 78 -- volume sufficiency.
        if loss_gallons > D(lot["volume_gallons"]):
            raise ApiError(ERR_INSUFFICIENT_LOT_VOLUME,
                           "The press loss exceeds the lot's volume.")
        lot["loss_gallons"] = rhu(D(lot["loss_gallons"]) + loss_gallons, 2)
        lot["volume_gallons"] = rhu(D(lot["volume_gallons"]) - loss_gallons, 2)
        if lot["origin"] == "INTAKE" and lot["brix_at_crush"] is not None:
            lot["alcohol_pct"] = rhu(
                D(lot["brix_at_crush"]) * calc.BRIX_TO_ALCOHOL_FACTOR, 2)
        lot["production_status"] = "PRESSED"
        touch(lot)

        client_id = domain.lot_client_id(lot)
        domain.book_loss(client_id, loss_gallons)
        client = db.clients.get(client_id)
        if client is not None:
            touch(client)
    else:  # START_AGING
        declared(lot["production_status"] == "PRESSED")
        now = db.now()
        lot["aging_start_at"] = iso(now)
        lot["_aging_dt"] = now
        lot["production_status"] = "AGING"
        touch(lot)

    return respond(domain.serialize_lot(lot))
