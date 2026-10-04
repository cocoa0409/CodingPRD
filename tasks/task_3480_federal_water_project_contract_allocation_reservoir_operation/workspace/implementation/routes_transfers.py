"""TransferRequests (PRD section 3.8).

Cyclic review loop UNDER_REVIEW -> REVISION_REQUESTED -> UNDER_REVIEW bounded
at 3 revision rounds; APPROVED sets a 72-hour objection window; execution moves
water between the year's current published announcement lines.
"""
from datetime import timedelta

from flask import Blueprint, request

import calc
from auth import ALL_ROLES, authenticate
from envelope import list_response, success
from errors import ApiError, invalid_quantity, not_found
from serial import transfer_view
from store import DB, clock_now, new_record, touch
from validate import as_enum, as_int, as_int_range, as_str, get_body, required

bp = Blueprint("transfer_requests", __name__)

DECISIONS = ("APPROVE", "REJECT", "REQUEST_REVISION")


def transfer_or_404(transfer_id):
    transfer = DB["transfers"].get(transfer_id)
    if transfer is None:
        not_found("TransferRequest")
    return transfer


def _year_state_gate(year):
    if year["status"] == "OPEN":
        raise ApiError("ERR_YEAR_NOT_ANNOUNCED", 409,
                       "water year has no PUBLISHED announcement")
    if year["status"] == "CLOSED":
        raise ApiError("ERR_YEAR_CLOSED", 409, "water year is CLOSED")


@bp.post("/water/transfer-requests")
def create_transfer():
    user_id, _role = authenticate(["DistrictManager"])
    body = get_body()
    from_id = as_str(required(body, "from_contract_id"), "from_contract_id")
    to_id = as_str(required(body, "to_contract_id"), "to_contract_id")
    year_id = as_str(required(body, "water_year_id"), "water_year_id")
    quantity = as_int(required(body, "quantity_af"), "quantity_af")
    price = as_int_range(body["price_cents"], "price_cents", 0) \
        if body.get("price_cents") is not None else 0
    if from_id == to_id:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "from_contract_id must differ from to_contract_id")
    # existence: body FKs in declared input order
    from_contract = DB["contracts"].get(from_id)
    if from_contract is None:
        not_found("WaterContract")
    to_contract = DB["contracts"].get(to_id)
    if to_contract is None:
        not_found("WaterContract")
    year = DB["water_years"].get(year_id)
    if year is None:
        not_found("WaterYear")
    # ownership: caller acts as the seller district
    if from_contract["district_id"] != user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "caller does not manage the seller contract's district")
    # state gates: seller suspension before buyer suspension, then the year
    if from_contract["status"] == "SUSPENDED":
        raise ApiError("ERR_CONTRACT_SUSPENDED", 409,
                       "seller contract is SUSPENDED")
    if to_contract["status"] == "SUSPENDED":
        raise ApiError("ERR_CONTRACT_SUSPENDED", 409,
                       "buyer contract is SUSPENDED")
    _year_state_gate(year)
    # business: positive quantity (priority 8), then fiscal (priority 11)
    if quantity <= 0:
        invalid_quantity("quantity_af must be > 0")
    line = calc.current_line(year, from_contract["id"])
    if line is None or quantity > line["remaining_af"]:
        raise ApiError("ERR_ALLOCATION_EXCEEDED", 422,
                       "quantity_af exceeds the seller line's remaining_af")
    rec = new_record()
    rec.update({
        "from_contract_id": from_contract["id"],
        "to_contract_id": to_contract["id"],
        "water_year_id": year["id"],
        "quantity_af": quantity,
        "price_cents": price,
        "status": "UNDER_REVIEW",
        "revision_count": 0,
        "objection_window_end": None,
        "executed_at": None,
    })
    DB["transfers"][rec["id"]] = rec
    return success(transfer_view(rec), 201)


@bp.get("/water/transfer-requests")
def list_transfers():
    authenticate(ALL_ROLES)
    filters = {
        "from_contract_id": request.args.get("from_contract_id"),
        "to_contract_id": request.args.get("to_contract_id"),
        "water_year_id": request.args.get("water_year_id"),
        "status": request.args.get("status"),
    }
    return list_response(list(DB["transfers"].values()), transfer_view, filters)


