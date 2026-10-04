"""Supplier registration (PRD 3.1)."""
from flask import Blueprint

from helpers import (CERTIFICATIONS, F, new_entity, pub, require_roles,
                     respond, validate_body)
from state import DB

bp = Blueprint("suppliers", __name__)


@bp.post("/spice/suppliers")
@require_roles("SupplyPlanner")
def create_supplier():
    data = validate_body({
        "name": F("str", required=True),
        "origin_country": F("str", required=True),
        "certifications": F("list", item_enum=CERTIFICATIONS, default=list),
        "knowledge_tier": F("enum", enum=["MASKED_ONLY", "FULL"], default="MASKED_ONLY"),
    })
    supplier = new_entity(data)
    DB.suppliers[supplier["id"]] = supplier
    return respond(pub(supplier), 201)
