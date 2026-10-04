"""Employee endpoints."""
from flask import Blueprint, request

import db
import errors as E
from middleware import require_role
from response import success_object
from serializers import employee, policy as policy_ser
from util import get_body, get_or_404, list_response, parse_iso

bp = Blueprint("employees", __name__)

STORE = db.STORES["employees"]


@bp.route("/employees", methods=["POST"])
def create(role, user_id):
    require_role(role, {"CarrierAdmin", "GroupAdmin"})
    body = get_body(["employer_group_id", "employee_ref", "full_name", "hire_date"])
    group = db.STORES["employer_groups"].get(body["employer_group_id"])
    if group is None:
        raise E.err(E.ERR_REFERENTIAL_INTEGRITY, "employer_group_id does not exist")
    hd = parse_iso(body["hire_date"], "hire_date")
    for e in STORE.values():
        if e["employer_group_id"] == body["employer_group_id"] and e["employee_ref"] == body["employee_ref"]:
            raise E.err(E.ERR_INVALID_REQUEST, "employee_ref must be unique within the employer group")
    rec = db.stamp_created({
        "employer_group_id": body["employer_group_id"],
        "employee_ref": body["employee_ref"],
        "full_name": body["full_name"],
        "hire_date": db.format_ts(hd),
        "preexisting_diagnosis_codes": body.get("preexisting_diagnosis_codes") or [],
        "status": "ACTIVE",
    })
    STORE[rec["id"]] = rec
    return success_object(employee(rec), status=201)


@bp.route("/employees/<rid>", methods=["GET"])
def get_one(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "GroupAdmin", "BenefitCounselor"})
    rec = get_or_404(STORE, rid)
    return success_object(employee(rec))


@bp.route("/employees/<rid>/terminate", methods=["POST"])
def terminate(role, user_id, rid):
    require_role(role, {"GroupAdmin"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "ACTIVE":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot terminate from {rec['status']}")
    rec["status"] = "TERMINATED"
    db.touch(rec)
    return success_object(employee(rec))


@bp.route("/employees/<rid>/reinstate", methods=["POST"])
def reinstate(role, user_id, rid):
    require_role(role, {"GroupAdmin"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "TERMINATED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot reinstate from {rec['status']}")
    group = db.STORES["employer_groups"][rec["employer_group_id"]]
    if group["status"] not in ("ACTIVE", "SUSPENDED"):
        raise E.err(E.ERR_GROUP_TERMINATED, "Employer group is TERMINATED")
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return success_object(employee(rec))


@bp.route("/employees/<rid>/policies", methods=["GET"])
def list_policies(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "GroupAdmin", "BenefitCounselor", "ClaimsAdjuster", "PolicyholderServices"})
    get_or_404(STORE, rid)
    filters = {
        "employee_id": rid,
        "status": request.args.get("status"),
    }
    return list_response(db.STORES["policies"], filters, policy_ser)
