"""NetworkService and CapacityPlan endpoints."""

from flask import Blueprint

from constants import (
    ROLE_ACCESS_SCHEDULER,
    ROLE_REGIONAL_FINANCE_OFFICER,
)
from calculations import meets_commissioning_ratio, supply_shortfall_slots
from db import STORE
from domain import (
    capacity_plan_for,
    committed_appointments_for,
    enforce_posture_gate,
    get_capacity_plan,
    get_department,
    get_referral,
    get_region,
    new_record,
    recompute_region_aggregates,
    refresh_capacity_plan,
    require_body_reference,
    run_posture_ladder,
    store_row,
    touch,
)
from errors import (
    ERR_CAPACITY_PLAN_NOT_ACTIVATABLE,
    ERR_CROSS_REGION_REFERENCE,
    ERR_DUPLICATE_CAPACITY_PLAN,
    ERR_DUPLICATE_NETWORK_SERVICE,
    ERR_INVALID_STATE,
    ERR_NETWORK_SERVICE_NOT_FOUND,
    ERR_REGION_POSTURE_FROZEN,
    raise_error,
)
from routes._common import (
    CAPACITY_READERS,
    READERS,
    arg,
    filter_rows,
    list_response,
    optional_field,
    payload,
    principal,
    require_field,
    single_response,
)
from projections import region_view

bp = Blueprint("network", __name__)

NETWORK_READERS = READERS


@bp.post("/regions/<region_id>/network-services")
def create_network_service(region_id):
    principal((ROLE_ACCESS_SCHEDULER,))
    get_region(region_id)
    body = payload()
    for service in STORE.network_services.values():
        if (service.get("region_id") == region_id
                and service.get("service_code") == body.get("service_code")):
            raise_error(ERR_DUPLICATE_NETWORK_SERVICE)
    row = new_record(
        region_id=region_id,
        service_code=require_field(body, "service_code"),
        service_name=require_field(body, "service_name"),
        availability_status=optional_field(body, "availability_status", "AVAILABLE"),
        available_provider_count=0,
        capacity_note=optional_field(body, "capacity_note", None),
    )
    store_row("network_services", row)
    return single_response("network_services", row, 201)


@bp.get("/regions/<region_id>/network-services")
def list_region_network_services(region_id):
    principal(NETWORK_READERS)
    get_region(region_id)
    rows = [s for s in STORE.network_services.values()
            if s.get("region_id") == region_id]
    rows = filter_rows(rows, availability_status=arg("availability_status"))
    return list_response("network_services", rows)


@bp.get("/network-services/<service_id>")
def get_one_network_service(service_id):
    principal(NETWORK_READERS)
    service = STORE.network_services.get(service_id)
    if service is None:
        raise_error(ERR_NETWORK_SERVICE_NOT_FOUND)
    return single_response("network_services", service)


# ------------------------------------------------------------- CapacityPlan

def _refresh_plan_committed_slots(plan):
    """PRD 3.3: committed_slots counts the department's appointments for the
    plan period whose fulfillment_status is REQUESTED, SCHEDULED or COMPLETED,
    and supply_shortfall_slots is that count minus budgeted_slots, floored at
    zero. Every recomputation advances recalculation_epoch by one."""
    committed = len(committed_appointments_for(
        plan["department_id"], plan.get("period")))
    plan["committed_slots"] = committed
    plan["supply_shortfall_slots"] = supply_shortfall_slots(
        committed, plan.get("budgeted_slots", 0))
    plan["recalculation_epoch"] = int(plan.get("recalculation_epoch", 1) or 1) + 1
    return plan


def _create_capacity_plan(region_id, department_id, body):
    department = get_department(department_id)
    if department.get("region_id") != region_id:
        raise_error(ERR_CROSS_REGION_REFERENCE)
    period = require_field(body, "period")
    if capacity_plan_for(department_id, period) is not None:
        raise_error(ERR_DUPLICATE_CAPACITY_PLAN)
    enforce_posture_gate(region_id)
    row = new_record(
        region_id=region_id,
        department_id=department_id,
        period=period,
        budgeted_slots=require_field(body, "budgeted_slots"),
        committed_slots=0,
        supply_shortfall_slots=0,
        panel_target=require_field(body, "panel_target"),
        recalculation_epoch=1,
        status="PLANNING",
    )
    store_row("capacity_plans", row)
    # PRD 3.3: committed_slots and supply_shortfall_slots are computed at
    # creation (the department's non-cancelled appointments for the period).
    _refresh_plan_committed_slots(row)
    recompute_region_aggregates(region_id, bump_version=False)
    return row


