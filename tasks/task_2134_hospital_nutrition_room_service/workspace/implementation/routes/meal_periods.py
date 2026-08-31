"""Meal periods: scheduling, forecasting, service and closing (PRD section 3.5)."""

from flask import Blueprint

import api
import calcs
import domain
import serialize
import store
from errors import ApiError

bp = Blueprint("meal_periods", __name__, url_prefix="/nutrition/meal-periods")

PERIOD_CODES = ("BREAKFAST", "LUNCH", "DINNER", "LATE_SNACK")
PERIOD_STATUSES = ("PLANNED", "FORECAST_LOCKED", "IN_SERVICE", "CLOSED")
FORECAST_VARIANTS = ("ROLLING_AVERAGE", "CENSUS_BASED")


@bp.post("")
@api.require("NutritionManager")
def create_period():
    body = api.body()
    ward_id = api.req_id(body, "ward_id")
    period_code = api.req_enum(body, "period_code", PERIOD_CODES)
    service_date = api.req_date(body, "service_date")
    cutoff = api.req_dt(body, "order_cutoff_at")
    window_start = api.req_dt(body, "window_start_at")
    window_end = api.req_dt(body, "window_end_at")
    capacity = api.req_int(body, "production_capacity_trays", lo=1)
    cost_ceiling = api.opt_int(body, "cost_ceiling_cents", None, lo=0)

    ward = store.get_ward(ward_id)

    # Priority 6 -- interval geometry.
    if not (cutoff < window_start < window_end):
        raise ApiError("ERR_INVALID_WINDOW",
                       "order_cutoff_at must precede window_start_at, which must "
                       "precede window_end_at.")

    # Priority 7 -- the governing ward is ACTIVE.
    if ward["status"] != "ACTIVE":
        raise ApiError("ERR_WARD_SUSPENDED", "The ward is SUSPENDED.")

    # Priority 28 -- closed-interval window collision on the same ward.
    for other in store.meal_periods.values():
        if other["ward_id"] != ward_id:
            continue
        if window_start <= other["window_end_at"] and other["window_start_at"] <= window_end:
            raise ApiError("ERR_MEAL_PERIOD_WINDOW_OVERLAP",
                           "The delivery window collides with an existing period "
                           "on this ward.")

    period = {
        "ward_id": ward_id,
        "period_code": period_code,
        "service_date": service_date,
        "order_cutoff_at": cutoff,
        "window_start_at": window_start,
        "window_end_at": window_end,
        "production_capacity_trays": capacity,
        "cost_ceiling_cents": cost_ceiling,
        "status": "PLANNED",
        "forecast_variant": None,
        "forecast_tray_count": None,
        "forecast_cost_cents": None,
        "forecast_variance_pct": None,
        "locked_at": None,
        "committed_tray_count": 0,
        "committed_food_cost_cents": 0,
        "delivered_tray_count": 0,
        "period_overhead_cents": 0,
        "period_bulk_discount_cents": 0,
        "period_total_cost_cents": 0,
    }
    store.stamp_new(period)
    store.meal_periods[period["id"]] = period
    return api.created(serialize.meal_period(period))


@bp.get("")
@api.require(*api.ALL_ROLES)
def list_periods():
    ward_id = api.q_str("ward_id")
    period_code = api.q_enum("period_code", PERIOD_CODES)
    service_date = api.q_str("service_date")
    status = api.q_enum("status", PERIOD_STATUSES)
    rows = api.filtered(list(store.meal_periods.values()),
                        [(ward_id, "ward_id"), (period_code, "period_code"),
                         (service_date, "service_date"), (status, "status")])
    return api.paged(rows, serialize.meal_period)


@bp.get("/<period_id>")
@api.require(*api.ALL_ROLES)
def read_period(period_id):
    return api.ok(serialize.meal_period(store.get_meal_period(period_id)))


@bp.post("/<period_id>/lock-forecast")
@api.require("NutritionManager")
def lock_forecast(period_id):
    period = store.get_meal_period(period_id)
    body = api.body()
    variant = api.req_enum(body, "forecast_variant", FORECAST_VARIANTS)
    ward = store.wards[period["ward_id"]]

    if ward["status"] != "ACTIVE":
        raise ApiError("ERR_WARD_SUSPENDED", "The ward is SUSPENDED.")
    if period["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a PLANNED meal period may have its forecast locked.")

    history = [p for p in store.meal_periods.values()
               if p["ward_id"] == period["ward_id"]
               and p["period_code"] == period["period_code"]
               and p["status"] == "CLOSED"
               and p["service_date"] < period["service_date"]]
    history.sort(key=lambda p: (p["service_date"], p["created_at"], p["_seq"]),
                 reverse=True)
    history = history[:calcs.ROLLING_HISTORY_DEPTH]

    census = store.ward_census(period["ward_id"])
    trays, cost = calcs.production_forecast_trays(variant, history, ward, census)

    period["forecast_variant"] = variant
    period["forecast_tray_count"] = trays
    period["forecast_cost_cents"] = cost
    period["locked_at"] = store.now()
    period["status"] = "FORECAST_LOCKED"
    domain.refresh_variance(period)
    store.touch(period)
    return api.ok(serialize.meal_period(period))


@bp.post("/<period_id>/open-service")
@api.require("NutritionManager")
def open_service(period_id):
    period = store.get_meal_period(period_id)
    ward = store.wards[period["ward_id"]]
    if ward["status"] != "ACTIVE":
        raise ApiError("ERR_WARD_SUSPENDED", "The ward is SUSPENDED.")
    if period["status"] != "FORECAST_LOCKED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a FORECAST_LOCKED meal period may be opened for service.")
    period["status"] = "IN_SERVICE"
    store.touch(period)
    return api.ok(serialize.meal_period(period))


@bp.post("/<period_id>/close")
@api.require("NutritionManager")
def close_period(period_id):
    period = store.get_meal_period(period_id)
    if period["status"] != "IN_SERVICE":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an IN_SERVICE meal period may be closed.")

    period["status"] = "CLOSED"
    trays = [t for t in store.orders_of_period(period["id"])
             if t["fulfillment_status"] in domain.OPEN_TRAY_STATES]
    for tray in trays:
        domain.mark_tray_missed(tray, "PERIOD_CLOSED", bump_patient_version=True)

    domain.refresh_period_ledger(period)
    store.touch(period)
    return api.ok(serialize.meal_period(period))
