"""Master data: product families, items and trade customers (PRD 3.1)."""
from flask import Blueprint

from auth import (ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
                  ROLE_EXECUTIVE_SPONSOR, ROLE_SOP_ADMIN, ROLE_SUPPLY_PLANNER,
                  ROLE_CUSTOMER_REP, endpoint, find_or_404)
from calcs import calc_inventory_policy
from cascades import (cancel_promotion_runout, forecasts_of_item,
                      promotions_of_item, stale_plans_of_item,
                      truncate_forecast, void_adjustment)
from envelope import respond_list, respond_object
from errors import ApiError, bad_request
from store import new_row, ordered, public, public_all, store, touch
from validators import (forbid, get_body, opt_bool, opt_enum, opt_id, opt_int,
                        opt_number, opt_string, paginate, pagination, query_bool,
                        query_enum, query_str, req_enum, req_int, req_month,
                        req_number, req_string)

bp = Blueprint("master", __name__)

READ_ROLES = [ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
              ROLE_SUPPLY_PLANNER, ROLE_EXECUTIVE_SPONSOR]

CHANNELS = ("GROCERY", "CLUB", "DISCOUNT", "ECOMMERCE")
LIFECYCLE_STATES = ("PRELAUNCH", "RAMP", "MATURE", "RUNOUT", "DISCONTINUED",
                    "CANCELLED_NPI")
GRADES = ("UNGRADED", "A", "B", "C", "D")

ITEM_TRANSITIONS = {
    "PRELAUNCH": ("RAMP", "CANCELLED_NPI"),
    "RAMP": ("MATURE",),
    "MATURE": ("RUNOUT",),
    "RUNOUT": ("DISCONTINUED",),
    "DISCONTINUED": (),
    "CANCELLED_NPI": (),
}


def _unique(collection, field, value):
    for row in getattr(store, collection).values():
        if row[field] == value:
            raise bad_request("%s '%s' is already registered" % (field, value))


