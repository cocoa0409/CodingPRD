"""Organization endpoints and the organization-scoped solicitation listing."""
from flask import Blueprint

import serializers
import store
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ORG_NOT_FOUND,
    ERR_UNAUTHORIZED,
)
from respond import ok, ok_list
from validators import (
    get_body,
    paginate,
    req_enum,
    req_str,
    require_auth,
    require_role,
)

bp = Blueprint("organizations", __name__)

ORG_TYPES = ("ISSUER", "OBLIGATED_PERSON", "BROKER_DEALER", "MUNICIPAL_ADVISOR")

ORG_READ_ROLES = ("PortalOperator", "ComplianceOfficer", "ExamAdmin", "LicensingOfficer")


@bp.route("/msrb/organizations", methods=["POST"])
def create_organization():
    _uid, role = require_auth()
    require_role(role, ("PortalOperator",))
    body = get_body()
    org_code = req_str(body, "org_code")
    name = req_str(body, "name")
    org_type = req_enum(body, "org_type", ORG_TYPES)
    for existing in store.organizations.values():
        if existing["org_code"] == org_code:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "org_code must be unique across all organizations.",
                400,
            )
    now = store.now()
    org = {
        "id": store.new_id(),
        "org_code": org_code,
        "name": name,
        "org_type": org_type,
        "status": "ACTIVE",
        "suspended_reason": None,
        "late_report_count": 0,
        "compliance_posture": "CLEAR",
        "published_par_total": 0,
        "active_professional_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.organizations[org["id"]] = org
    return ok(serializers.organization(org), 201)


@bp.route("/msrb/organizations/<org_id>", methods=["GET"])
def get_organization(org_id):
    _uid, role = require_auth()
    require_role(role, ORG_READ_ROLES)
    org = store.organizations.get(org_id)
    if org is None:
        raise ApiError(ERR_ORG_NOT_FOUND, "Organization not found.", 404)
    return ok(serializers.organization(org), 200)


@bp.route("/msrb/organizations/<org_id>/suspend", methods=["POST"])
def suspend_organization(org_id):
    _uid, role = require_auth()
    require_role(role, ("ComplianceOfficer",))
    body = get_body()
    reason = req_str(body, "reason")
    org = store.organizations.get(org_id)
    if org is None:
        raise ApiError(ERR_ORG_NOT_FOUND, "Organization not found.", 404)
    if org["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Organization is already SUSPENDED.", 409)
    org["status"] = "SUSPENDED"
    org["suspended_reason"] = reason
    org["version"] += 1
    org["updated_at"] = store.now()
    return ok(serializers.organization(org), 200)


@bp.route("/msrb/organizations/<org_id>/solicitation-records", methods=["GET"])
def list_org_solicitation_records(org_id):
    uid, role = require_auth()
    require_role(role, ("ComplianceOfficer", "PortalOperator", "DealerRep"))
    # Ownership: a DealerRep may list only its own organization's records.
    if role == "DealerRep" and uid != org_id:
        raise ApiError(
            ERR_UNAUTHORIZED,
            "DealerRep may list only its own organization's solicitation records.",
            403,
        )
    org = store.organizations.get(org_id)
    if org is None:
        raise ApiError(ERR_ORG_NOT_FOUND, "Organization not found.", 404)
    items = [
        s for s in store.solicitation_records.values() if s["advisor_org_id"] == org_id
    ]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items)
    return ok_list(
        [serializers.solicitation_record(s) for s in page], limit, offset, total
    )
