"""ApprovalPolicy endpoints."""

from flask import Blueprint, request

import db
from errors import raise_err, ERR_POLICY_NOT_FOUND
from middleware import (
    get_actor, require_role, get_json_body, validate_fields, req_enum, req_int,
    get_pagination, paginate,
)
from response import success
from services import calc

bp = Blueprint("policies", __name__)

SEVERITIES = ["BELOW_MIN", "ABOVE_BAND", "EXCEPTION"]
POLICY_ROLES = ["CompAnalyst", "DepartmentDirector", "VPPeople"]
READ_ROLES = ["HRAdmin", "CompAnalyst", "VPPeople", "DepartmentDirector",
              "Recruiter", "HiringManager"]


@bp.route("/api/approval-policies", methods=["POST"])
def create():
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body, ["min_band_severity", "required_role", "chain_position"], [])
    sev = req_enum(body, "min_band_severity", SEVERITIES)
    req_role = req_enum(body, "required_role", POLICY_ROLES)
    pos = req_int(body, "chain_position", min_value=1)
    require_role(role, ["HRAdmin"])
    ts = db.now_ms()
    pol = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "min_band_severity": sev,
        "required_role": req_role,
        "chain_position": pos,
        "status": "ACTIVE",
    }
    db.policies[pol["id"]] = pol
    return success(pol, status=201)


@bp.route("/api/approval-policies", methods=["GET"])
def list_all():
    uid, role = get_actor()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    status_f = request.args.get("status")
    items = sorted(db.policies.values(), key=lambda p: p["created_at"])
    if status_f is not None:
        items = [p for p in items if p["status"] == status_f]
    page, pg = paginate(items, limit, offset)
    return success(list(page), response_type="array", pagination=pg)


@bp.route("/api/approval-policies/<pol_id>/deactivate", methods=["POST"])
def deactivate(pol_id):
    uid, role = get_actor()
    if db.request_has_body():
        get_json_body()
    require_role(role, ["HRAdmin"])
    pol = db.policies.get(pol_id)
    if pol is None:
        raise_err(ERR_POLICY_NOT_FOUND, "Approval policy not found")
    pol["status"] = "INACTIVE"
    calc.touch(pol)
    return success(pol)
