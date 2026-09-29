"""Planning cycles (PRD 3.3, 3.5, 3.7) and the cycle accuracy summary (3.9)."""
from flask import Blueprint

from auth import (ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
                  ROLE_EXECUTIVE_SPONSOR, ROLE_SOP_ADMIN, ROLE_SUPPLY_PLANNER,
                  endpoint, find_or_404)
from calcs import (MAX_REOPENS, calc_accuracy_rollup, calc_cycle_financials,
                   calc_cycle_posture, rollup_consensus)
from cascades import (cycle_forecasts, cycle_plans, cycle_scenarios,
                      open_adjustments_in_cycle, recompute_cycle, stale_plan)
from envelope import respond_list, respond_object
from errors import ApiError, bad_request
from store import new_row, ordered, public, public_all, store, touch
from util import clock
from validators import (get_body, paginate, pagination, query_enum, query_str,
                        req_enum, req_int, req_month, req_string)

bp = Blueprint("cycles", __name__)

READ_ROLES = [ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
              ROLE_SUPPLY_PLANNER, ROLE_EXECUTIVE_SPONSOR]
SUMMARY_ROLES = [ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
                 ROLE_EXECUTIVE_SPONSOR]

CYCLE_STATUSES = ("DEMAND_REVIEW", "SUPPLY_REVIEW", "SCENARIO_REVIEW",
                  "EXECUTIVE_REVIEW", "PUBLISHED")
POSTURES = ("GREEN", "AT_RISK", "FROZEN")
POLICIES = ("NET_INVENTORY_FIRST", "GROSS_CAPACITY_FIRST")

CYCLE_TRANSITIONS = {
    "DEMAND_REVIEW": ("SUPPLY_REVIEW",),
    "SUPPLY_REVIEW": ("SCENARIO_REVIEW",),
    "SCENARIO_REVIEW": ("EXECUTIVE_REVIEW",),
    "EXECUTIVE_REVIEW": ("PUBLISHED", "DEMAND_REVIEW"),
    "PUBLISHED": (),
}


@bp.post("/sop/planning-cycles")
@endpoint([ROLE_SOP_ADMIN])
def create_cycle():
    body = get_body()
    cycle_code = req_string(body, "cycle_code")
    horizon_start_month = req_month(body, "horizon_start_month")
    horizon_end_month = req_month(body, "horizon_end_month")
    if horizon_end_month < horizon_start_month:
        raise bad_request("horizon_end_month may not precede horizon_start_month")
    financial_commitment_cents = req_int(body, "financial_commitment_cents",
                                        minimum=0)
    supply_review_policy = req_enum(body, "supply_review_policy", POLICIES)
    for other in store.cycles.values():
        if other["cycle_code"] == cycle_code:
            raise bad_request("cycle_code '%s' is already registered" % cycle_code)

    row = new_row()
    row.update({
        "cycle_code": cycle_code,
        "horizon_start_month": horizon_start_month,
        "horizon_end_month": horizon_end_month,
        "financial_commitment_cents": financial_commitment_cents,
        "supply_review_policy": supply_review_policy,
        "status": "DEMAND_REVIEW",
        "posture": "GREEN",
        "reopen_count": 0,
        "plan_value_cents": 0,
        "gross_gap_cents": 0,
        "selected_closure_cents": 0,
        "residual_gap_cents": 0,
        "constrained_plan_count": 0,
        "published_at": None,
    })
    calc_cycle_financials(row)
    calc_cycle_posture(row)
    store.cycles[row["id"]] = row
    return respond_object(public(row), 201)


