"""AcquisitionTarget endpoints: create, get, list, close."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import (
    current_user, require_roles, require_fields, require_int, require_enum,
    require_str,
)
from models import new_target, touch
from response import success_obj, success_list, json_body, parse_pagination, paginate
from util import ALL_ROLES, SYSTEM_TYPES, VALUATION_METHODS

bp = Blueprint("targets", __name__)


def get_target_or_404(target_id):
    target = db.targets.get(target_id)
    if target is None:
        raise ApiError("ERR_NOT_FOUND", 404, "AcquisitionTarget not found")
    return target


@bp.route("/acquisitions/targets", methods=["POST"])
def create_target():
    _, role = current_user()
    require_roles(role, ["AcquisitionAnalyst"])
    body = json_body()
    require_fields(body, ["system_name", "municipality_name", "state_code",
                          "system_type", "customer_count", "permitted_valuation_methods"])
    require_str(body, "system_name")
    require_str(body, "municipality_name")
    require_str(body, "state_code")
    require_enum(body, "system_type", SYSTEM_TYPES)
    require_int(body, "customer_count", gt_zero=True)
    methods = body.get("permitted_valuation_methods")
    if (not isinstance(methods, list) or len(methods) == 0
            or any(m not in VALUATION_METHODS for m in methods)):
        raise ApiError("ERR_INVALID_REQUEST", 422,
                       "permitted_valuation_methods must be a non-empty subset of the declared methods")
    target = new_target(body)
    return success_obj(target, status=201)


@bp.route("/acquisitions/targets/<target_id>", methods=["GET"])
def get_target(target_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    return success_obj(get_target_or_404(target_id))


@bp.route("/acquisitions/targets", methods=["GET"])
def list_targets():
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(db.targets.values())
    status = request.args.get("status")
    state_code = request.args.get("state_code")
    if status is not None:
        records = [t for t in records if t["status"] == status]
    if state_code is not None:
        records = [t for t in records if t["state_code"] == state_code]
    records.sort(key=lambda t: (t["created_at"], t["id"]))
    page, total = paginate(records, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/acquisitions/targets/<target_id>/close", methods=["POST"])
def close_target(target_id):
    _, role = current_user()
    require_roles(role, ["TransitionManager"])
    target = get_target_or_404(target_id)
    if target["status"] != "CLOSING":
        raise ApiError("ERR_INVALID_STATE", 409, "Target is not in CLOSING")
    # Priority 12 prerequisite gates, in scaffold-listed order.
    items = db.transition_items_of_target(target_id)
    if any(i["status"] != "DONE" for i in items):
        raise ApiError("ERR_TRANSITION_INCOMPLETE", 409, "Not all transition items are DONE")
    if any(a["status"] == "LEGACY" for a in db.customer_accounts_of_target(target_id)):
        raise ApiError("ERR_ACCOUNTS_PENDING", 409, "LEGACY customer accounts remain")
    if any(e["status"] == "PENDING" for e in db.employee_transitions_of_target(target_id)):
        raise ApiError("ERR_EMPLOYEES_PENDING", 409, "PENDING employee transitions remain")
    target["status"] = "INTEGRATED"
    touch(target)
    return success_obj(target)
