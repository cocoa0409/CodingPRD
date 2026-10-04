"""Party organizations (PRD 3.3).

POST /party-organizations        PartyCoordinator
GET  /party-organizations/{id}   all roles
"""

from flask import Blueprint

import db
import domain
from auth import get_context, require_roles
from constants import ORG_TYPES, ROLES
from envelope import ok_object
from serializers import organization_public
from validate import get_body, req_enum, req_str

bp = Blueprint("party_orgs", __name__)


@bp.route("/party-organizations", methods=["POST"])
def create_organization():
    _user_id, role = get_context()
    require_roles(role, ("PartyCoordinator",))
    body = get_body()
    legal_name = req_str(body, "legal_name")
    org_type = req_enum(body, "org_type", ORG_TYPES)
    organization = db.add(
        "party_organizations",
        {"legal_name": legal_name, "org_type": org_type},
    )
    return ok_object(organization_public(organization), status=201)


@bp.route("/party-organizations/<organization_id>", methods=["GET"])
def get_organization(organization_id):
    _user_id, role = get_context()
    require_roles(role, ROLES)
    organization = domain.get_organization(organization_id)
    return ok_object(organization_public(organization), status=200)