# ---------------------------------------------------------------- families
@bp.post("/sop/product-families")
@endpoint([ROLE_SOP_ADMIN])
def create_family():
    body = get_body()
    family_code = req_string(body, "family_code")
    name = req_string(body, "name", allow_empty=True)
    planner = req_string(body, "accountable_planner_user_id")
    units_per_hour = req_number(body, "units_per_hour", exclusive_min=0)
    max_monthly_hours = req_number(body, "max_monthly_hours", exclusive_min=0)
    _unique("families", "family_code", family_code)

    row = new_row()
    row.update({
        "family_code": family_code,
        "name": name,
        "accountable_planner_user_id": planner,
        "units_per_hour": units_per_hour,
        "max_monthly_hours": max_monthly_hours,
        "rolling_wmape_pct": None,
        "rolling_bias_pct": None,
        "bias_flag": "NONE",
        "accuracy_grade": "UNGRADED",
        "scored_record_count": 0,
    })
    store.families[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/sop/product-families/<family_id>")
@endpoint(READ_ROLES)
def get_family(family_id):
    row = find_or_404("families", family_id, "ERR_FAMILY_NOT_FOUND")
    return respond_object(public(row))


@bp.get("/sop/product-families")
@endpoint(READ_ROLES)
def list_families():
    limit, offset = pagination()
    planner = query_str("accountable_planner_user_id")
    grade = query_enum("accuracy_grade", GRADES)
    rows = ordered(store.families.values())
    if planner is not None:
        rows = [r for r in rows if r["accountable_planner_user_id"] == planner]
    if grade is not None:
        rows = [r for r in rows if r["accuracy_grade"] == grade]
    page, total = paginate(rows, limit, offset)
    return respond_list(public_all(page), limit, offset, total)


# ------------------------------------------------------------------- items
@bp.post("/sop/items")
@endpoint([ROLE_SOP_ADMIN])
def create_item():
    body = get_body()
    sku = req_string(body, "sku")
    family_id = req_string(body, "family_id")
    unit_price_cents = req_int(body, "unit_price_cents", exclusive_min=0)
    unit_cost_cents = req_int(body, "unit_cost_cents", exclusive_min=0)
    on_hand_units = req_int(body, "on_hand_units", minimum=0)
    material_supply_cap_units = req_int(body, "material_supply_cap_units", minimum=0)
    avg_monthly_demand_units = req_int(body, "avg_monthly_demand_units", minimum=0)
    npi_ramp_pct = opt_number(body, "npi_ramp_pct", default=100, minimum=0, maximum=200)
    service_level_target_pct = opt_number(body, "service_level_target_pct",
                                         default=95.0, exclusive_min=0, maximum=100)
    demand_cv = opt_number(body, "demand_cv", default=0.30, minimum=0, maximum=3)
    lead_time_days = opt_int(body, "lead_time_days", default=30, minimum=1)
    lifecycle_state = opt_enum(body, "lifecycle_state", LIFECYCLE_STATES,
                               default="MATURE")

    family = find_or_404("families", family_id, "ERR_FAMILY_NOT_FOUND")
    _unique("items", "sku", sku)

    row = new_row()
    row.update({
        "sku": sku,
        "family_id": family["id"],
        "unit_price_cents": unit_price_cents,
        "unit_cost_cents": unit_cost_cents,
        "on_hand_units": on_hand_units,
        "material_supply_cap_units": material_supply_cap_units,
        "avg_monthly_demand_units": avg_monthly_demand_units,
        "npi_ramp_pct": npi_ramp_pct,
        "service_level_target_pct": service_level_target_pct,
        "demand_cv": demand_cv,
        "lead_time_days": lead_time_days,
        "safety_stock_units": 0,
        "reorder_point_units": 0,
        "lifecycle_state": lifecycle_state,
        "successor_item_id": None,
        "runout_end_month": None,
    })
    calc_inventory_policy(row)
    store.items[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/sop/items/<item_id>")
@endpoint(READ_ROLES)
def get_item(item_id):
    row = find_or_404("items", item_id, "ERR_ITEM_NOT_FOUND")
    return respond_object(public(row))


@bp.get("/sop/items")
@endpoint(READ_ROLES)
def list_items():
    limit, offset = pagination()
    family_id = query_str("family_id")
    successor_item_id = query_str("successor_item_id")
    lifecycle_state = query_enum("lifecycle_state", LIFECYCLE_STATES)
    rows = ordered(store.items.values())
    if family_id is not None:
        rows = [r for r in rows if r["family_id"] == family_id]
    if successor_item_id is not None:
        rows = [r for r in rows if r["successor_item_id"] == successor_item_id]
    if lifecycle_state is not None:
        rows = [r for r in rows if r["lifecycle_state"] == lifecycle_state]
    page, total = paginate(rows, limit, offset)
    return respond_list(public_all(page), limit, offset, total)


@bp.post("/sop/items/<item_id>/inventory-policy")
@endpoint([ROLE_SOP_ADMIN, ROLE_SUPPLY_PLANNER])
def reset_inventory_policy(item_id):
    body = get_body()
    service_level_target_pct = req_number(body, "service_level_target_pct",
                                          exclusive_min=0, maximum=100)
    demand_cv = req_number(body, "demand_cv", minimum=0, maximum=3)
    lead_time_days = req_int(body, "lead_time_days", minimum=1)
    item = find_or_404("items", item_id, "ERR_ITEM_NOT_FOUND")

    item["service_level_target_pct"] = service_level_target_pct
    item["demand_cv"] = demand_cv
    item["lead_time_days"] = lead_time_days
    calc_inventory_policy(item)
    touch(item)
    stale_plans_of_item(item["id"])
    return respond_object(public(item))


@bp.post("/sop/items/<item_id>/lifecycle-transitions")
@endpoint([ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER])
def transition_item(item_id):
    body = get_body()
    target_state = req_enum(body, "target_state", LIFECYCLE_STATES)
    if target_state == "RUNOUT":
        runout_end_month = req_month(body, "runout_end_month")
    else:
        forbid(body, "runout_end_month",
               "is only accepted when target_state is RUNOUT")
        runout_end_month = None
    successor_item_id = opt_id(body, "successor_item_id")

    item = find_or_404("items", item_id, "ERR_ITEM_NOT_FOUND")
    successor = None
    if successor_item_id is not None:
        successor = find_or_404("items", successor_item_id, "ERR_ITEM_NOT_FOUND")

    if target_state not in ITEM_TRANSITIONS[item["lifecycle_state"]]:
        raise ApiError("ERR_ITEM_LIFECYCLE_TRANSITION_INVALID",
                       "An item in %s may not move to %s"
                       % (item["lifecycle_state"], target_state))

    if target_state == "RUNOUT" and successor is not None:
        if (successor["id"] == item["id"]
                or successor["family_id"] != item["family_id"]
                or successor["lifecycle_state"] not in ("PRELAUNCH", "RAMP")):
            raise ApiError("ERR_SUCCESSOR_NOT_ELIGIBLE",
                           "The nominated successor is not eligible")

    if target_state == "DISCONTINUED" and item["on_hand_units"] != 0:
        raise ApiError("ERR_RUNOUT_INVENTORY_REMAINS",
                       "Finished-goods inventory remains on the item")

    item["lifecycle_state"] = target_state

    if target_state == "CANCELLED_NPI":
        line_ids = set()
        for forecast in forecasts_of_item(item["id"]):
            line_ids.add(forecast["id"])
        for adjustment in ordered([a for a in store.adjustments.values()
                                   if a["demand_forecast_id"] in line_ids
                                   and a["adjustment_type"] == "NEW_ITEM_PLAN"]):
            if adjustment["status"] in ("PROPOSED", "ENDORSED", "COMMITTED"):
                void_adjustment(adjustment)
        for forecast in forecasts_of_item(item["id"]):
            if forecast["status"] in ("BASELINE", "UNDER_CONSENSUS",
                                      "CONSENSUS_LOCKED"):
                truncate_forecast(forecast)
        for promotion in promotions_of_item(item["id"]):
            if promotion["status"] in ("DRAFT", "APPROVED"):
                cancel_promotion_runout(promotion)

    elif target_state == "RUNOUT":
        item["runout_end_month"] = runout_end_month
        if successor is not None:
            item["successor_item_id"] = successor["id"]
        # hop one, and hop two through each cancelled promotion
        for promotion in promotions_of_item(item["id"]):
            if (promotion["status"] in ("DRAFT", "APPROVED")
                    and promotion["start_month"] > runout_end_month):
                cancel_promotion_runout(promotion)
        # hop three, alongside
        for forecast in forecasts_of_item(item["id"]):
            if (forecast["month"] > runout_end_month
                    and forecast["status"] in ("UNDER_CONSENSUS",
                                               "CONSENSUS_LOCKED")):
                truncate_forecast(forecast)

    touch(item)
    stale_plans_of_item(item["id"])
    return respond_object(public(item))


# --------------------------------------------------------------- customers
@bp.post("/sop/customers")
@endpoint([ROLE_SOP_ADMIN])
def create_customer():
    body = get_body()
    customer_code = req_string(body, "customer_code")
    name = req_string(body, "name", allow_empty=True)
    channel = req_enum(body, "channel", CHANNELS)
    priority_rank = req_int(body, "priority_rank", minimum=1)
    credit_hold = opt_bool(body, "credit_hold", default=False)
    _unique("customers", "customer_code", customer_code)

    row = new_row()
    row.update({
        "customer_code": customer_code,
        "name": name,
        "channel": channel,
        "priority_rank": priority_rank,
        "credit_hold": credit_hold,
    })
    store.customers[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/sop/customers/<customer_id>")
@endpoint(READ_ROLES + [ROLE_CUSTOMER_REP])
def get_customer(customer_id):
    row = find_or_404("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")
    return respond_object(public(row))


@bp.get("/sop/customers")
@endpoint(READ_ROLES)
def list_customers():
    limit, offset = pagination()
    channel = query_enum("channel", CHANNELS)
    credit_hold = query_bool("credit_hold")
    rows = ordered(store.customers.values())
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    if credit_hold is not None:
        rows = [r for r in rows if r["credit_hold"] == credit_hold]
    page, total = paginate(rows, limit, offset)
    return respond_list(public_all(page), limit, offset, total)
