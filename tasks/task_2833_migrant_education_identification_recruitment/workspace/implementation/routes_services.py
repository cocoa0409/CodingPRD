"""Service plans, hour allocation, the delivery ledger and the logical clock."""

from decimal import Decimal

from flask import Blueprint

import calc
import flows
from auth import read_only, require
from errors import ApiError
from envelope import success, success_list
from store import bump, mark_fresh, store
from support import fetch, matches, paginate
from validation import (get_date, get_decimal, get_enum, get_id, get_instant,
                        get_int, iso_date, pagination_params, query_bool,
                        query_enum, query_string, read_body, round_half_up)

bp = Blueprint("services", __name__)

ZERO = Decimal("0.00")
QUARTER = Decimal("0.25")

PLAN_TYPES = ("SUPPLEMENTAL_INSTRUCTION", "SUMMER_PROGRAM", "CREDIT_ACCRUAL", "OSY_ALTERNATIVE")
DELIVERY_MODES = ("IN_PERSON", "VIRTUAL", "HOME_BASED", "WORKSITE")
PLAN_STATUSES = ("DRAFT", "ACTIVE", "SUPERSEDED", "CLOSED")
PRIORITY_TIERS = ("PFS", "NON_PFS")
COORDINATOR_CLOSURE_REASONS = ("COMPLETED", "COORDINATOR_CLOSED")
SERVICE_CATEGORIES = ("INSTRUCTION", "COUNSELING", "CREDIT_ACCRUAL_SESSION", "SUPPORT_SERVICE")


def _off_grid(value, maximum, allow_zero):
    if value < ZERO:
        return True
    if not allow_zero and value <= ZERO:
        return True
    if value > maximum:
        return True
    return (value % QUARTER) != ZERO


# =========================================================================
# service plans
# =========================================================================

@bp.route("/mep/service-plans", methods=["POST"])
@require("ServiceCoordinator")
def create_plan():
    body = read_body()
    student_id = get_id(body, "student_id", required=True)
    plan_type = get_enum(body, "plan_type", PLAN_TYPES, required=True)
    delivery_mode = get_enum(body, "delivery_mode", DELIVERY_MODES, required=True)
    expected_student_version = get_int(body, "expected_student_version", required=True)

    student = fetch("student", student_id)

    # rung 7
    if expected_student_version != student["version"]:
        raise ApiError(
            "ERR_STALE_STUDENT_VERSION",
            "Student version is %s, not the expected %s"
            % (student["version"], expected_student_version),
        )

    # rungs 25 and 26
    if plan_type == "OSY_ALTERNATIVE" and student["schooling_status"] != "OUT_OF_SCHOOL":
        raise ApiError(
            "ERR_OSY_PLAN_REQUIRES_OUT_OF_SCHOOL",
            "An OSY_ALTERNATIVE plan requires an OUT_OF_SCHOOL student",
        )
    if plan_type == "SUPPLEMENTAL_INSTRUCTION" and student["schooling_status"] != "ENROLLED":
        raise ApiError(
            "ERR_SUPPLEMENTAL_REQUIRES_ENROLLED",
            "A SUPPLEMENTAL_INSTRUCTION plan requires an ENROLLED student",
        )

    created = store.now_iso()
    plan = {
        "id": store.new_id(),
        "student_id": student_id,
        "plan_type": plan_type,
        "delivery_mode": delivery_mode,
        "status": "DRAFT",
        "priority_tier": "NON_PFS",
        "allocated_hours": ZERO,
        "expected_service_hours": ZERO,
        "delivered_hours": ZERO,
        "closure_reason": None,
        "superseded_by_plan_id": None,
        "created_at": created,
        "updated_at": created,
        "version": 1,
    }
    store.plans[plan["id"]] = plan
    mark_fresh(plan)

    flows.supersede_same_type(student_id, plan_type, plan["id"])
    bump(student)
    flows.rederive_service_status(student)
    flows.run_allocation(student)
    return success(plan, 201)


@bp.route("/mep/service-plans/<plan_id>", methods=["GET"])
@read_only
def read_plan(plan_id):
    return success(fetch("plan", plan_id))


