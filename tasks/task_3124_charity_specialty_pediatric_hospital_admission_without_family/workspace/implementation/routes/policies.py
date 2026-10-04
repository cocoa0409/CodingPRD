"""InsurancePolicy endpoints (PRD §3.4)."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_POLICY_NOT_FOUND
from helpers import get_body, new_id, now_iso, req_bool, req_str
from middleware import require_auth
from response import success_list, success_object, paginate
from routes.applications import get_application_or_404
from views import policy_view

bp = Blueprint("policies", __name__)

LIST_ROLES = ["NetworkAdmin", "IntakeCoordinator", "ReviewCommitteeMember",
              "BillingSpecialist", "CareCoordinator"]


def get_policy_or_404(policy_id):
    p = db.policies.get(policy_id)
    if p is None:
        raise ApiError(ERR_POLICY_NOT_FOUND, 404, "Insurance policy id does not exist")
    return p


@bp.post("/applications/<id>/insurance-policies")
def create_policy(id):
    require_auth(["IntakeCoordinator", "BillingSpecialist"])
    a = get_application_or_404(id)
    body = get_body()
    payer_name = req_str(body, "payer_name")
    policy_number = req_str(body, "policy_number")
    coverage_exists = req_bool(body, "coverage_exists")
    now = now_iso()
    p = {
        "id": new_id(),
        "application_id": a["id"],
        "payer_name": payer_name,
        "policy_number": policy_number,
        "coverage_exists": coverage_exists,
        "status": "VERIFIED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.policies[p["id"]] = p
    return success_object(policy_view(p), 201)


@bp.get("/applications/<id>/insurance-policies")
def list_policies(id):
    require_auth(LIST_ROLES)
    a = get_application_or_404(id)
    items = [p for p in db.policies.values() if p["application_id"] == a["id"]]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([policy_view(p) for p in page], total, limit, offset)


@bp.get("/insurance-policies/<policyId>")
def get_policy(policyId):
    require_auth(LIST_ROLES)
    p = get_policy_or_404(policyId)
    return success_object(policy_view(p))
