"""CreditorAgency endpoints (PRD §3.1, §2.9)."""
from flask import Blueprint

from constants import CREDITOR_TYPES, ROLE_TREASURY_SUPERVISOR
from db import STORE, new_entity
from errors import (
    err_duplicate_creditor_code,
    err_invalid_request,
    err_not_found,
    err_state_code_required,
)
from middleware import authenticate, get_body, require_roles, spec_field, validate_body
from response import ok
from serializers import serialize_creditor
from util import gen_id

bp = Blueprint("creditors", __name__)


@bp.post("/creditor-agencies")
def create_creditor():
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_SUPERVISOR)
    data = validate_body(get_body(), [
        spec_field("creditor_code", "str", required=True),
        spec_field("legal_name", "str", required=True),
        spec_field("creditor_type", "enum", required=True, enum=CREDITOR_TYPES),
        spec_field("state_code", "str", required=False),
    ])
    # Conditional state_code rule (PRD §3.1): STATE requires it, FEDERAL
    # forbids it entirely.
    if data["creditor_type"] == "STATE" and data["state_code"] is None:
        raise err_state_code_required()
    if data["creditor_type"] == "FEDERAL" and data["state_code"] is not None:
        raise err_invalid_request("state_code must be absent when creditor_type is FEDERAL")
    for existing in STORE["creditors"].values():
        if existing["creditor_code"] == data["creditor_code"]:
            raise err_duplicate_creditor_code()

    ent = new_entity()
    ent["id"] = gen_id()
    ent.update({
        "creditor_code": data["creditor_code"],
        "legal_name": data["legal_name"],
        "creditor_type": data["creditor_type"],
        "state_code": data["state_code"] if data["creditor_type"] == "STATE" else None,
        # Ledger initialized exactly per §2.9.
        "remitted_gross_ytd_cents": 0,
        "remitted_ytd_year": None,
        "remitted_net_total_cents": 0,
    })
    STORE["creditors"][ent["id"]] = ent
    return ok(serialize_creditor(ent), 201)


@bp.get("/creditor-agencies/<string:creditorAgencyId>")
def get_creditor(creditorAgencyId):
    authenticate()  # all declared roles may read (PRD §4)
    creditor = STORE["creditors"].get(creditorAgencyId)
    if creditor is None:
        raise err_not_found("Creditor agency not found")
    return ok(serialize_creditor(creditor))