@bp.post("/regions/<region_id>/capacity-plans")
def create_capacity_plan(region_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    get_region(region_id)
    body = payload()
    department_id = require_field(body, "department_id")
    require_body_reference("departments", department_id)
    row = _create_capacity_plan(region_id, department_id, body)
    return single_response("capacity_plans", row, 201)


@bp.post("/referrals/<referral_id>/capacity-plans")
def create_referral_capacity_plan(referral_id):
    principal((ROLE_ACCESS_SCHEDULER,))
    referral = get_referral(referral_id)
    department_id = referral.get("target_department_id")
    department = get_department(department_id)
    body = payload()
    row = _create_capacity_plan(department["region_id"], department_id, body)
    return single_response("capacity_plans", row, 201)


@bp.get("/regions/<region_id>/capacity-plans")
def list_region_capacity_plans(region_id):
    principal(CAPACITY_READERS)
    get_region(region_id)
    rows = [p for p in STORE.capacity_plans.values()
            if p.get("region_id") == region_id]
    rows = filter_rows(rows, department_id=arg("department_id"),
                       period=arg("period"), status=arg("status"))
    return list_response("capacity_plans", rows)


@bp.get("/capacity-plans")
def list_capacity_plans():
    principal(CAPACITY_READERS)
    rows = list(STORE.capacity_plans.values())
    rows = filter_rows(rows, region_id=arg("region_id"),
                       department_id=arg("department_id"),
                       period=arg("period"), status=arg("status"))
    return list_response("capacity_plans", rows)


@bp.get("/capacity-plans/<plan_id>")
def get_one_capacity_plan(plan_id):
    principal(CAPACITY_READERS)
    return single_response("capacity_plans", get_capacity_plan(plan_id))


@bp.post("/capacity-plans/<plan_id>/review")
def review_capacity_plan(plan_id):
    principal((ROLE_ACCESS_SCHEDULER,))
    plan = get_capacity_plan(plan_id)
    if plan.get("status") not in ("PLANNING", "ADJUSTED"):
        raise_error(ERR_INVALID_STATE)
    if not meets_commissioning_ratio(plan.get("budgeted_slots", 0),
                                     plan.get("panel_target", 0)):
        raise_error(ERR_INVALID_STATE)
    plan["status"] = "UNDER_REVIEW"
    touch(plan)
    recompute_region_aggregates(plan["region_id"], bump_version=False)
    return single_response("capacity_plans", plan)


@bp.post("/capacity-plans/<plan_id>/return")
def return_capacity_plan(plan_id):
    principal((ROLE_ACCESS_SCHEDULER,))
    plan = get_capacity_plan(plan_id)
    if plan.get("status") != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE)
    plan["status"] = "PLANNING"
    touch(plan)
    recompute_region_aggregates(plan["region_id"], bump_version=False)
    return single_response("capacity_plans", plan)


@bp.post("/capacity-plans/<plan_id>/activate")
def activate_capacity_plan(plan_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    plan = get_capacity_plan(plan_id)
    region_id = plan["region_id"]
    if plan.get("status") != "UNDER_REVIEW":
        raise_error(ERR_CAPACITY_PLAN_NOT_ACTIVATABLE)
    posture = region_view(get_region(region_id))["posture"]
    if posture not in ("OPEN", "RESTRICTED"):
        raise_error(ERR_REGION_POSTURE_FROZEN)
    plan["status"] = "ACTIVE"
    refresh_capacity_plan(plan)
    touch(plan)
    recompute_region_aggregates(region_id, bump_version=True)
    run_posture_ladder(region_id)
    return single_response("capacity_plans", plan)


@bp.post("/capacity-plans/<plan_id>/adjust")
def adjust_capacity_plan(plan_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    plan = get_capacity_plan(plan_id)
    region_id = plan["region_id"]
    if plan.get("status") != "ACTIVE":
        raise_error(ERR_INVALID_STATE)
    enforce_posture_gate(region_id)
    body = payload()
    budgeted = require_field(body, "budgeted_slots")
    committed = len(committed_appointments_for(
        plan["department_id"], plan.get("period")))
    if float(budgeted) < float(committed):
        raise_error(ERR_INVALID_STATE)
    plan["budgeted_slots"] = budgeted
    plan["status"] = "ADJUSTED"
    refresh_capacity_plan(plan)
    touch(plan)
    recompute_region_aggregates(region_id, bump_version=True)
    run_posture_ladder(region_id)
    return single_response("capacity_plans", plan)