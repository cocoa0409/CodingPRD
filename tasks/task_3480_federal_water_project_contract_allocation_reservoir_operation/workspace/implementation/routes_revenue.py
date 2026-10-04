"""RevenuePeriods: monthly hydropower revenue and repayment settlement
(PRD section 3.7). Projected includes SCHEDULED+EXECUTED releases; settled
reruns the identical computation restricted to EXECUTED releases.
"""
from flask import Blueprint, request

import calc
from auth import ALL_ROLES, authenticate
from envelope import list_response, success
from errors import ApiError, not_found
from routes_reservoir import reservoir_or_404
from serial import period_view
from store import DB, new_record, touch
from validate import as_int_range, as_period_month, as_str, get_body, required

bp = Blueprint("revenue_periods", __name__)


@bp.post("/water/revenue-periods")
def create_revenue_period():
    authenticate(["FinanceOfficer"])
    body = get_body()
    reservoir_id = as_str(required(body, "reservoir_id"), "reservoir_id")
    period_month = as_period_month(required(body, "period_month"))
    rate = as_int_range(required(body, "rate_cents_per_mwh"),
                        "rate_cents_per_mwh", 1)
    reservoir = DB["reservoirs"].get(reservoir_id)
    if reservoir is None:
        not_found("Reservoir")
    for p in DB["revenue_periods"].values():
        if p["reservoir_id"] == reservoir_id and p["period_month"] == period_month:
            raise ApiError("ERR_DUPLICATE_REVENUE_PERIOD", 409,
                           "a RevenuePeriod already exists for this reservoir and month")
    mwh, revenue = calc.revenue_figures(
        reservoir, period_month, ("SCHEDULED", "EXECUTED"), rate)
    rec = new_record()
    rec.update({
        "reservoir_id": reservoir["id"],
        "period_month": period_month,
        "rate_cents_per_mwh": rate,
        "projected_mwh": mwh,
        "projected_revenue_cents": revenue,
        "settled_mwh": None,
        "settled_revenue_cents": None,
        "status": "PROJECTED",
    })
    DB["revenue_periods"][rec["id"]] = rec
    return success(period_view(rec), 201)


@bp.get("/water/reservoirs/<string:reservoir_id>/revenue-periods")
def list_revenue_periods(reservoir_id):
    authenticate(ALL_ROLES)
    reservoir = reservoir_or_404(reservoir_id)
    filters = {"status": request.args.get("status")}
    records = [p for p in DB["revenue_periods"].values()
               if p["reservoir_id"] == reservoir["id"]]
    return list_response(records, period_view, filters)


@bp.post("/water/revenue-periods/<string:period_id>/settle")
def settle_revenue_period(period_id):
    authenticate(["FinanceOfficer"])
    period = DB["revenue_periods"].get(period_id)
    if period is None:
        not_found("RevenuePeriod")
    if period["status"] != "PROJECTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a PROJECTED revenue period can be settled")
    reservoir = DB["reservoirs"][period["reservoir_id"]]
    mwh, revenue = calc.revenue_figures(
        reservoir, period["period_month"], ("EXECUTED",),
        period["rate_cents_per_mwh"])
    period["settled_mwh"] = mwh
    period["settled_revenue_cents"] = revenue
    period["status"] = "SETTLED"
    touch(period)
    # distribute settled revenue as repayment credits; unrecovered balance
    # decreases by exactly the sum of credits (recomputed on read)
    credits = calc.credit_distribution(revenue)
    for contract in DB["contracts"].values():
        credit = credits.get(contract["id"], 0)
        if credit:
            contract["repaid_credits_cents"] += credit
            touch(contract)
    if any(credits.values()):
        touch(reservoir)
    return success(period_view(period), 200)
