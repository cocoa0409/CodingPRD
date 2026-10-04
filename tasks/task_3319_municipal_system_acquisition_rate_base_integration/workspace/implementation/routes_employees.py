"""EmployeeTransition endpoints: register, list, get, offer-response."""
from flask import Blueprint

import db
from calculations import severance_calc
from errors import ApiError
from middleware import (
    current_user, require_roles, require_fields, require_int, require_str,
)
from models import new_employee_transition, touch
from response import success_obj, success_list, json_body, parse_pagination, paginate
from routes_targets import get_target_or_404
from util import ALL_ROLES, OFFER_RESPONSES

bp = Blueprint("employee_transitions", __name__)

_RESPONSE_ALLOWED_TARGET_STATUSES = (
    "VALUATION", "MUNICIPAL_REVIEW", "REGULATORY_REVIEW", "CLOSING")


def get_employee_transition_or_404(emp_id):
    emp = db.employee_transitions.get(emp_id)
    if emp is None:
        raise ApiError("ERR_NOT_FOUND", 404, "EmployeeTransition not found")
    return emp


@bp.route("/acquisitions/targets/<target_id>/employee-transitions", methods=["POST"])
def create_employee_transition(target_id):
    _, role = current_user()
    require_roles(role, ["HRDirector"])
    target = get_target_or_404(target_id)
    body = json_body()
    require_fields(body, ["employee_ref", "years_of_service",
                          "weekly_salary_cents", "union_covered"])
    require_str(body, "employee_ref")
    require_int(body, "years_of_service", minimum=0)
    require_int(body, "weekly_salary_cents", gt_zero=True)
    if not isinstance(body["union_covered"], bool):
        raise ApiError("ERR_INVALID_REQUEST", 422, "union_covered must be a boolean")
    emp = new_employee_transition(target["id"], body)
    return success_obj(emp, status=201)


@bp.route("/acquisitions/targets/<target_id>/employee-transitions", methods=["GET"])
def list_employee_transitions(target_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    get_target_or_404(target_id)
    limit, offset = parse_pagination()
    records = sorted(db.employee_transitions_of_target(target_id),
                     key=lambda e: (e["created_at"], e["id"]))
    page, total = paginate(records, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/acquisitions/employee-transitions/<emp_id>", methods=["GET"])
def get_employee_transition(emp_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    return success_obj(get_employee_transition_or_404(emp_id))


@bp.route("/acquisitions/employee-transitions/<emp_id>/offer-response", methods=["POST"])
def offer_response(emp_id):
    _, role = current_user()
    require_roles(role, ["HRDirector"])
    emp = get_employee_transition_or_404(emp_id)
    target = db.targets[emp["target_id"]]
    if emp["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "EmployeeTransition is not in PENDING")
    if target["status"] not in _RESPONSE_ALLOWED_TARGET_STATUSES:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Target is not in VALUATION, MUNICIPAL_REVIEW, REGULATORY_REVIEW, or CLOSING")
    body = json_body()
    require_fields(body, ["response"])
    response = body.get("response")
    if response not in OFFER_RESPONSES:
        raise ApiError("ERR_INVALID_REQUEST", 422,
                       "response must be one of ACCEPTED, DECLINED, ASSUMED")
    # Priority 15: union rule.
    if response == "DECLINED" and emp["union_covered"]:
        raise ApiError("ERR_UNION_ASSUMPTION_REQUIRED", 409,
                       "Union-covered employee may not DECLINE")
    if response == "ASSUMED" and not emp["union_covered"]:
        raise ApiError("ERR_UNION_ASSUMPTION_REQUIRED", 409,
                       "Non-union employee may not be ASSUMED")
    if response == "DECLINED":
        weeks, cents = severance_calc(emp)
        emp["severance_weeks"] = weeks
        emp["severance_cents"] = cents
    else:
        emp["severance_weeks"] = 0
        emp["severance_cents"] = 0
    emp["status"] = response
    touch(emp)
    return success_obj(emp)
