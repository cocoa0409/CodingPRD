"""PrivateLabelAgreement routes (PRD 3.8)."""
from flask import Blueprint

from helpers import (D, F, new_entity, not_found, pub, require_roles, respond,
                     validate_body, validation_error)
from state import DB

bp = Blueprint("agreements", __name__)


@bp.post("/spice/agreements")
@require_roles("ProductionScheduler")
def create_agreement():
    data = validate_body({
        "retailer_name": F("str", required=True),
        "product_codes": F("list", item="str", required=True),
        "confidentiality_level": F("enum", enum=["STANDARD", "HIGH_SEGREGATION"],
                                   default="STANDARD"),
        "annual_commitment_kg": F("num", required=True),
        "development_nda_signed": F("bool", default=False),
    })
    if len(data["product_codes"]) == 0:
        validation_error("product_codes must be a non-empty array")
    if data["annual_commitment_kg"] <= 0:
        validation_error("annual_commitment_kg must be > 0")
    agreement = new_entity({
        "retailer_name": data["retailer_name"],
        "product_codes": data["product_codes"],
        "confidentiality_level": data["confidentiality_level"],
        "annual_commitment_kg": data["annual_commitment_kg"],
        "development_nda_signed": data["development_nda_signed"],
        "produced_ytd_kg": D(0),
        "commitment_met": False,
    })
    DB.agreements[agreement["id"]] = agreement
    return respond(pub(agreement), 201)


@bp.get("/spice/agreements/<agreement_id>")
@require_roles("ProductionScheduler", "SupplyPlanner")
def get_agreement(agreement_id):
    agreement = DB.agreements.get(agreement_id)
    if agreement is None:
        not_found("agreement not found")
    return respond(pub(agreement))
