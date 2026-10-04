"""Planting endpoints: plan (OCC on agreement), get, list, confirm, complete."""
from flask import Blueprint, request

import calc
import constants
import store
from errors import (
    err,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LOT_QUANTITY_EXCEEDED,
    ERR_LOT_VARIETY_MISMATCH,
    ERR_NO_HARVEST_WINDOW,
    ERR_PLANTING_NOT_FOUND,
    ERR_PLANTING_QUOTA_EXCEEDED,
    ERR_PLANTING_WINDOW_VIOLATION,
    ERR_PLANT_LOT_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_VARIETY_RECALLED,
    ERR_WINDOW_CAPACITY_EXCEEDED,
)
from helpers import (
    as_dt,
    as_int,
    as_pos_int,
    body,
    check_owner,
    dump,
    paginate,
    reject_future,
    req_field,
    require_roles,
    success,
)
from routes_plant_lots import maybe_deplete, recompute_availability

bp = Blueprint("plantings", __name__)

ANY_ROLE = constants.ROLES


def get_planting_or_404(planting_id):
    p = store.db["plantings"].get(planting_id)
    if p is None:
        raise err(ERR_PLANTING_NOT_FOUND, "No planting with the given id")
    return p


@bp.route("/licensing/plantings", methods=["POST"])
@require_roles("GrowerPrincipal")
def create_planting():
    b = body()
    agreement_id = b.get("agreement_id")
    # Tier 4: agreement must resolve to walk the ownership chain
    agreement = store.db["agreements"].get(agreement_id) if isinstance(agreement_id, str) else None
    if agreement is None and agreement_id is not None:
        raise err(ERR_AGREEMENT_NOT_FOUND, "No agreement with the given id")
    # Tier 3 ownership: caller must own the agreement's grower
    if agreement is not None:
        check_owner(agreement["grower_id"])
    if agreement is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: agreement_id")
    plant_lot_id = as_pos_int_or_str(b)
    planned_plants = as_pos_int(req_field(b, "planned_plants"), "planned_plants")
    expected_agreement_version = as_int(
        req_field(b, "expected_agreement_version"), "expected_agreement_version"
    )
    # Tier 4 continued: plant lot
    lot = store.db["plant_lots"].get(plant_lot_id)
    if lot is None:
        raise err(ERR_PLANT_LOT_NOT_FOUND, "No plant lot with the given id")
    # Tier 6 OCC on the agreement version
    if expected_agreement_version != agreement["version"]:
        raise err(ERR_STALE_VERSION, "Stale agreement version")
    # Tier 7 state: agreement must be ACTIVE
    if agreement["status"] != "ACTIVE":
        raise err(ERR_AGREEMENT_NOT_ACTIVE, "Agreement is not ACTIVE")
    # Tier 9 referential: variety not RECALLED; lot variety must match agreement variety
    variety = store.db["varieties"].get(agreement["variety_id"])
    if variety is not None and variety["status"] == "RECALLED":
        raise err(ERR_VARIETY_RECALLED, "Variety is RECALLED")
    if lot["variety_id"] != agreement["variety_id"]:
        raise err(ERR_LOT_VARIETY_MISMATCH, "Plant lot variety differs from agreement variety")
    # Tier 11: reservation against lot availability
    if planned_plants > lot["plants_available"]:
        raise err(ERR_LOT_QUANTITY_EXCEEDED, "planned_plants exceeds lot availability")
    rec = store.init_record({
        "agreement_id": agreement["id"],
        "plant_lot_id": lot["id"],
        "planned_plants": planned_plants,
        "plants_planted_actual": None,
        "planted_on": None,
        "region_code": agreement["region_code"],
        "expected_first_harvest": None,
        "expected_yield_kg": None,
        "harvest_window_id": None,
        "status": "PLANNED",
        "completed_at": None,
        "recalled_at": None,
        "recall_compensation_cents": None,
    })
    store.db["plantings"][rec["id"]] = rec
    lot["plants_reserved"] += planned_plants
    recompute_availability(lot)
    store.touch(lot)
    # The reservation changes the quota picture: bump the agreement version
    store.touch(agreement)
    return success(dump(rec), code=201)


def as_pos_int_or_str(b):
    v = req_field(b, "plant_lot_id")
    if not isinstance(v, str) or not v:
        raise err(ERR_INVALID_REQUEST, "Field plant_lot_id must be a non-empty string")
    return v


