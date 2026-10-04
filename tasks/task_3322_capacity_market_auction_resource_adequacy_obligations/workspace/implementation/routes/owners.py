"""Owners routes."""
from flask import Blueprint

from db import db
from middleware import require_roles, require_any
from response import success_object
from util import base_entity, touch, dec, require_fields, is_number, get_body, strip_internal
from errors import err_not_found, err_invalid_request, err_invalid_state

bp = Blueprint("owners", __name__)


def _serialize(o):
    return strip_internal(o)


@bp.route("/capacity-market/owners", methods=["POST"])
def create_owner():
    require_roles("MarketAdmin")
    body = get_body()
    require_fields(body, ["legal_name", "contact_email", "credit_score"])
    legal_name = body["legal_name"]
    email = body["contact_email"]
    credit = body["credit_score"]
    if not isinstance(legal_name, str) or not legal_name.strip():
        raise err_invalid_request("legal_name must be a non-empty string")
    if not isinstance(email, str) or "@" not in email:
        raise err_invalid_request("contact_email must contain '@'")
    if isinstance(credit, bool) or not isinstance(credit, int) or credit < 0 or credit > 1000:
        raise err_invalid_request("credit_score must be an integer in [0,1000]")
    # business: unique legal_name
    for o in db.owners.values():
        if o["legal_name"] == legal_name:
            raise err_invalid_request("legal_name must be unique")
    owner = base_entity()
    owner.update({
        "legal_name": legal_name,
        "contact_email": email,
        "credit_score": credit,
        "status": "ACTIVE",
    })
    db.owners[owner["id"]] = owner
    return success_object(_serialize(owner), 201)


@bp.route("/capacity-market/owners/<owner_id>", methods=["GET"])
def get_owner(owner_id):
    require_any()
    o = db.owners.get(owner_id)
    if o is None:
        raise err_not_found("owner not found")
    return success_object(_serialize(o))


@bp.route("/capacity-market/owners/<owner_id>/suspend", methods=["POST"])
def suspend_owner(owner_id):
    require_roles("MarketAdmin")
    o = db.owners.get(owner_id)
    if o is None:
        raise err_not_found("owner not found")
    if o["status"] != "ACTIVE":
        raise err_invalid_state("owner is not ACTIVE")
    o["status"] = "SUSPENDED"
    touch(o)
    return success_object(_serialize(o))