@bp.route("/mep/service-plans", methods=["GET"])
@read_only
def list_plans():
    limit, offset = pagination_params()
    filters = {
        "student_id": query_string("student_id"),
        "status": query_enum("status", PLAN_STATUSES),
        "plan_type": query_enum("plan_type", PLAN_TYPES),
        "superseded_by_plan_id": query_string("superseded_by_plan_id"),
        "priority_tier": query_enum("priority_tier", PRIORITY_TIERS),
    }
    rows = [row for row in store.plans.values() if matches(row, filters)]
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/mep/service-plans/<plan_id>/activate", methods=["POST"])
@require("ServiceCoordinator")
def activate_plan(plan_id):
    plan = fetch("plan", plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError(
            "ERR_PLAN_INVALID_STATE",
            "Plan is %s, not DRAFT" % plan["status"],
        )
    student = store.students.get(plan["student_id"])
    if student is None or student["eligibility_status"] not in ("ELIGIBLE", "CONTINUATION"):
        raise ApiError(
            "ERR_STUDENT_NOT_ELIGIBLE_FOR_SERVICES",
            "The child's eligibility_status must be ELIGIBLE or CONTINUATION",
        )

    plan["status"] = "ACTIVE"
    bump(plan)
    flows.run_allocation(student)
    if flows.rederive_service_status(student):
        bump(student)
    return success(plan)


@bp.route("/mep/service-plans/<plan_id>/close", methods=["POST"])
@require("ServiceCoordinator")
def close_plan(plan_id):
    plan = fetch("plan", plan_id)
    body = read_body()
    reason = get_enum(body, "closure_reason", COORDINATOR_CLOSURE_REASONS, required=True)

    if plan["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(
            "ERR_PLAN_INVALID_STATE",
            "Plan is %s and cannot be closed" % plan["status"],
        )

    plan["status"] = "CLOSED"
    plan["closure_reason"] = reason
    bump(plan)

    student = store.students.get(plan["student_id"])
    if student is not None:
        flows.run_allocation(student)
        if flows.rederive_service_status(student):
            bump(student)
    return success(plan)


# =========================================================================
# delivered sessions (immutable)
# =========================================================================

@bp.route("/mep/service-deliveries", methods=["POST"])
@require("ServiceCoordinator")
def create_delivery():
    body = read_body()
    plan_id = get_id(body, "plan_id", required=True)
    delivered_on = get_date(body, "delivered_on", required=True)
    hours = get_decimal(body, "hours", required=True)
    category = get_enum(body, "service_category", SERVICE_CATEGORIES, required=True)
    credits = get_decimal(body, "credits_awarded", default=ZERO)

    plan = fetch("plan", plan_id)

    if plan["status"] != "ACTIVE":
        raise ApiError(
            "ERR_PLAN_INVALID_STATE",
            "Sessions may only be posted against an ACTIVE plan; this one is %s"
            % plan["status"],
        )

    # rung 16
    if credits > ZERO and plan["plan_type"] != "CREDIT_ACCRUAL":
        raise ApiError(
            "ERR_CREDITS_NOT_ALLOWED_FOR_PLAN_TYPE",
            "Credits may only be awarded on a CREDIT_ACCRUAL plan",
        )

    # rung 17
    if delivered_on > store.clock_date():
        raise ApiError(
            "ERR_MOVE_DATE_IN_FUTURE",
            "'delivered_on' is later than the current logical clock date",
        )

    # rung 27
    if _off_grid(hours, Decimal("8.00"), allow_zero=False):
        raise ApiError(
            "ERR_INVALID_SERVICE_HOURS",
            "'hours' must be greater than 0.00, at most 8.00 and a multiple of 0.25",
        )
    if _off_grid(credits, Decimal("2.00"), allow_zero=True):
        raise ApiError(
            "ERR_INVALID_SERVICE_HOURS",
            "'credits_awarded' must be at most 2.00 and a multiple of 0.25",
        )

    created = store.now_iso()
    row = {
        "id": store.new_id(),
        "plan_id": plan_id,
        "delivered_on": iso_date(delivered_on),
        "hours": round_half_up(hours),
        "service_category": category,
        "credits_awarded": round_half_up(credits),
        "reverses_delivery_id": None,
        "is_reversed": False,
        "created_at": created,
    }
    store.deliveries[row["id"]] = row

    student = store.students.get(plan["student_id"])
    if student is not None:
        flows.republish_plan_and_student_ledger(plan, student)
    else:
        plan["delivered_hours"] = calc.plan_delivered_hours(plan["id"])
        bump(plan)
    return success(row, 201)


@bp.route("/mep/service-deliveries/<delivery_id>", methods=["GET"])
@read_only
def read_delivery(delivery_id):
    return success(fetch("delivery", delivery_id))


@bp.route("/mep/service-deliveries", methods=["GET"])
@read_only
def list_deliveries():
    limit, offset = pagination_params()
    filters = {
        "plan_id": query_string("plan_id"),
        "reverses_delivery_id": query_string("reverses_delivery_id"),
        "service_category": query_enum("service_category", SERVICE_CATEGORIES),
        "is_reversed": query_bool("is_reversed"),
    }
    rows = [row for row in store.deliveries.values() if matches(row, filters)]
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/mep/service-deliveries/<delivery_id>/reverse", methods=["POST"])
@require("ServiceCoordinator")
def reverse_delivery(delivery_id):
    target = fetch("delivery", delivery_id)

    if target.get("reverses_delivery_id") is not None or target.get("is_reversed"):
        raise ApiError(
            "ERR_DELIVERY_NOT_REVERSIBLE",
            "Only an unreversed forward delivery record can be reversed",
        )

    created = store.now_iso()
    row = {
        "id": store.new_id(),
        "plan_id": target["plan_id"],
        "delivered_on": target["delivered_on"],
        "hours": target["hours"],
        "service_category": target["service_category"],
        "credits_awarded": target["credits_awarded"],
        "reverses_delivery_id": target["id"],
        "is_reversed": False,
        "created_at": created,
    }
    store.deliveries[row["id"]] = row
    target["is_reversed"] = True

    plan = store.plans.get(target["plan_id"])
    if plan is not None:
        student = store.students.get(plan["student_id"])
        if student is not None:
            flows.republish_plan_and_student_ledger(plan, student)
        else:
            plan["delivered_hours"] = calc.plan_delivered_hours(plan["id"])
            bump(plan)
    return success(row, 201)


# =========================================================================
# the logical program clock
# =========================================================================

@bp.route("/mep/_clock/set_current_utc", methods=["POST"])
@require("StateProgramAdmin")
def set_clock():
    body = read_body()
    moment = get_instant(body, "to_iso8601", required=True)
    store.clock = moment
    return success({"current_utc": store.clock_instant()})
