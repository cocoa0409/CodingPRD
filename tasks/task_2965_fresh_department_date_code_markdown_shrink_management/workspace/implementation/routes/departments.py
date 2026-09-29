"""Department and item endpoints plus the margin reads and the ops run."""
from flask import Blueprint

import calc
import services
from db import db
from errors import ApiError, bad_request
from middleware import (ROLE_ADMIN, ROLE_AUDITOR, ROLE_CLERK, ROLE_MANAGER,
                        authenticate)
from records import (department_by_id, item_by_id, ladder_by_id, new_record,
                     store_by_id, touch)
from response import created, ok, public
from routes.common import (COMPLIANCE_STATUSES, DEPARTMENT_CODES,
                           ITEM_STATUSES, POLICY_PROFILES, POLICY_PROFILES,
                           UPC_RE, listing, matches)
from util import D, num
from validate import (MISSING, field_bool, field_enum, field_int, field_number,
                      field_string, json_body, query_date, query_enum,
                      query_string)

bp = Blueprint("departments", __name__)

READ_ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_CLERK, ROLE_AUDITOR)


def _window_dates():
    """Both query dates are required (400) before the window rule (422)."""
    start = query_date("window_start_date", required=True)
    end = query_date("window_end_date", required=True)
    return start, end


def _check_window(start, end):
    if end < start:
        raise ApiError("ERR_RECOMMENDATION_WINDOW_INVALID",
                       "window_end_date precedes window_start_date")
    if (end - start).days + 1 > 31:
        raise ApiError("ERR_RECOMMENDATION_WINDOW_INVALID",
                       "The window spans more than 31 days")


# --- departments -----------------------------------------------------------
@bp.get("/fresh/departments/<department_id>")
def get_department(department_id):
    authenticate(*READ_ROLES)
    return ok(public(department_by_id(department_id)))


@bp.get("/fresh/departments")
def list_departments():
    authenticate(*READ_ROLES)
    store_id = query_string("store_id")
    ladder_id = query_string("markdown_ladder_id")
    code = query_enum("code", DEPARTMENT_CODES)
    status = query_enum("compliance_status", COMPLIANCE_STATUSES)
    rows = [
        d for d in db.departments.values()
        if matches(d, "store_id", store_id)
        and matches(d, "markdown_ladder_id", ladder_id)
        and matches(d, "code", code)
        and matches(d, "compliance_status", status)
    ]
    return listing(rows)


@bp.post("/fresh/departments")
def create_department():
    authenticate(ROLE_ADMIN)
    body = json_body()
    store_id = field_string(body, "store_id", required=True, max_len=200)
    ladder_id = field_string(body, "markdown_ladder_id", required=True,
                             max_len=200)
    code = field_enum(body, "code", DEPARTMENT_CODES, required=True)
    shelf_life = field_int(body, "shelf_life_days_default", required=True,
                           minimum=1, maximum=60)
    tolerance = field_int(body, "past_date_tolerance_hours", default=4,
                          minimum=0, maximum=72)
    budget = field_number(body, "shrink_budget_pct", default=D("2.5"),
                          exclusive_min=0, maximum=100)
    profile = field_enum(body, "markdown_policy_profile", POLICY_PROFILES,
                         default="STANDARD")
    store = store_by_id(store_id)
    ladder = ladder_by_id(ladder_id)
    if ladder["department_code"] != code:
        raise ApiError("ERR_LADDER_DEPARTMENT_MISMATCH",
                       "Ladder department_code does not match the department")
    for existing in db.departments.values():
        if existing["store_id"] == store["id"] and existing["code"] == code:
            raise ApiError("ERR_DEPARTMENT_CODE_DUPLICATE",
                           "This store already has a %s department" % code)
    record = new_record(db.departments, {
        "store_id": store["id"],
        "markdown_ladder_id": ladder["id"],
        "code": code,
        "shelf_life_days_default": shelf_life,
        "past_date_tolerance_hours": tolerance,
        "shrink_budget_pct": num(budget),
        "markdown_policy_profile": profile,
        "compliance_status": "COMPLIANT",
        "markdown_liability_cents": 0,
        "shrink_cost_ratio_pct": 0,
        "sweep_epoch": 0,
        "open_finding_count": 0,
    })
    return created(public(record))


