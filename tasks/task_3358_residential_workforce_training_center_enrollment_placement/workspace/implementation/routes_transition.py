"""Transition plans: fetch the 1:1 plan of an enrollment; record services."""
from flask import Blueprint

from auth import authenticate, require_role
from db import STORE, bump
from envelope import ok_object, ok_list
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_TRANSITION_WINDOW_EXPIRED,
)
from helpers import (
    get_body,
    check_unknown,
    as_enum,
    as_int,
    as_number,
    pagination_params,
    paginate,
)
import domain
import serializers

bp = Blueprint("transition_plans", __name__)

SERVICE_TYPES = ["JOB_PLACEMENT", "HOUSING", "TRANSPORTATION"]
OUTCOMES = ["COMPLETED", "WAIVED"]
TRACK_FIELD = {
    "JOB_PLACEMENT": "job_placement_status",
    "HOUSING": "housing_status",
    "TRANSPORTATION": "transportation_status",
}


@bp.route("/jc/enrollments/<enrollment_id>/transition-plan", methods=["GET"])
def get_enrollment_plan(enrollment_id):
    user_id, role = authenticate()
    require_role(role, {"TransitionSpecialist", "EnrollmentManager"})
    if enrollment_id not in STORE.enrollments:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Enrollment not found")
    limit, offset = pagination_params()
    items = [
        p for p in STORE.transition_plans.values() if p["enrollment_id"] == enrollment_id
    ]
    items.sort(key=lambda p: p["_seq"])
    page, meta = paginate([serializers.plan_view(p) for p in items], limit, offset)
    return ok_list(page, meta)


@bp.route("/jc/transition-plans/<plan_id>/services", methods=["POST"])
def record_service(plan_id):
    user_id, role = authenticate()
    require_role(role, {"TransitionSpecialist"})
    plan = STORE.transition_plans.get(plan_id)
    if plan is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Transition plan not found")
    body = get_body()
    check_unknown(body, {"service_type", "outcome", "starting_wage_cents", "distance_miles"})
    service_type = as_enum(body, "service_type", SERVICE_TYPES, required=True)
    outcome = as_enum(body, "outcome", OUTCOMES, required=True)
    starting_wage_cents = (
        as_int(body, "starting_wage_cents", lo=0) if "starting_wage_cents" in body else None
    )
    distance_miles = (
        as_number(body, "distance_miles", lo=0) if "distance_miles" in body else None
    )
    if service_type == "JOB_PLACEMENT" and outcome == "COMPLETED" and starting_wage_cents is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            ERR_INVALID_REQUEST[1],
            "starting_wage_cents is required when completing the job placement track",
        )
    if service_type == "TRANSPORTATION" and outcome == "COMPLETED" and distance_miles is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            ERR_INVALID_REQUEST[1],
            "distance_miles is required when completing the transportation track",
        )
    # Endpoint-specific ordering (PRD 2.7): a COMPLETED plan surfaces through
    # the generic state rule; the expired window check outranks it otherwise.
    if domain.plan_status(plan) == "COMPLETED":
        raise ApiError(
            ERR_INVALID_STATE[0],
            ERR_INVALID_STATE[1],
            "Transition plan is fully resolved",
        )
    if STORE.clock_date_str() > plan["expires_at"]:
        raise ApiError(
            ERR_TRANSITION_WINDOW_EXPIRED[0],
            ERR_TRANSITION_WINDOW_EXPIRED[1],
            "The transition service window has closed",
        )
    field = TRACK_FIELD[service_type]
    if plan[field] != "PENDING":
        raise ApiError(
            ERR_INVALID_STATE[0],
            ERR_INVALID_STATE[1],
            "Service track {} is already resolved".format(service_type),
        )
    plan[field] = outcome
    if service_type == "JOB_PLACEMENT" and outcome == "COMPLETED":
        plan["job_starting_wage_cents"] = starting_wage_cents
    if service_type == "TRANSPORTATION" and outcome == "COMPLETED":
        plan["_transport_distance"] = distance_miles
    bump(plan)
    return ok_object(serializers.plan_view(plan), status=200)
