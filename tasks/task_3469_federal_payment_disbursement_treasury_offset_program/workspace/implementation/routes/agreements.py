"""ReciprocalAgreement endpoints (PRD §2.10, §3.8)."""
from flask import Blueprint

from constants import DIRECTIONS, ROLE_TREASURY_SUPERVISOR
from db import STORE, new_entity, touch
from errors import (
    err_agreement_overlap,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
)
from middleware import authenticate, get_body, require_roles, spec_field, validate_body
from response import ok
from serializers import serialize_agreement
from services.matching import has_active_agreement_overlap
from util import gen_id

bp = Blueprint("agreements", __name__)


@bp.post("/reciprocal-agreements")
def create_agreement():
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_SUPERVISOR)
    data = validate_body(get_body(), [
        spec_field("state_code", "str", required=True),
        spec_field("direction", "enum", required=True, enum=DIRECTIONS),
        spec_field("effective_from", "dt", required=True),
        spec_field("effective_until", "dt", required=True),
    ])
    # Half-open window: effective_until must be strictly after effective_from.
    if data["effective_until"] <= data["effective_from"]:
        raise err_invalid_request("effective_until must be strictly after effective_from")
    # Overlap with an ACTIVE agreement of the same state and a conflicting
    # direction scope is rejected at creation.
    if has_active_agreement_overlap(
        data["state_code"], data["direction"], data["effective_from"], data["effective_until"]
    ):
        raise err_agreement_overlap()

    ent = new_entity()
    ent["id"] = gen_id()
    ent.update({
        "state_code": data["state_code"],
        "direction": data["direction"],
        "effective_from": data["effective_from"],
        "effective_until": data["effective_until"],
        "status": "DRAFT",
    })
    STORE["agreements"][ent["id"]] = ent
    return ok(serialize_agreement(ent), 201)


@bp.post("/reciprocal-agreements/<string:reciprocalAgreementId>/activate")
def activate_agreement(reciprocalAgreementId):
    """DRAFT -> ACTIVE; the overlap rule is re-checked so a stale draft cannot
    slip into conflict. ACTIVE is absorbing — there is no terminate."""
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_SUPERVISOR)
    validate_body(get_body(), [])
    agreement = STORE["agreements"].get(reciprocalAgreementId)
    if agreement is None:
        raise err_not_found("Reciprocal agreement not found")
    if agreement["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT agreement can be activated")
    if has_active_agreement_overlap(
        agreement["state_code"],
        agreement["direction"],
        agreement["effective_from"],
        agreement["effective_until"],
        exclude_id=agreement["id"],
    ):
        raise err_agreement_overlap()
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return ok(serialize_agreement(agreement))
