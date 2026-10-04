"""Partner agency registration."""
from flask import Blueprint
import db
import errors
import envelope
import validation as V
import auth
import domain
from constants import PARTNER_KINDS

bp = Blueprint("partners", __name__)


@bp.post("/vdr/partners")
def create_partner():
    body = V.get_body()
    V.check_unknown(body, {"name", "kind", "contact_email"})
    name = V.req_str(body, "name")
    kind = V.req_enum(body, "kind", PARTNER_KINDS)
    contact_email = V.req_str(body, "contact_email")
    auth.require_roles("SystemAdmin")
    partner = db.mint("partners", {
        "name": name,
        "kind": kind,
        "contact_email": contact_email,
    })
    return envelope.ok(domain.public(partner), 201)
