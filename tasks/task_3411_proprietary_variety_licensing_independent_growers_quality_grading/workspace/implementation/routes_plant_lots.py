"""PlantLot endpoints: ship (NurseryManager only), get, list."""
from flask import Blueprint, request

import constants
import store
from calc import finalize_royalty
from errors import (
    err,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_PLANT_LOT_NOT_FOUND,
    ERR_VARIETY_NOT_FOUND,
    ERR_VARIETY_RECALLED,
)
from helpers import (
    as_pos_int,
    as_str,
    body,
    dump,
    paginate,
    req_field,
    require_roles,
    success,
)

bp = Blueprint("plant_lots", __name__)

ANY_ROLE = constants.ROLES


def get_plant_lot_or_404(lot_id):
    lot = store.db["plant_lots"].get(lot_id)
    if lot is None:
        raise err(ERR_PLANT_LOT_NOT_FOUND, "No plant lot with the given id")
    return lot


def recompute_availability(lot):
    lot["plants_available"] = (
        lot["quantity_plants"]
        - lot["plants_reserved"]
        - lot["plants_planted"]
        - lot["plants_destroyed"]
    )


def maybe_deplete(lot):
    """After counters move: SHIPPED/PLANTED -> PLANTED, and -> DEPLETED when
    plants_planted + plants_destroyed reaches quantity_plants (royalty final)."""
    if lot["status"] in ("SHIPPED", "PLANTED"):
        if lot["plants_planted"] > 0:
            lot["status"] = "PLANTED"
        if lot["plants_planted"] + lot["plants_destroyed"] >= lot["quantity_plants"]:
            lot["status"] = "DEPLETED"
            lot["depleted_at"] = store.clock_now()
            finalize_royalty(lot)


@bp.route("/licensing/plant-lots", methods=["POST"])
@require_roles("NurseryManager")
def create_plant_lot():
    b = body()
    nursery_code = as_str(req_field(b, "nursery_code"), "nursery_code")
    agreement_id = as_str(req_field(b, "agreement_id"), "agreement_id")
    variety_id = as_str(req_field(b, "variety_id"), "variety_id")
    quantity_plants = as_pos_int(req_field(b, "quantity_plants"), "quantity_plants")
    # Existence, left-to-right: agreement, then variety
    agreement = store.db["agreements"].get(agreement_id)
    if agreement is None:
        raise err(ERR_AGREEMENT_NOT_FOUND, "No agreement with the given id")
    variety = store.db["varieties"].get(variety_id)
    if variety is None:
        raise err(ERR_VARIETY_NOT_FOUND, "No variety with the given id")
    # State: agreement must be ACTIVE
    if agreement["status"] != "ACTIVE":
        raise err(ERR_AGREEMENT_NOT_ACTIVE, "Agreement is not ACTIVE")
    # Referential: variety must not be RECALLED
    if variety["status"] == "RECALLED":
        raise err(ERR_VARIETY_RECALLED, "Variety is RECALLED")
    shipped_at = store.clock_now()
    rec = store.init_record({
        "nursery_code": nursery_code,
        "agreement_id": agreement_id,
        "variety_id": variety_id,
        "quantity_plants": quantity_plants,
        "shipped_at": shipped_at,
        "season_year": shipped_at.year,
        "plants_reserved": 0,
        "plants_planted": 0,
        "plants_destroyed": 0,
        "plants_available": quantity_plants,
        "royalty_provisional_cents": quantity_plants * constants.ROYALTY_BASE_CENTS_PER_PLANT,
        "royalty_final_cents": None,
        "royalty_adjustment_cents": None,
        "depleted_at": None,
        "status": "SHIPPED",
    })
    store.db["plant_lots"][rec["id"]] = rec
    return success(dump(rec), code=201)


@bp.route("/licensing/plant-lots/<plantLotId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_plant_lot(plantLotId):
    return success(dump(get_plant_lot_or_404(plantLotId)))


@bp.route("/licensing/plant-lots", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_plant_lots():
    items = list(store.db["plant_lots"].values())
    for f in ("agreement_id", "variety_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [x for x in items if x.get(f) == val]
    page, pagination = paginate(items)
    return success(page, pagination=pagination)
