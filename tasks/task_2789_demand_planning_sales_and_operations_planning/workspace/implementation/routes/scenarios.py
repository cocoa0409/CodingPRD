"""Gap-closing scenarios: draft, evaluate, select (PRD 3.7)."""
from flask import Blueprint, g

from auth import (ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
                  ROLE_EXECUTIVE_SPONSOR, ROLE_SOP_ADMIN, ROLE_SUPPLY_PLANNER,
                  check_frozen, check_phase_actor, check_phase_closed,
                  check_sod, endpoint, find_or_404, phase_gate)
from calcs import active_plan_for, calc_scenario_gap_closure, scenarios_of
from cascades import recompute_cycle
from envelope import respond_list, respond_object
from errors import ApiError
from store import new_row, ordered, public, public_all, store, touch
from validators import (forbid, get_body, paginate, pagination, query_enum,
                        query_str, req_enum, req_id, req_int, req_number,
                        req_string)

bp = Blueprint("scenarios", __name__)

WRITE_ROLES = [ROLE_SUPPLY_PLANNER, ROLE_EXECUTIVE_SPONSOR]
READ_ROLES = [ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
              ROLE_SUPPLY_PLANNER, ROLE_EXECUTIVE_SPONSOR]

SCENARIO_TYPES = ("CAPACITY_INVESTMENT", "PRICE_REALIZATION")
SCENARIO_STATUSES = ("DRAFT", "EVALUATED", "SELECTED", "SUPERSEDED", "EXECUTED")


@bp.post("/sop/scenarios")
@endpoint(WRITE_ROLES)
def create_scenario():
    body = get_body()
    cycle_id = req_id(body, "cycle_id")
    name = req_string(body, "name")
    scenario_type = req_enum(body, "scenario_type", SCENARIO_TYPES)
    if scenario_type == "CAPACITY_INVESTMENT":
        target_item_id = req_id(body, "target_item_id")
        added_capacity_hours = req_number(body, "added_capacity_hours",
                                         exclusive_min=0)
        forbid(body, "price_increase_pct",
               "is only accepted for a PRICE_REALIZATION scenario")
        price_increase_pct = None
    else:
        price_increase_pct = req_number(body, "price_increase_pct",
                                       exclusive_min=0, maximum=100)
        forbid(body, "target_item_id",
               "is only accepted for a CAPACITY_INVESTMENT scenario")
        forbid(body, "added_capacity_hours",
               "is only accepted for a CAPACITY_INVESTMENT scenario")
        target_item_id = None
        added_capacity_hours = None

    cycle = find_or_404("cycles", cycle_id, "ERR_CYCLE_NOT_FOUND")
    if target_item_id is not None:
        find_or_404("items", target_item_id, "ERR_ITEM_NOT_FOUND")

    phase_gate(cycle, "SCENARIO_REVIEW")

    row = new_row()
    row.update({
        "cycle_id": cycle_id,
        "scenario_type": scenario_type,
        "name": name,
        "target_item_id": target_item_id,
        "added_capacity_hours": added_capacity_hours,
        "price_increase_pct": price_increase_pct,
        "incremental_units": 0,
        "gross_uplift_cents": 0,
        "investment_cost_cents": 0,
        "pre_trade_closure_cents": 0,
        "trade_rate_pct": 0,
        "trade_spend_cents": 0,
        "net_gap_closure_cents": 0,
        "status": "DRAFT",
        "created_by_user_id": g.user_id,
        "selected_by_user_id": None,
    })
    store.scenarios[row["id"]] = row
    return respond_object(public(row), 201)


@bp.post("/sop/scenarios/<scenario_id>/evaluate")
@endpoint(WRITE_ROLES)
def evaluate_scenario(scenario_id):
    get_body()
    scenario = find_or_404("scenarios", scenario_id, "ERR_SCENARIO_NOT_FOUND")
    cycle = store.cycles.get(scenario["cycle_id"])
    if cycle is not None:
        phase_gate(cycle, "SCENARIO_REVIEW")

    if scenario["status"] != "DRAFT":
        raise ApiError("ERR_SCENARIO_NOT_EVALUATABLE",
                       "A scenario in %s may not be evaluated" % scenario["status"])

    if scenario["scenario_type"] == "CAPACITY_INVESTMENT":
        plan = active_plan_for(cycle["id"], scenario["target_item_id"])
        if plan is None:
            raise ApiError("ERR_SUPPLY_PLAN_NOT_FOUND",
                           "No live supply plan exists for this cycle and "
                           "target item")

    calc_scenario_gap_closure(scenario, cycle)
    scenario["status"] = "EVALUATED"
    touch(scenario)
    # Evaluation deliberately does not touch the cycle's money fields.
    return respond_object(public(scenario))


@bp.post("/sop/scenarios/<scenario_id>/select")
@endpoint([ROLE_EXECUTIVE_SPONSOR])
def select_scenario(scenario_id):
    body = get_body()
    expected_cycle_version = req_int(body, "expected_cycle_version")

    scenario = find_or_404("scenarios", scenario_id, "ERR_SCENARIO_NOT_FOUND")
    cycle = store.cycles.get(scenario["cycle_id"])

    if cycle is not None:
        check_phase_actor(cycle, "EXECUTIVE_REVIEW")
    check_sod(scenario["created_by_user_id"], "created this scenario")
    if cycle is not None:
        if expected_cycle_version != cycle["version"]:
            raise ApiError("ERR_STALE_CYCLE_VERSION",
                           "The planning cycle is at version %d, not %d"
                           % (cycle["version"], expected_cycle_version))
        check_frozen(cycle)
        check_phase_closed(cycle, "EXECUTIVE_REVIEW")

    if scenario["status"] != "EVALUATED":
        raise ApiError("ERR_SCENARIO_NOT_SELECTABLE",
                       "A scenario in %s may not be selected" % scenario["status"])

    if scenario["scenario_type"] == "CAPACITY_INVESTMENT":
        if active_plan_for(cycle["id"], scenario["target_item_id"]) is None:
            raise ApiError("ERR_STALE_SUPPLY_PLAN",
                           "The scenario's target supply plan has gone stale")

    scenario["selected_by_user_id"] = g.user_id
    scenario["status"] = "SELECTED"
    touch(scenario)

    for other in ordered(scenarios_of(cycle["id"])):
        if (other["id"] != scenario["id"]
                and other["scenario_type"] == scenario["scenario_type"]
                and other["status"] == "SELECTED"):
            other["status"] = "SUPERSEDED"
            touch(other)

    recompute_cycle(cycle, bump=True)
    return respond_object(public(scenario))


@bp.get("/sop/scenarios/<scenario_id>")
@endpoint(READ_ROLES)
def get_scenario(scenario_id):
    row = find_or_404("scenarios", scenario_id, "ERR_SCENARIO_NOT_FOUND")
    return respond_object(public(row))


@bp.get("/sop/scenarios")
@endpoint(READ_ROLES)
def list_scenarios():
    limit, offset = pagination()
    cycle_id = query_str("cycle_id")
    target_item_id = query_str("target_item_id")
    status = query_enum("status", SCENARIO_STATUSES)
    scenario_type = query_enum("scenario_type", SCENARIO_TYPES)
    rows = ordered(store.scenarios.values())
    if cycle_id is not None:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if target_item_id is not None:
        rows = [r for r in rows if r["target_item_id"] == target_item_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if scenario_type is not None:
        rows = [r for r in rows if r["scenario_type"] == scenario_type]
    page, total = paginate(rows, limit, offset)
    return respond_list(public_all(page), limit, offset, total)