@bp.get("/water/transfer-requests/<string:transfer_id>")
def get_transfer(transfer_id):
    authenticate(ALL_ROLES)
    return success(transfer_view(transfer_or_404(transfer_id)))


@bp.post("/water/transfer-requests/<string:transfer_id>/decide")
def decide_transfer(transfer_id):
    authenticate(["RegionalDirector"])
    body = get_body()
    decision = as_enum(required(body, "decision"), "decision", DECISIONS)
    if body.get("rationale") is not None:
        as_str(body["rationale"], "rationale")
    transfer = transfer_or_404(transfer_id)
    if transfer["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only an UNDER_REVIEW transfer can be decided")
    if decision == "APPROVE":
        # referential: approval requires zero FILED impact reviews
        for review in DB["impact_reviews"].values():
            if (review["transfer_request_id"] == transfer["id"]
                    and review["status"] == "FILED"):
                raise ApiError("ERR_REVIEW_PENDING", 409,
                               "an impact review on this transfer is still FILED")
        transfer["objection_window_end"] = (
            clock_now() + timedelta(hours=calc.OBJECTION_WINDOW_HOURS))
        transfer["status"] = "APPROVED"
    elif decision == "REJECT":
        transfer["status"] = "REJECTED"
    else:  # REQUEST_REVISION
        if transfer["revision_count"] >= calc.TRANSFER_REVISION_CAP:
            raise ApiError("ERR_REVISION_LIMIT_EXCEEDED", 409,
                           "the three-round revision cap is exhausted")
        transfer["revision_count"] += 1
        transfer["status"] = "REVISION_REQUESTED"
    touch(transfer)
    return success(transfer_view(transfer), 200)


@bp.post("/water/transfer-requests/<string:transfer_id>/resubmit")
def resubmit_transfer(transfer_id):
    user_id, _role = authenticate(["DistrictManager"])
    body = get_body()
    new_quantity = None
    if body.get("quantity_af") is not None:
        new_quantity = as_int(body["quantity_af"], "quantity_af")
    new_price = None
    if body.get("price_cents") is not None:
        new_price = as_int_range(body["price_cents"], "price_cents", 0)
    transfer = transfer_or_404(transfer_id)
    from_contract = DB["contracts"][transfer["from_contract_id"]]
    if from_contract["district_id"] != user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "caller does not manage the seller contract's district")
    if transfer["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a REVISION_REQUESTED transfer can be resubmitted")
    if new_quantity is not None:
        if new_quantity <= 0:
            invalid_quantity("quantity_af must be > 0")
        year = DB["water_years"][transfer["water_year_id"]]
        line = calc.current_line(year, from_contract["id"])
        if line is None or new_quantity > line["remaining_af"]:
            raise ApiError("ERR_ALLOCATION_EXCEEDED", 422,
                           "amended quantity_af exceeds the seller line's remaining_af")
        transfer["quantity_af"] = new_quantity
    if new_price is not None:
        transfer["price_cents"] = new_price
    transfer["status"] = "UNDER_REVIEW"
    touch(transfer)
    return success(transfer_view(transfer), 200)


@bp.post("/water/transfer-requests/<string:transfer_id>/execute")
def execute_transfer(transfer_id):
    authenticate(["ReclamationOperator"])
    transfer = transfer_or_404(transfer_id)
    if transfer["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only an APPROVED transfer can be executed")
    now = clock_now()
    if now < transfer["objection_window_end"]:
        raise ApiError("ERR_OBJECTION_WINDOW_OPEN", 409,
                       "the objection window is still open")
    # ledger movement lands on the CURRENT published announcement's lines
    year = DB["water_years"][transfer["water_year_id"]]
    from_line = calc.current_line(year, transfer["from_contract_id"])
    to_line = calc.current_line(year, transfer["to_contract_id"])
    if from_line is None or to_line is None:
        not_found("AllocationLine")
    from_line["transfer_out_af"] += transfer["quantity_af"]
    calc.recompute_line(from_line)
    to_line["transfer_in_af"] += transfer["quantity_af"]
    calc.recompute_line(to_line)
    transfer["executed_at"] = now
    transfer["status"] = "EXECUTED"
    touch(transfer)
    return success(transfer_view(transfer), 200)
