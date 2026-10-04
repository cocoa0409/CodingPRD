"""HarvestLot endpoints: record (OCC on planting), get, list, receive, grade,
certify-grade, dispute-grade. Parallel dimensions: lot_status + grade_status."""
from decimal import Decimal

from flask import Blueprint, g, request

import calc
import constants
import store
from errors import (
    err,
    ERR_HARVEST_BEFORE_PLANTING,
    ERR_HARVEST_LOT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LOT_NOT_RECEIVED,
    ERR_PLANTING_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
)
from helpers import (
    as_dt,
    as_int,
    as_num,
    as_pos_int,
    as_str,
    body,
    check_owner,
    dump,
    paginate,
    reject_future,
    req_field,
    require_roles,
    success,
)

bp = Blueprint("harvest_lots", __name__)

ANY_ROLE = constants.ROLES


def get_lot_or_404(lot_id):
    lot = store.db["harvest_lots"].get(lot_id)
    if lot is None:
        raise err(ERR_HARVEST_LOT_NOT_FOUND, "No harvest lot with the given id")
    return lot


def owning_grower_id(lot):
    planting = store.db["plantings"].get(lot["planting_id"])
    if planting is None:
        return None
    agreement = store.db["agreements"].get(planting["agreement_id"])
    return agreement["grower_id"] if agreement else None


@bp.route("/licensing/harvest-lots", methods=["POST"])
@require_roles("GrowerPrincipal")
def create_harvest_lot():
    b = body()
    planting_id = b.get("planting_id")
    planting = store.db["plantings"].get(planting_id) if isinstance(planting_id, str) else None
    if planting is None and planting_id is not None:
        raise err(ERR_PLANTING_NOT_FOUND, "No planting with the given id")
    if planting is not None:
        agreement = store.db["agreements"].get(planting["agreement_id"])
        if agreement is not None:
            check_owner(agreement["grower_id"])
    if planting is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: planting_id")
    harvested_at = as_dt(req_field(b, "harvested_at"), "harvested_at")
    gross = as_num(req_field(b, "gross_weight_kg"), "gross_weight_kg")
    if gross <= 0:
        raise err(ERR_INVALID_REQUEST, "gross_weight_kg must be positive")
    tare = as_num(b.get("tare_weight_kg", 0), "tare_weight_kg")
    if tare < 0 or tare >= gross:
        raise err(ERR_INVALID_REQUEST, "tare_weight_kg must be >= 0 and < gross_weight_kg")
    expected_planting_version = as_int(
        req_field(b, "expected_planting_version"), "expected_planting_version"
    )
    reject_future(harvested_at, "harvested_at")
    # Tier 6 OCC on the planting version
    if expected_planting_version != planting["version"]:
        raise err(ERR_STALE_VERSION, "Stale planting version")
    # Tier 7 state: planting must be PLANTED or HARVESTING
    if planting["status"] not in ("PLANTED", "HARVESTING"):
        raise err(ERR_INVALID_STATE, "Planting is not PLANTED or HARVESTING")
    # Tier 10 temporal: fruit cannot predate the planting
    if harvested_at < planting["planted_on"]:
        raise err(ERR_HARVEST_BEFORE_PLANTING, "harvested_at earlier than planted_on")
    first_lot = planting["status"] == "PLANTED"
    rec = store.init_record({
        "planting_id": planting["id"],
        "harvested_at": harvested_at,
        "gross_weight_kg": gross,
        "tare_weight_kg": tare,
        "net_kg": gross - tare,
        "received_at": None,
        "pulp_temp_c_at_receipt": None,
        "received_by_user_id": None,
        "precool_hours": None,
        "cold_chain_compliant": None,
        "lot_status": "IN_TRANSIT",
        "grade_status": "UNGRADED",
        "flavor_brix": None,
        "firmness_g": None,
        "appearance_score": None,
        "defect_pct": None,
        "grade": None,
        "pack_designation": None,
        "submitted_by_user_id": None,
        "certified_by_user_id": None,
        "grade_submitted_at": None,
        "grade_dispute_reason": None,
        "grade_version": 0,
        "pool_period_id": None,
        "lot_gross_provisional_cents": None,
        "lot_gross_final_cents": None,
    })
    store.db["harvest_lots"][rec["id"]] = rec
    if first_lot:
        planting["status"] = "HARVESTING"
    store.touch(planting)  # every harvest-lot recording bumps the planting version
    return success(dump(rec), code=201)


