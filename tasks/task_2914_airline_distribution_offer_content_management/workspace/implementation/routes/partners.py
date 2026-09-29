"""Distribution partner registry (PRD 3.3)."""
from flask import Blueprint

import validators as v
from auth import ALL_ROLES, ROLE_PLATFORM_ADMIN, authenticate
from envelope import respond_object
from serializers import partner_out
from store import common_fields, db, get_or_404

bp = Blueprint("partners", __name__)

PARTNER_TYPES = ("TRAVEL_AGENCY", "TECH_PROVIDER", "CORPORATE")


@bp.post("/distribution-partners")
def create_partner():
    authenticate([ROLE_PLATFORM_ADMIN])
    body = v.json_body()
    partner_name = v.req_string(body, "partner_name", 1, 120)
    partner_type = v.req_enum(body, "partner_type", PARTNER_TYPES)
    iata_code = v.req_string(body, "iata_code", 1, 16)
    home_country = v.req_country(body, "home_country")

    partner = common_fields()
    partner.update({
        "partner_name": partner_name,
        "partner_type": partner_type,
        "iata_code": iata_code,
        "home_country": home_country,
        "certification_status": "UNCERTIFIED",
    })
    db.partners[partner["id"]] = partner
    return respond_object(partner_out(partner), 201)


@bp.get("/distribution-partners/<partner_id>")
def read_partner(partner_id):
    authenticate(ALL_ROLES)
    partner = get_or_404(db.partners, partner_id, "ERR_PARTNER_NOT_FOUND")
    return respond_object(partner_out(partner))
