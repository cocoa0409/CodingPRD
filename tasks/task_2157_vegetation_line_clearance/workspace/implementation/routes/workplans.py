"""Work-plan endpoints."""
from flask import Blueprint, request

import envelope
import services
import store
import validate as V
from auth import ALL_ROLES, endpoint
from errors import ApiError

bp = Blueprint("workplans", __name__)


@bp.post("/vm/work-plans")
@endpoint(["UtilityForester"])
def create_plan():
    data = V.body()
    circuit = V.body_fk(data, "circuit_id", store.circuits, "ERR_CIRCUIT_NOT_FOUND")
    if circuit is None:
        V.require(data, "circuit_id")
    program_year = V.as_integer(data, "program_year", minimum=2000, maximum=2100)
    span_miles = V.as_number(data, "planned_span_miles", minimum=0, exclusive_min=True)
    budget_cents = V.as_integer(data, "budget_cents", minimum=0)

    rec = store.new_record()
    rec.update({
        "circuit_id": circuit["id"],
        "program_year": program_year,
        "planned_span_miles": span_miles,
        "budget_cents": budget_cents,
        "planned_unit_count": 0,
        "completed_unit_count": 0,
        "production_pct": 0.00,
        "committed_cents": 0,
        "status": "DRAFT",
    })
    store.work_plans[rec["id"]] = rec
    return envelope.created(store.public(rec))


@bp.post("/vm/work-plans/<pid>/release")
@endpoint(["ContractorPlanner"])
def release_plan(pid):
    plan = V.find(store.work_plans, pid, "ERR_WORK_PLAN_NOT_FOUND")
    services.require_state(plan, "work_plan", ["DRAFT"])
    mapped = [w for w in services.plan_orders(plan["id"])
              if w.get("execution_status") == "MAPPED"]
    if not mapped:
        raise ApiError("ERR_EMPTY_WORK_PLAN", "the plan has no MAPPED span")
    plan["status"] = "RELEASED"
    store.touch(plan)
    circuit = services.circuit_of_plan(plan)
    if circuit is not None and circuit.get("trim_status") == "NOT_SCHEDULED":
        services.set_trim_status(circuit, "SCHEDULED")
    return envelope.ok(store.public(plan))


@bp.post("/vm/work-plans/<pid>/cancel")
@endpoint(["UtilityForester"])
def cancel_plan(pid):
    plan = V.find(store.work_plans, pid, "ERR_WORK_PLAN_NOT_FOUND")
    services.require_state(plan, "work_plan",
                           ["DRAFT", "RELEASED", "IN_PROGRESS", "SUSPENDED"])
    for work_order in services.plan_orders(plan["id"]):
        if work_order.get("execution_status") not in ("COMPLETED", "CANCELLED"):
            services.cancel_order(work_order)
        voided = False
        for line in services.order_lines(work_order["id"]):
            if line.get("status") == "DRAFT":
                line["status"] = "VOID"
                store.touch(line)
                voided = True
        if voided or work_order.get("execution_status") == "CANCELLED":
            services.derive_billing_status(work_order)
    plan["status"] = "CANCELLED"
    services.recompute_plan(plan, bump=False)
    services.recompute_committed(plan, bump=False)
    store.touch(plan)
    circuit = services.circuit_of_plan(plan)
    services.set_trim_status(circuit, "NOT_SCHEDULED")
    return envelope.ok(store.public(plan))


@bp.get("/vm/work-plans/<pid>")
@endpoint(ALL_ROLES)
def get_plan(pid):
    plan = V.find(store.work_plans, pid, "ERR_WORK_PLAN_NOT_FOUND")
    return envelope.ok(store.public(plan))


@bp.get("/vm/work-plans")
@endpoint(ALL_ROLES)
def list_plans():
    rows = list(store.work_plans.values())
    year = request.args.get("program_year")
    if year is not None:
        try:
            year_value = int(str(year).strip())
        except ValueError:
            year_value = None
        rows = [r for r in rows if r.get("program_year") == year_value]
    return envelope.list_response(rows, {
        "circuit_id": request.args.get("circuit_id"),
        "status": request.args.get("status"),
    })


@bp.get("/vm/work-plans/<pid>/production-summary")
@endpoint(ALL_ROLES)
def production_summary(pid):
    plan = V.find(store.work_plans, pid, "ERR_WORK_PLAN_NOT_FOUND")
    services.recompute_plan(plan, bump=False)
    services.recompute_committed(plan, bump=False)
    return envelope.ok({
        "work_plan_id": plan["id"],
        "planned_unit_count": plan.get("planned_unit_count"),
        "completed_unit_count": plan.get("completed_unit_count"),
        "production_pct": plan.get("production_pct"),
        "committed_cents": plan.get("committed_cents"),
        "budget_remaining_cents": int(plan.get("budget_cents") or 0)
        - int(plan.get("committed_cents") or 0),
        "crew_production_rate": services.crew_production_rate(plan),
    })