@bp.route("/licensing/harvest-lots/<harvestLotId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_harvest_lot(harvestLotId):
    return success(dump(get_lot_or_404(harvestLotId)))


@bp.route("/licensing/harvest-lots", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_harvest_lots():
    items = list(store.db["harvest_lots"].values())
    for f in ("planting_id", "pool_period_id", "grade", "lot_status", "grade_status"):
        val = request.args.get(f)
        if val is not None:
            items = [x for x in items if x.get(f) == val]
    page, pagination = paginate(items)
    return success(page, pagination=pagination)


@bp.route("/licensing/harvest-lots/<harvestLotId>/receive", methods=["POST"])
@require_roles("CoolingOperator")
def receive_harvest_lot(harvestLotId):
    lot = get_lot_or_404(harvestLotId)
    b = body()
    received_at = as_dt(req_field(b, "received_at"), "received_at")
    pulp = as_num(req_field(b, "pulp_temp_c_at_receipt"), "pulp_temp_c_at_receipt")
    if received_at <= lot["harvested_at"] or received_at > store.clock_now():
        raise err(ERR_INVALID_REQUEST, "received_at must be after harvested_at and not in the future")
    if lot["lot_status"] != "IN_TRANSIT":
        raise err(ERR_INVALID_STATE, "Harvest lot is not IN_TRANSIT")
    precool_hours, hard_reject, compliant = calc.evaluate_cold_chain(
        lot["harvested_at"], received_at, pulp
    )
    lot["received_at"] = received_at
    lot["pulp_temp_c_at_receipt"] = pulp
    lot["received_by_user_id"] = g.uid
    lot["precool_hours"] = precool_hours
    if hard_reject:
        # Auto hard reject: lot REJECTED, grade_status locks at UNGRADED
        lot["lot_status"] = "REJECTED"
        lot["cold_chain_compliant"] = False
    else:
        lot["lot_status"] = "RECEIVED"
        lot["cold_chain_compliant"] = compliant
    store.touch(lot)
    return success(dump(lot))


@bp.route("/licensing/harvest-lots/<harvestLotId>/grade", methods=["POST"])
@require_roles("QualityGrader")
def grade_harvest_lot(harvestLotId):
    lot = get_lot_or_404(harvestLotId)
    b = body()
    flavor_brix = as_num(req_field(b, "flavor_brix"), "flavor_brix")
    firmness_g = as_int(req_field(b, "firmness_g"), "firmness_g")
    appearance_score = as_int(req_field(b, "appearance_score"), "appearance_score")
    defect_pct = as_num(req_field(b, "defect_pct"), "defect_pct")
    if not (Decimal(0) <= flavor_brix <= Decimal(20)):
        raise err(ERR_INVALID_REQUEST, "flavor_brix out of range 0..20")
    if not (0 <= firmness_g <= 500):
        raise err(ERR_INVALID_REQUEST, "firmness_g out of range 0..500")
    if not (0 <= appearance_score <= 100):
        raise err(ERR_INVALID_REQUEST, "appearance_score out of range 0..100")
    if not (Decimal(0) <= defect_pct <= Decimal(100)):
        raise err(ERR_INVALID_REQUEST, "defect_pct out of range 0..100")
    # Receipt requirement (PRD 3.7): the lot must have been received. Lots still
    # IN_TRANSIT and hard-rejected lots (REJECTED while still UNGRADED) can never
    # be graded. A certified-then-disputed lot sits at lot_status GRADED (or
    # REJECTED via a certified REJECT grade) and must accept a regrade — the
    # SUBMITTED → CERTIFIED → DISPUTED → SUBMITTED cycle repeats without limit.
    if lot["lot_status"] == "IN_TRANSIT" or (
        lot["lot_status"] == "REJECTED" and lot["grade_status"] == "UNGRADED"
    ):
        raise err(ERR_LOT_NOT_RECEIVED, "Lot is not RECEIVED")
    if lot["grade_status"] not in ("UNGRADED", "DISPUTED"):
        raise err(ERR_INVALID_STATE, "Grade dimension does not accept a submission")
    regrade = lot["grade_status"] == "DISPUTED"
    lot["flavor_brix"] = flavor_brix
    lot["firmness_g"] = firmness_g
    lot["appearance_score"] = appearance_score
    lot["defect_pct"] = defect_pct
    grade = calc.determine_grade(flavor_brix, firmness_g, appearance_score, defect_pct)
    lot["grade"] = grade
    lot["pack_designation"] = grade
    lot["grade_version"] = lot["grade_version"] + 1 if regrade else 1
    lot["submitted_by_user_id"] = g.uid
    lot["grade_submitted_at"] = store.clock_now()
    lot["certified_by_user_id"] = None  # fresh certification must follow a regrade
    lot["grade_status"] = "SUBMITTED"
    store.touch(lot)
    return success(dump(lot))


@bp.route("/licensing/harvest-lots/<harvestLotId>/certify-grade", methods=["POST"])
@require_roles("QualityGrader")
def certify_grade(harvestLotId):
    lot = get_lot_or_404(harvestLotId)
    if lot["grade_status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Grade dimension is not SUBMITTED")
    # Four-eyes segregation of duties (tier 8)
    if g.uid == lot["submitted_by_user_id"] or g.uid == lot["received_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Certifier must differ from submitter and receiver")
    lot["certified_by_user_id"] = g.uid
    lot["grade_status"] = "CERTIFIED"
    if lot["grade"] == "REJECT":
        lot["lot_status"] = "REJECTED"
    else:
        lot["lot_status"] = "GRADED"
    store.touch(lot)
    return success(dump(lot))


@bp.route("/licensing/harvest-lots/<harvestLotId>/dispute-grade", methods=["POST"])
@require_roles("GrowerPrincipal")
def dispute_grade(harvestLotId):
    lot = get_lot_or_404(harvestLotId)
    owner = owning_grower_id(lot)
    if owner is not None:
        check_owner(owner)
    reason = as_str(req_field(body(), "reason"), "reason")
    if lot["grade_status"] != "CERTIFIED" or lot["lot_status"] == "SETTLED":
        raise err(ERR_INVALID_STATE, "Grade is not in a disputable state")
    lot["grade_status"] = "DISPUTED"
    lot["grade_dispute_reason"] = reason
    store.touch(lot)
    return success(dump(lot))