@bp.post("/sop/planning-cycles/<cycle_id>/transitions")
@endpoint([ROLE_SOP_ADMIN, ROLE_EXECUTIVE_SPONSOR])
def transition_cycle(cycle_id):
    body = get_body()
    target_status = req_enum(body, "target_status", CYCLE_STATUSES)
    if target_status == "DEMAND_REVIEW":
        reopen_reason = req_string(body, "reopen_reason")
    else:
        reopen_reason = None

    cycle = find_or_404("cycles", cycle_id, "ERR_CYCLE_NOT_FOUND")

    if target_status not in CYCLE_TRANSITIONS[cycle["status"]]:
        raise ApiError("ERR_CYCLE_TRANSITION_INVALID",
                       "A cycle in %s may not move to %s"
                       % (cycle["status"], target_status))

    # priority 130 -- cross-entity referential eligibility
    if target_status == "SUPPLY_REVIEW":
        if open_adjustments_in_cycle(cycle["id"]):
            raise ApiError("ERR_OPEN_ADJUSTMENTS",
                           "An adjustment of this cycle is still open")
    elif target_status == "SCENARIO_REVIEW":
        for plan in cycle_plans(cycle["id"]):
            if plan["status"] == "STALE":
                raise ApiError("ERR_STALE_SUPPLY_PLAN",
                               "A supply plan of this cycle is stale")
    elif target_status == "EXECUTIVE_REVIEW":
        for scenario in cycle_scenarios(cycle["id"]):
            if scenario["status"] == "DRAFT":
                raise ApiError("ERR_UNEVALUATED_SCENARIO",
                               "A scenario of this cycle is still a draft")

    # priority 160 -- rate and volume safety limits
    if target_status == "DEMAND_REVIEW" and cycle["reopen_count"] >= MAX_REOPENS:
        raise ApiError("ERR_REOPEN_LIMIT_REACHED",
                       "The cycle has already been reopened %d times" % MAX_REOPENS)

    # priority 170 -- financial guardrails
    if target_status == "PUBLISHED" and cycle["residual_gap_cents"] > 0:
        raise ApiError("ERR_UNCLOSED_GAP",
                       "The cycle's residual gap is still greater than zero")

    cycle["status"] = target_status

    if target_status == "SUPPLY_REVIEW":
        for forecast in cycle_forecasts(cycle["id"]):
            if forecast["status"] in ("BASELINE", "UNDER_CONSENSUS"):
                rollup_consensus(forecast)
                forecast["status"] = "CONSENSUS_LOCKED"
                touch(forecast)
                for adjustment in ordered(
                        [a for a in store.adjustments.values()
                         if a["demand_forecast_id"] == forecast["id"]]):
                    if adjustment["status"] == "ENDORSED":
                        adjustment["status"] = "COMMITTED"
                        touch(adjustment)
    elif target_status == "PUBLISHED":
        for plan in cycle_plans(cycle["id"]):
            if plan["status"] in ("PLANNED", "RATIONED"):
                plan["status"] = "COMMITTED"
                touch(plan)
        for scenario in cycle_scenarios(cycle["id"]):
            if scenario["status"] == "SELECTED":
                scenario["status"] = "EXECUTED"
                touch(scenario)
        cycle["published_at"] = clock.now_iso()
    elif target_status == "DEMAND_REVIEW":
        cycle["reopen_count"] += 1
        for forecast in cycle_forecasts(cycle["id"]):
            if forecast["status"] == "CONSENSUS_LOCKED":
                forecast["status"] = "UNDER_CONSENSUS"
                touch(forecast)
        for scenario in cycle_scenarios(cycle["id"]):
            if scenario["status"] == "SELECTED":
                scenario["status"] = "SUPERSEDED"
                touch(scenario)
        for plan in cycle_plans(cycle["id"]):
            if plan["status"] in ("PLANNED", "RATIONED"):
                stale_plan(plan)

    recompute_cycle(cycle, bump=True)
    return respond_object(public(cycle))


@bp.get("/sop/planning-cycles/<cycle_id>")
@endpoint(READ_ROLES)
def get_cycle(cycle_id):
    row = find_or_404("cycles", cycle_id, "ERR_CYCLE_NOT_FOUND")
    return respond_object(public(row))


@bp.get("/sop/planning-cycles")
@endpoint(READ_ROLES)
def list_cycles():
    limit, offset = pagination()
    status = query_enum("status", CYCLE_STATUSES)
    posture = query_enum("posture", POSTURES)
    rows = ordered(store.cycles.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if posture is not None:
        rows = [r for r in rows if r["posture"] == posture]
    page, total = paginate(rows, limit, offset)
    return respond_list(public_all(page), limit, offset, total)


@bp.get("/sop/planning-cycles/<cycle_id>/accuracy-summary")
@endpoint(SUMMARY_ROLES)
def cycle_accuracy_summary(cycle_id):
    cycle = find_or_404("cycles", cycle_id, "ERR_CYCLE_NOT_FOUND")
    family_id = query_str("family_id")
    records = ordered([r for r in store.accuracy_records.values()
                       if r["cycle_id"] == cycle["id"]])
    if family_id is not None:
        item_ids = set(i["id"] for i in store.items.values()
                       if i["family_id"] == family_id)
        records = [r for r in records if r["item_id"] in item_ids]
    return respond_object(calc_accuracy_rollup(records))
