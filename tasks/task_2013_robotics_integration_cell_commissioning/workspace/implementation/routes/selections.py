"""RobotSelection endpoints (PRD §3.4)."""
from decimal import Decimal

from flask import Blueprint, request

from db import children, store
from errors import (ApiError, ERR_BRAND_OUT_OF_SCOPE, ERR_PAYLOAD_CHECK_FAILED,
                    invalid_state, not_found)
from middleware import authenticate
from middleware import ROLE_FINANCE_ADMIN as FA
from middleware import ROLE_PROJECT_ENGINEER as PE
from middleware import ROLE_SAFETY_LEAD as SL
from middleware import ROLE_SITE_SUPERVISOR as SS
from response import success, success_list
from services import calculations as calc
from services.domain import common_fields, org_of_project, pub, pubs, touch
from validation import as_enum, as_num, as_str, body, paginate, pagination, req

bp = Blueprint("selections", __name__)

READ_ROLES = {FA, PE, SL, SS}
BRANDS = ("FANUC", "ABB")


def get_selection(selection_id):
    s = store.selections.get(selection_id)
    if s is None:
        raise not_found("Robot selection not found")
    return s


@bp.post("/robotics/cell-projects/<project_id>/robot-selections")
def create_selection(project_id):
    authenticate({PE})
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    b = body()
    selection = {
        **common_fields(),
        "cell_project_id": project_id,
        "robot_model": as_str(req(b, "robot_model"), "robot_model"),
        "brand": as_enum(req(b, "brand"), "brand", BRANDS),
        "rated_payload_kg": as_num(req(b, "rated_payload_kg"), "rated_payload_kg",
                                   min_v=0, min_exclusive=True),
        "end_effector_weight_kg": as_num(req(b, "end_effector_weight_kg"),
                                         "end_effector_weight_kg", min_v=0),
        "part_weight_kg": as_num(req(b, "part_weight_kg"), "part_weight_kg", min_v=0),
        "wrist_inertia_kgm2": as_num(req(b, "wrist_inertia_kgm2"), "wrist_inertia_kgm2", min_v=0),
        "wrist_inertia_limit_kgm2": as_num(req(b, "wrist_inertia_limit_kgm2"),
                                           "wrist_inertia_limit_kgm2", min_v=0,
                                           min_exclusive=True),
        "payload_margin_pct": None,
        "selection_status": "PROPOSED",
    }
    store.selections[selection["id"]] = selection
    return success(pub(selection), 201)


@bp.get("/robotics/cell-projects/<project_id>/robot-selections")
def list_selections(project_id):
    authenticate(READ_ROLES)
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    limit, offset = pagination()
    items = children("selections", "cell_project_id", project_id)
    status_filter = request.args.get("selection_status")
    if status_filter is not None:
        items = [s for s in items if s["selection_status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/robot-selections/<selection_id>")
def get_one_selection(selection_id):
    authenticate(READ_ROLES)
    return success(pub(get_selection(selection_id)))


@bp.post("/robotics/robot-selections/<selection_id>/validate")
def validate_selection(selection_id):
    authenticate({PE})
    s = get_selection(selection_id)
    if s["selection_status"] != "PROPOSED":
        raise invalid_state("Only a PROPOSED selection can be validated")
    # Pinned order: payload/inertia check (priority 8) before brand scope (9).
    margin = calc.payload_margin_pct(s["rated_payload_kg"], s["end_effector_weight_kg"],
                                     s["part_weight_kg"])
    margin_ok = margin >= calc.MIN_PAYLOAD_MARGIN_PCT
    inertia_ok = calc.d(s["wrist_inertia_kgm2"]) <= calc.d(s["wrist_inertia_limit_kgm2"])
    if not (margin_ok and inertia_ok):
        raise ApiError(ERR_PAYLOAD_CHECK_FAILED, 422,
                       "Payload margin below 20.0% or wrist inertia over limit")
    project = store.projects[s["cell_project_id"]]
    org = org_of_project(project)
    if org["brand_specialization"] != "DUAL" and s["brand"] != org["brand_specialization"]:
        raise ApiError(ERR_BRAND_OUT_OF_SCOPE, 422,
                       "Robot brand is outside the integrator's specialization")
    s["payload_margin_pct"] = float(margin)
    s["selection_status"] = "VALIDATED"
    touch(s)
    return success(pub(s))


@bp.post("/robotics/robot-selections/<selection_id>/lock")
def lock_selection(selection_id):
    authenticate({SS})
    s = get_selection(selection_id)
    if s["selection_status"] != "VALIDATED":
        raise invalid_state("Only a VALIDATED selection can be locked")
    project = store.projects[s["cell_project_id"]]
    if project["status"] != "DESIGN":
        raise invalid_state("Locking a selection requires project status DESIGN")
    s["selection_status"] = "LOCKED"
    touch(s)
    return success(pub(s))


@bp.post("/robotics/robot-selections/<selection_id>/reject")
def reject_selection(selection_id):
    authenticate({PE})
    s = get_selection(selection_id)
    if s["selection_status"] != "PROPOSED":
        raise invalid_state("Only a PROPOSED selection can be rejected")
    s["selection_status"] = "REJECTED"
    touch(s)
    return success(pub(s))