@bp.patch("/fresh/departments/<department_id>")
def patch_department(department_id):
    authenticate(ROLE_ADMIN, ROLE_MANAGER)
    body = json_body()
    ladder_id = field_string(body, "markdown_ladder_id", default=MISSING,
                             max_len=200)
    shelf_life = field_int(body, "shelf_life_days_default", default=MISSING,
                           minimum=1, maximum=60)
    tolerance = field_int(body, "past_date_tolerance_hours", default=MISSING,
                          minimum=0, maximum=72)
    budget = field_number(body, "shrink_budget_pct", default=MISSING,
                          exclusive_min=0, maximum=100)
    profile = field_enum(body, "markdown_policy_profile", POLICY_PROFILES,
                         default=MISSING)
    department = department_by_id(department_id)
    ladder = None
    if ladder_id is not MISSING:
        ladder = ladder_by_id(ladder_id)
        if ladder["department_code"] != department["code"]:
            raise ApiError("ERR_LADDER_DEPARTMENT_MISMATCH",
                           "Ladder department_code does not match")
    if ladder is not None:
        department["markdown_ladder_id"] = ladder["id"]
    if shelf_life is not MISSING:
        department["shelf_life_days_default"] = shelf_life
    if tolerance is not MISSING:
        department["past_date_tolerance_hours"] = tolerance
    if profile is not MISSING:
        department["markdown_policy_profile"] = profile
    budget_changed = False
    if budget is not MISSING:
        if num(budget) != department["shrink_budget_pct"]:
            budget_changed = True
        department["shrink_budget_pct"] = num(budget)
    touch(department)
    if budget_changed:
        services.recompute_posture(department)
    return ok(public(department))


@bp.get("/fresh/departments/<department_id>/margin-report")
def margin_report(department_id):
    authenticate(ROLE_ADMIN, ROLE_MANAGER, ROLE_AUDITOR)
    start, end = _window_dates()
    department = department_by_id(department_id)
    _check_window(start, end)
    totals = calc.margin_report_for_department(department, start, end)
    return ok({
        "department_id": department["id"],
        "window_start_date": start.isoformat(),
        "window_end_date": end.isoformat(),
        "lot_count": totals["lot_count"],
        "revenue_cents": totals["revenue_cents"],
        "markdown_giveback_cents": totals["markdown_giveback_cents"],
        "cogs_cents": totals["cogs_cents"],
        "shrink_cost_cents": totals["shrink_cost_cents"],
        "donation_cost_cents": totals["donation_cost_cents"],
        "gross_margin_cents": totals["gross_margin_cents"],
        "gross_margin_pct": totals["gross_margin_pct"],
        "shrink_cost_ratio_pct": totals["shrink_cost_ratio_pct"],
    })


@bp.get("/fresh/stores/<store_id>/margin-rollup")
def margin_rollup(store_id):
    authenticate(ROLE_ADMIN, ROLE_AUDITOR)
    start, end = _window_dates()
    store = store_by_id(store_id)
    _check_window(start, end)
    departments = [
        d for d in db.departments.values() if d["store_id"] == store["id"]
    ]
    lines = {
        "revenue_cents": 0,
        "markdown_giveback_cents": 0,
        "cogs_cents": 0,
        "shrink_cost_cents": 0,
        "donation_cost_cents": 0,
    }
    for department in departments:
        totals = calc.margin_report_for_department(department, start, end)
        for key in lines:
            lines[key] = lines[key] + totals[key]
    rolled = calc.margin_totals(lines)
    return ok({
        "store_id": store["id"],
        "window_start_date": start.isoformat(),
        "window_end_date": end.isoformat(),
        "department_count": len(departments),
        "revenue_cents": rolled["revenue_cents"],
        "markdown_giveback_cents": rolled["markdown_giveback_cents"],
        "cogs_cents": rolled["cogs_cents"],
        "shrink_cost_cents": rolled["shrink_cost_cents"],
        "donation_cost_cents": rolled["donation_cost_cents"],
        "gross_margin_cents": rolled["gross_margin_cents"],
        "gross_margin_pct": rolled["gross_margin_pct"],
        "shrink_cost_ratio_pct": rolled["shrink_cost_ratio_pct"],
    })


