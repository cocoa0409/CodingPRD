"""DeliveryOrders (PRD section 3.6).

Fulfillment and compliance are parallel dimensions: record-delivery never
touches compliance_status, and a FLAGGED order records exactly like a CLEARED
one. The only road to SHORTED is the curtailment cascade.
"""
from flask import Blueprint, request

import calc
from auth import ALL_ROLES, authenticate
from envelope import list_response, success
from errors import ApiError, invalid_quantity, not_found
from serial import order_view
from store import DB, new_record, touch
from validate import as_int, as_str, get_body, required

bp = Blueprint("delivery_orders", __name__)


def order_or_404(order_id):
    order = DB["delivery_orders"].get(order_id)
    if order is None:
        not_found("DeliveryOrder")
    return order


@bp.post("/water/delivery-orders")
def create_delivery_order():
    user_id, _role = authenticate(["DistrictManager"])
    body = get_body()
    contract_id = as_str(required(body, "contract_id"), "contract_id")
    water_year_id = as_str(required(body, "water_year_id"), "water_year_id")
    ordered_af = as_int(required(body, "ordered_af"), "ordered_af")
    # existence: body FKs in declared input order
    contract = DB["contracts"].get(contract_id)
    if contract is None:
        not_found("WaterContract")
    year = DB["water_years"].get(water_year_id)
    if year is None:
        not_found("WaterYear")
    # ownership: caller must own the contract's district
    if contract["district_id"] != user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "caller does not manage the contract's district")
    # state gates: contract suspension before the year check
    if contract["status"] == "SUSPENDED":
        raise ApiError("ERR_CONTRACT_SUSPENDED", 409,
                       "contract is SUSPENDED")
    if year["status"] == "OPEN":
        raise ApiError("ERR_YEAR_NOT_ANNOUNCED", 409,
                       "water year has no PUBLISHED announcement")
    if year["status"] == "CLOSED":
        raise ApiError("ERR_YEAR_CLOSED", 409, "water year is CLOSED")
    # business: positive quantity
    if ordered_af <= 0:
        invalid_quantity("ordered_af must be > 0")
    # fiscal: quantity must fit the resolved line's remaining balance
    line = calc.current_line(year, contract["id"])
    if line is None or ordered_af > line["remaining_af"]:
        raise ApiError("ERR_ALLOCATION_EXCEEDED", 422,
                       "ordered_af exceeds the allocation line's remaining_af")
    reservoir = calc.singleton_reservoir()
    flagged = (reservoir is not None
               and calc.reservoir_posture(reservoir["id"]) == "COMPLIANCE_HOLD")
    rec = new_record()
    rec.update({
        "contract_id": contract["id"],
        "water_year_id": year["id"],
        "allocation_line_id": line["id"],
        "ordered_af": ordered_af,
        "delivered_af": 0,
        "fulfillment_status": "CONFIRMED",
        "compliance_status": "FLAGGED" if flagged else "CLEARED",
    })
    DB["delivery_orders"][rec["id"]] = rec
    calc.recompute_line(line)
    return success(order_view(rec), 201)


@bp.get("/water/delivery-orders")
def list_delivery_orders():
    authenticate(ALL_ROLES)
    filters = {
        "contract_id": request.args.get("contract_id"),
        "allocation_line_id": request.args.get("allocation_line_id"),
        "water_year_id": request.args.get("water_year_id"),
        "fulfillment_status": request.args.get("fulfillment_status"),
    }
    return list_response(list(DB["delivery_orders"].values()), order_view, filters)


@bp.get("/water/delivery-orders/<string:order_id>")
def get_delivery_order(order_id):
    authenticate(ALL_ROLES)
    return success(order_view(order_or_404(order_id)))


@bp.post("/water/delivery-orders/<string:order_id>/record-delivery")
def record_delivery(order_id):
    authenticate(["ReclamationOperator"])
    body = get_body()
    delivered = as_int(required(body, "delivered_af"), "delivered_af")
    order = order_or_404(order_id)
    if order["fulfillment_status"] not in calc.ACTIVE_ORDER_STATES:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only CONFIRMED or PARTIALLY_DELIVERED orders accept deliveries")
    outstanding = order["ordered_af"] - order["delivered_af"]
    if delivered <= 0 or delivered > outstanding:
        invalid_quantity(
            "delivered_af must be > 0 and no more than the outstanding amount")
    order["delivered_af"] += delivered
    order["fulfillment_status"] = (
        "DELIVERED" if delivered == outstanding else "PARTIALLY_DELIVERED")
    touch(order)
    line = DB["allocation_lines"].get(order["allocation_line_id"])
    if line is not None:
        calc.recompute_line(line)
    return success(order_view(order), 200)
