"""Demand forecast lines: the statistical baseline and the consensus workflow (PRD 3.3)."""
from flask import Blueprint

from auth import (ROLE_CUSTOMER_REP, ROLE_DEMAND_PLANNER,
                  ROLE_DEMAND_REVIEW_LEAD, ROLE_EXECUTIVE_SPONSOR,
                  ROLE_SOP_ADMIN, ROLE_SUPPLY_PLANNER, check_frozen,
                  check_phase_closed, endpoint, find_or_404,
                  scope_list_customer, scope_row_customer)
from calcs import adjustments_of, calc_statistical_baseline, rollup_consensus
from cascades import open_adjustments_on_forecast, stale_plans_of_item
from envelope import respond_list, respond_object
from errors import ApiError
from store import new_row, ordered, public, public_all, store, touch
from validators import (get_body, paginate, pagination, query_enum,
                        query_month, query_str, req_enum, req_id, req_int,
                        req_month, req_number)

bp = Blueprint("forecasts", __name__)

WRITE_ROLES = [ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER]
TRANSITION_ROLES = [ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD]
READ_ROLES = [ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
              ROLE_SUPPLY_PLANNER, ROLE_EXECUTIVE_SPONSOR, ROLE_CUSTOMER_REP]

FORECAST_STATUSES = ("BASELINE", "UNDER_CONSENSUS", "CONSENSUS_LOCKED",
                     "RUNOUT_TRUNCATED")

FORECAST_TRANSITIONS = {
    "BASELINE": ("UNDER_CONSENSUS", "CONSENSUS_LOCKED"),
    "UNDER_CONSENSUS": ("CONSENSUS_LOCKED",),
    "CONSENSUS_LOCKED": ("UNDER_CONSENSUS",),
    "RUNOUT_TRUNCATED": (),
}


@bp.post("/sop/demand-forecasts")
@endpoint(WRITE_ROLES)
def create_forecast():
    body = get_body()
    cycle_id = req_id(body, "cycle_id")
    item_id = req_id(body, "item_id")
    customer_id = req_id(body, "customer_id")
    month = req_month(body, "month")
    level_units = req_int(body, "level_units", minimum=0)
    trend_units_per_month = req_number(body, "trend_units_per_month")
    seasonal_index = req_number(body, "seasonal_index", exclusive_min=0, maximum=5)
    causal_uplift_pct = req_number(body, "causal_uplift_pct", minimum=-100,
                                   maximum=500)

    cycle = find_or_404("cycles", cycle_id, "ERR_CYCLE_NOT_FOUND")
    item = find_or_404("items", item_id, "ERR_ITEM_NOT_FOUND")
    find_or_404("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")

    # Forecast creation is not one of the nine phase-actor operations (PRD 2.8);
    # it is covered by the frozen barrier and by the phase-closed rejection.
    check_frozen(cycle)
    check_phase_closed(cycle, "DEMAND_REVIEW")

    if (month < cycle["horizon_start_month"]
            or month > cycle["horizon_end_month"]):
        raise ApiError("ERR_MONTH_OUTSIDE_HORIZON",
                       "Month %s falls outside the cycle horizon %s..%s"
                       % (month, cycle["horizon_start_month"],
                          cycle["horizon_end_month"]))

    for other in store.forecasts.values():
        if (other["cycle_id"] == cycle_id and other["item_id"] == item_id
                and other["customer_id"] == customer_id
                and other["month"] == month):
            raise ApiError("ERR_DUPLICATE_FORECAST",
                           "A forecast line already exists for that cycle, "
                           "item, customer and month")

    method, baseline_units = calc_statistical_baseline(
        cycle, item, month, level_units, trend_units_per_month,
        seasonal_index, causal_uplift_pct)

    row = new_row()
    row.update({
        "cycle_id": cycle_id,
        "item_id": item_id,
        "customer_id": customer_id,
        "month": month,
        "level_units": level_units,
        "trend_units_per_month": trend_units_per_month,
        "seasonal_index": seasonal_index,
        "causal_uplift_pct": causal_uplift_pct,
        "method": method,
        "baseline_units": baseline_units,
        "consensus_units": baseline_units,
        "endorsed_adjustment_count": 0,
        "status": "BASELINE",
    })
    store.forecasts[row["id"]] = row
    return respond_object(public(row), 201)


@bp.post("/sop/demand-forecasts/<forecast_id>/transitions")
@endpoint(TRANSITION_ROLES)
def transition_forecast(forecast_id):
    body = get_body()
    target_status = req_enum(body, "target_status", FORECAST_STATUSES)

    forecast = find_or_404("forecasts", forecast_id, "ERR_FORECAST_NOT_FOUND")
    cycle = store.cycles.get(forecast["cycle_id"])
    current = forecast["status"]

    if cycle is not None:
        check_frozen(cycle)
        # Only BASELINE -> UNDER_CONSENSUS carries a cycle-phase precondition
        # (PRD 3.3); the two lock edges and the rework edge do not.
        if current == "BASELINE" and target_status == "UNDER_CONSENSUS":
            check_phase_closed(cycle, "DEMAND_REVIEW")

    if target_status not in FORECAST_TRANSITIONS[current]:
        raise ApiError("ERR_FORECAST_TRANSITION_INVALID",
                       "A forecast line in %s may not move to %s"
                       % (current, target_status))

    if current == "UNDER_CONSENSUS" and target_status == "CONSENSUS_LOCKED":
        if open_adjustments_on_forecast(forecast["id"]):
            raise ApiError("ERR_OPEN_ADJUSTMENTS",
                           "An adjustment on this forecast line is still open")

    forecast["status"] = target_status

    if target_status == "CONSENSUS_LOCKED":
        if current == "UNDER_CONSENSUS":
            for adjustment in ordered(adjustments_of(forecast["id"])):
                if adjustment["status"] == "ENDORSED":
                    adjustment["status"] = "COMMITTED"
                    touch(adjustment)
        rollup_consensus(forecast)
    elif current == "CONSENSUS_LOCKED" and target_status == "UNDER_CONSENSUS":
        for adjustment in ordered(adjustments_of(forecast["id"])):
            if adjustment["status"] == "COMMITTED":
                adjustment["status"] = "ENDORSED"
                touch(adjustment)
        rollup_consensus(forecast)
    else:
        rollup_consensus(forecast)

    touch(forecast)

    if current == "CONSENSUS_LOCKED" and target_status == "UNDER_CONSENSUS":
        stale_plans_of_item(forecast["item_id"])

    return respond_object(public(forecast))


@bp.get("/sop/demand-forecasts/<forecast_id>")
@endpoint(READ_ROLES)
def get_forecast(forecast_id):
    row = find_or_404("forecasts", forecast_id, "ERR_FORECAST_NOT_FOUND")
    scope_row_customer(row["customer_id"])
    return respond_object(public(row))


@bp.get("/sop/demand-forecasts")
@endpoint(READ_ROLES)
def list_forecasts():
    limit, offset = pagination()
    scope_list_customer()
    cycle_id = query_str("cycle_id")
    item_id = query_str("item_id")
    customer_id = query_str("customer_id")
    month = query_month("month")
    status = query_enum("status", FORECAST_STATUSES)
    rows = ordered(store.forecasts.values())
    if cycle_id is not None:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if item_id is not None:
        rows = [r for r in rows if r["item_id"] == item_id]
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if month is not None:
        rows = [r for r in rows if r["month"] == month]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return respond_list(public_all(page), limit, offset, total)
