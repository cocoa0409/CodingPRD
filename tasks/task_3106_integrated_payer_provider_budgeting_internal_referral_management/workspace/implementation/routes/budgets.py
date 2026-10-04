"""RegionalBudget endpoints (PRD 3.7)."""

from flask import Blueprint

from constants import (
    ROLE_BUDGET_APPROPRIATIONS_COMMITTEE,
    ROLE_REGIONAL_FINANCE_OFFICER,
)
from db import STORE
from domain import (
    new_record,
    get_budget,
    get_region,
    raise_alert,
    recompute_region_aggregates,
    run_posture_ladder,
    store_row,
    touch,
)
from errors import (
    ERR_BUDGET_NOT_SUBMITTABLE,
    ERR_INVALID_STATE,
    raise_error,
)
from projections import region_view
from routes._common import (
    BUDGET_READERS,
    arg,
    filter_rows,
    list_response,
    payload,
    principal,
    require_field,
    single_response,
)

bp = Blueprint("budgets", __name__)


def _locked(token):
    return token


@bp.post("/regions/<region_id>/regional-budgets")
def create_budget(region_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    region = get_region(region_id)
    body = payload()
    view = region_view(region)
    row = new_record(
        region_id=region_id,
        period=require_field(body, "period"),
        premium_revenue_cents=view["premium_revenue_cents"],
        employed_delivery_cost_cents=view["employed_delivery_cost_cents"],
        staffing_budget_cents=require_field(body, "staffing_budget_cents"),
        outside_services_budget_cents=require_field(
            body, "outside_services_budget_cents"),
        outside_services_committed_cents=0,
        facility_investment_cents=require_field(body, "facility_investment_cents"),
        division_deductible_cents=require_field(body, "system_deductible_cents"),
        division_deductible_original_cents=require_field(
            body, "system_deductible_cents"),
        system_deductible_cents=require_field(body, "system_deductible_cents"),
        ort_contract_rate=1.0,
        division_liability_cents=0,
        net_liability_cents=0,
        operating_margin_cents=0,
        status="DRAFT",
    )
    store_row("budgets", row)
    return single_response("budgets", row, 201)


@bp.get("/regions/<region_id>/regional-budgets")
def list_region_budgets(region_id):
    principal(BUDGET_READERS)
    get_region(region_id)
    rows = [b for b in STORE.budgets.values() if b.get("region_id") == region_id]
    rows = filter_rows(rows, period=arg("period"), status=arg("status"))
    return list_response("budgets", rows)


@bp.get("/regional-budgets")
def list_budgets():
    principal(BUDGET_READERS)
    rows = list(STORE.budgets.values())
    rows = filter_rows(rows, region_id=arg("region_id"), status=arg("status"))
    return list_response("budgets", rows)


@bp.get("/regional-budgets/<budget_id>")
def get_one_budget(budget_id):
    principal(BUDGET_READERS)
    return single_response("budgets", get_budget(budget_id))


@bp.post("/regional-budgets/<budget_id>/submit")
def submit_budget(budget_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    budget = get_budget(budget_id)
    if budget.get("status") not in ("DRAFT", "REOPENED"):
        raise_error(ERR_BUDGET_NOT_SUBMITTABLE)

    region_id = budget["region_id"]
    region = get_region(region_id)
    from projections import regional_budget_view
    view = regional_budget_view(budget)
    if view["operating_margin_cents"] < 0 and region_view(region)["posture"] == "FROZEN":
        raise_error(ERR_BUDGET_NOT_SUBMITTABLE)

    budget["status"] = "SUBMITTED"
    budget["operating_margin_cents"] = view["operating_margin_cents"]
    touch(budget)

    recompute_region_aggregates(region_id, bump_version=True)

    if view["operating_margin_cents"] < 0:
        raise_alert(region_id, "BUDGET_BREACH", "WARNING",
                    "RegionalBudget", budget_id)
        recompute_region_aggregates(region_id, bump_version=False)

    run_posture_ladder(region_id)
    return single_response("budgets", budget)


@bp.post("/regional-budgets/<budget_id>/approve")
def approve_budget(budget_id):
    principal((ROLE_BUDGET_APPROPRIATIONS_COMMITTEE,))
    budget = get_budget(budget_id)
    if budget.get("status") != "SUBMITTED":
        raise_error(ERR_INVALID_STATE)
    region = get_region(budget["region_id"])
    view = region_view(region)
    budget["premium_revenue_cents"] = view["premium_revenue_cents"]
    budget["employed_delivery_cost_cents"] = view["employed_delivery_cost_cents"]
    budget["status"] = "APPROVED"
    touch(budget)
    return single_response("budgets", budget)


@bp.post("/regional-budgets/<budget_id>/return")
def return_budget(budget_id):
    principal((ROLE_BUDGET_APPROPRIATIONS_COMMITTEE,))
    budget = get_budget(budget_id)
    if budget.get("status") != "SUBMITTED":
        raise_error(ERR_INVALID_STATE)
    budget["status"] = "DRAFT"
    touch(budget)
    return single_response("budgets", budget)


@bp.post("/regional-budgets/<budget_id>/close")
def close_budget(budget_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    budget = get_budget(budget_id)
    if budget.get("status") != "APPROVED":
        raise_error(ERR_INVALID_STATE)
    budget["status"] = "CLOSED"
    touch(budget)
    return single_response("budgets", budget)


@bp.post("/regional-budgets/<budget_id>/reopen")
def reopen_budget(budget_id):
    principal((ROLE_BUDGET_APPROPRIATIONS_COMMITTEE,))
    budget = get_budget(budget_id)
    if budget.get("status") not in ("APPROVED", "CLOSED"):
        raise_error(ERR_INVALID_STATE)
    budget["status"] = "REOPENED"
    touch(budget)
    return single_response("budgets", budget)