@bp.route("/licensing/plantings/<plantingId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_planting(plantingId):
    return success(dump(get_planting_or_404(plantingId)))


@bp.route("/licensing/plantings", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_plantings():
    items = list(store.db["plantings"].values())
    for f in ("agreement_id", "plant_lot_id", "harvest_window_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [x for x in items if x.get(f) == val]
    page, pagination = paginate(items)
    return success(page, pagination=pagination)


@bp.route("/licensing/plantings/<plantingId>/confirm", methods=["POST"])
@require_roles("GrowerPrincipal")
def confirm_planting(plantingId):
    p = get_planting_or_404(plantingId)
    agreement = store.db["agreements"].get(p["agreement_id"])
    if agreement is not None:
        check_owner(agreement["grower_id"])
    b = body()
    actual = as_pos_int(req_field(b, "plants_planted_actual"), "plants_planted_actual")
    planted_on = as_dt(req_field(b, "planted_on"), "planted_on")
    reject_future(planted_on, "planted_on")
    if p["status"] != "PLANNED":
        raise err(ERR_INVALID_STATE, "Planting is not PLANNED")
    if agreement is None or agreement["status"] != "ACTIVE":
        raise err(ERR_AGREEMENT_NOT_ACTIVE, "Agreement is not ACTIVE")
    lot = store.db["plant_lots"][p["plant_lot_id"]]
    variety = store.db["varieties"][lot["variety_id"]]
    berry_type = variety["berry_type"]
    # Temporal: planted_on inside the closed agreement window
    if not (agreement["effective_from"] <= planted_on <= agreement["effective_to"]):
        raise err(ERR_PLANTING_WINDOW_VIOLATION, "planted_on outside the agreement window")
    # Agronomic expectations
    efh = calc.expected_first_harvest(berry_type, planted_on)
    ey = calc.expected_yield(berry_type, actual)
    # Temporal: an eligible harvest window must exist
    window = calc.find_eligible_window(lot["variety_id"], p["region_code"], efh)
    if window is None:
        raise err(ERR_NO_HARVEST_WINDOW, "No harvest window covers expected_first_harvest")
    # Quantity gates: agreement quota, lot availability, window capacity (in order)
    if actual > agreement["max_planting_units"] - agreement["units_planted"]:
        raise err(ERR_PLANTING_QUOTA_EXCEEDED, "Confirm exceeds the agreement quota")
    if actual > lot["plants_available"] + p["planned_plants"]:
        raise err(ERR_LOT_QUANTITY_EXCEEDED, "Confirm exceeds the lot's true availability")
    if window["booked_volume_kg"] + ey > window["target_volume_kg"] * constants.WINDOW_OVERSUBSCRIBE_PCT:
        raise err(ERR_WINDOW_CAPACITY_EXCEEDED, "Booking exceeds the window capacity")
    # Atomic mutation: reservation converts into planted reality
    lot["plants_reserved"] -= p["planned_plants"]
    lot["plants_planted"] += actual
    recompute_availability(lot)
    maybe_deplete(lot)
    store.touch(lot)
    agreement["units_planted"] += actual
    store.touch(agreement)
    window["booked_volume_kg"] += ey
    store.touch(window)
    p["plants_planted_actual"] = actual
    p["planted_on"] = planted_on
    p["expected_first_harvest"] = efh
    p["expected_yield_kg"] = ey
    p["harvest_window_id"] = window["id"]
    p["status"] = "PLANTED"
    store.touch(p)
    return success(dump(p))


@bp.route("/licensing/plantings/<plantingId>/complete", methods=["POST"])
@require_roles("GrowerPrincipal")
def complete_planting(plantingId):
    p = get_planting_or_404(plantingId)
    agreement = store.db["agreements"].get(p["agreement_id"])
    if agreement is not None:
        check_owner(agreement["grower_id"])
    if p["status"] != "HARVESTING":
        raise err(ERR_INVALID_STATE, "Planting is not HARVESTING")
    for lot in store.db["harvest_lots"].values():
        if lot["planting_id"] == p["id"] and lot["lot_status"] not in ("GRADED", "SETTLED", "REJECTED"):
            raise err(ERR_INVALID_STATE, "A harvest lot of this planting is still in flight")
    p["status"] = "COMPLETED"
    p["completed_at"] = store.clock_now()
    store.touch(p)
    return success(dump(p))