@bp.post("/fresh/departments/<department_id>/run-date-code-sweep")
def run_date_code_sweep(department_id):
    authenticate(ROLE_ADMIN, ROLE_MANAGER)
    json_body()
    department = department_by_id(department_id)
    return ok(services.run_department_sweep(department))


# --- items -----------------------------------------------------------------
@bp.get("/fresh/items/<item_id>")
def get_item(item_id):
    authenticate(*READ_ROLES)
    return ok(public(item_by_id(item_id)))


@bp.get("/fresh/items")
def list_items():
    authenticate(*READ_ROLES)
    department_id = query_string("department_id")
    status = query_enum("status", ITEM_STATUSES)
    rows = [
        i for i in db.items.values()
        if matches(i, "department_id", department_id)
        and matches(i, "status", status)
    ]
    return listing(rows)


@bp.post("/fresh/items")
def create_item():
    authenticate(ROLE_ADMIN, ROLE_MANAGER)
    body = json_body()
    department_id = field_string(body, "department_id", required=True,
                                max_len=200)
    upc = field_string(body, "upc", required=True, min_len=12, max_len=12,
                       pattern=UPC_RE)
    description = field_string(body, "description", required=True, min_len=1,
                               max_len=120)
    base_retail = field_int(body, "base_retail_cents", required=True, minimum=1)
    unit_cost = field_int(body, "unit_cost_cents", required=True, minimum=1)
    forecast = field_number(body, "daily_forecast_units", required=True,
                            exclusive_min=0)
    shelf_life = field_int(body, "shelf_life_days", default=None, nullable=True,
                           minimum=1, maximum=60)
    donation_eligible = field_bool(body, "donation_eligible", default=True)
    sampling_allowed = field_bool(body, "sampling_allowed", default=False)
    status = field_enum(body, "status", ITEM_STATUSES, default="ACTIVE")
    if unit_cost >= base_retail:
        raise bad_request("unit_cost_cents must be below base_retail_cents")
    department = department_by_id(department_id)
    for existing in db.items.values():
        if (existing["department_id"] == department["id"]
                and existing["upc"] == upc):
            raise ApiError("ERR_ITEM_UPC_DUPLICATE",
                           "UPC %s already exists in this department" % upc)
    record = new_record(db.items, {
        "department_id": department["id"],
        "upc": upc,
        "description": description,
        "base_retail_cents": base_retail,
        "unit_cost_cents": unit_cost,
        "shelf_life_days": shelf_life,
        "donation_eligible": donation_eligible,
        "sampling_allowed": sampling_allowed,
        "daily_forecast_units": num(forecast),
        "status": status,
    })
    return created(public(record))


@bp.patch("/fresh/items/<item_id>")
def patch_item(item_id):
    authenticate(ROLE_ADMIN, ROLE_MANAGER)
    body = json_body()
    status = field_enum(body, "status", ITEM_STATUSES, default=MISSING)
    forecast = field_number(body, "daily_forecast_units", default=MISSING,
                            exclusive_min=0)
    donation_eligible = field_bool(body, "donation_eligible", default=MISSING)
    sampling_allowed = field_bool(body, "sampling_allowed", default=MISSING)
    item = item_by_id(item_id)
    if status is not MISSING:
        item["status"] = status
    if forecast is not MISSING:
        item["daily_forecast_units"] = num(forecast)
    if donation_eligible is not MISSING:
        item["donation_eligible"] = donation_eligible
    if sampling_allowed is not MISSING:
        item["sampling_allowed"] = sampling_allowed
    touch(item)
    return ok(public(item))
