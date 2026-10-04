from flask import Blueprint

import auth
import constants as C
import db
import domain
import util
from errors import ApiError
from serializers import serialize

bp = Blueprint("organizations", __name__)


@bp.route("/organizations", methods=["POST"])
def create_organization():
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    body = util.body_json()
    legal_name = body.get("legal_name")
    ein = body.get("ein")
    org_type = body.get("org_type")
    if not util.is_str(legal_name) or not legal_name.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "legal_name is required")
    if not util.is_str(ein) or not ein.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "ein is required")
    if org_type not in C.ORG_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "org_type is invalid")
    org = db.new_entity(
        {
            "id": util.new_id(),
            "legal_name": legal_name,
            "ein": ein,
            "org_type": org_type,
            "status": "ACTIVE",
        }
    )
    db.store.organizations[org["id"]] = org
    return util.ok(serialize(org), 201)


@bp.route("/organizations/<orgId>", methods=["GET"])
def get_organization(orgId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer", "ComplianceOfficer", "GranteeStaff"])
    # Org-scoped ownership is path-based here: GranteeStaff may read only itself.
    if role == "GranteeStaff" and uid != orgId:
        raise ApiError(
            "ERR_UNAUTHORIZED", 403, "Resource belongs to a different organization"
        )
    org = db.store.organizations.get(orgId)
    if org is None:
        raise ApiError("ERR_ORGANIZATION_NOT_FOUND", 404, "Organization not found")
    return util.ok(serialize(org), 200)


@bp.route("/organizations/<orgId>/debar", methods=["POST"])
def debar_organization(orgId):
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    org = db.store.organizations.get(orgId)
    if org is None:
        raise ApiError("ERR_ORGANIZATION_NOT_FOUND", 404, "Organization not found")
    if org["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Organization is not ACTIVE")
    org["status"] = "DEBARRED"
    domain.touch(org)
    return util.ok(serialize(org), 200)
