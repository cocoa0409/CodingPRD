"""Estray disposition: statutory hold, claim, auction and proceeds."""

from flask import Blueprint, request

from db import by_created_at, db, now, touch
from errors import ApiError
from middleware import caller_id, endpoint
from response import object_response, paginate
from routes import lookup
from services import aggregates
from services.calculations import write_final_distribution, write_provisional_distribution
from validation import ESTRAY_DECISIONS, body, req_enum, req_int

bp = Blueprint("estray_cases", __name__)

READ_ROLES = ("BoardAdmin", "LivestockOwner", "FeeAdministrator")


@bp.get("/estray-cases/<case_id>")
@endpoint(*READ_ROLES)
def read_case(case_id):
    return object_response(lookup.estray_case(case_id))


@bp.get("/estray-cases")
@endpoint(*READ_ROLES)
def list_cases():
    rows = lookup.filtered(
        db.estrays,
        {
            "animal_lot_id": request.args.get("animal_lot_id"),
            "territory_id": request.args.get("territory_id"),
            "claimant_owner_id": request.args.get("claimant_owner_id"),
            "status": request.args.get("status"),
        },
    )
    return paginate(by_created_at(rows))


@bp.post("/estray-cases/<case_id>/claim")
@endpoint("LivestockOwner")
def file_estray_claim(case_id):
    case = lookup.estray_case(case_id)
    if case["status"] != "IMPOUNDED":
        raise ApiError("ERR_ESTRAY_INVALID_STATE", "The case is not open to claims.")
    if now() >= case["statutory_release_on"]:
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED", "The statutory claim window has closed.")
    case["status"] = "CLAIM_FILED"
    case["claimant_owner_id"] = caller_id()
    touch(case)
    return object_response(case)


@bp.post("/estray-cases/<case_id>/claim-decision")
@endpoint("BoardAdmin")
def decide_estray_claim(case_id):
    payload = body()
    decision = req_enum(payload, "decision", ESTRAY_DECISIONS)

    case = lookup.estray_case(case_id)
    if case["status"] != "CLAIM_FILED":
        raise ApiError("ERR_ESTRAY_INVALID_STATE", "No claim is on file for this case.")

    if decision == "APPROVED":
        case["status"] = "RELEASED_TO_CLAIMANT"
        touch(case)
        territory = db.territories.get(case["territory_id"])
        if territory is not None:
            aggregates.recompute_territory(territory)
        lot = db.lots.get(case["animal_lot_id"])
        if lot is not None:
            lot["lot_status"] = "VERIFIED"
            lot["match_status"] = "MATCHED"
            lot["disposition"] = "CLEARED"
            touch(lot)
            order = db.orders.get(lot["inspection_order_id"])
            if order is not None and aggregates.recompute_head_count_presented(order):
                touch(order)
    else:
        case["status"] = "IMPOUNDED"
        case["claim_denied_count"] += 1
        case["claimant_owner_id"] = None
        touch(case)

    return object_response(case)


@bp.post("/estray-cases/<case_id>/schedule-auction")
@endpoint("BoardAdmin")
def schedule_auction(case_id):
    payload = body()
    estimated_gross_cents = req_int(payload, "estimated_gross_cents")

    case = lookup.estray_case(case_id)
    if case["status"] not in ("IMPOUNDED", "CLAIM_FILED"):
        raise ApiError("ERR_ESTRAY_INVALID_STATE", "The case cannot go to auction from this state.")
    if now() < case["statutory_release_on"]:
        raise ApiError("ERR_HOLD_PERIOD_NOT_ELAPSED", "The statutory hold has not elapsed.")

    case["status"] = "AUCTION_SCHEDULED"
    case["estimated_gross_cents"] = estimated_gross_cents
    write_provisional_distribution(case)
    touch(case)
    return object_response(case)


@bp.post("/estray-cases/<case_id>/record-sale")
@endpoint("BoardAdmin")
def record_sale(case_id):
    payload = body()
    gross_proceeds_cents = req_int(payload, "gross_proceeds_cents")

    case = lookup.estray_case(case_id)
    if case["status"] != "AUCTION_SCHEDULED":
        raise ApiError("ERR_ESTRAY_INVALID_STATE", "No auction is scheduled for this case.")

    case["status"] = "SOLD"
    case["gross_proceeds_cents"] = gross_proceeds_cents
    case["sale_at"] = now()
    write_final_distribution(case)
    touch(case)
    return object_response(case)


@bp.post("/estray-cases/<case_id>/disburse")
@endpoint("FeeAdministrator")
def disburse_case(case_id):
    case = lookup.estray_case(case_id)
    if case["status"] != "SOLD":
        raise ApiError("ERR_ESTRAY_INVALID_STATE", "Only a sold case may be closed out.")

    if case["claimant_owner_id"] is not None:
        case["status"] = "PROCEEDS_DISBURSED"
        case["board_forfeiture_cents"] = 0
    else:
        case["status"] = "FORFEITED_TO_BOARD"
        case["claimant_residual_cents"] = 0
        case["board_forfeiture_cents"] = (
            (case["gross_proceeds_cents"] or 0) - case["care_cost_cents"] - case["handling_fee_cents"]
        )
    touch(case)

    territory = db.territories.get(case["territory_id"])
    if territory is not None:
        aggregates.recompute_territory(territory)

    lot = db.lots.get(case["animal_lot_id"])
    if lot is not None:
        lot["lot_status"] = "VERIFIED"
        lot["disposition"] = "CLEARED"
        touch(lot)
        order = db.orders.get(lot["inspection_order_id"])
        if order is not None and aggregates.recompute_head_count_presented(order):
            touch(order)

    return object_response(case)
