"""SettlementSignatory endpoints (PRD 3.5): sign / decline / rescind with
unanimity bubble-up and the assented counter on the case."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_PROPOSAL_STATE,
    ERR_INVALID_SIGNATORY_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_arg
from services.core import public, recompute_proposal_counts, touch
from util import CLOCK
from validate import get_body, no_unknown_fields, require_path_resource

bp = Blueprint("settlement_signatories", __name__)


@bp.get("/settlement-signatories")
def list_signatories():
    filters = {
        "settlement_proposal_id": query_arg("settlement_proposal_id"),
        "intervenor_id": query_arg("intervenor_id"),
        "status": query_arg("status"),
    }
    return list_response("settlement_signatories", filters)


@bp.get("/settlement-signatories/<signatory_id>")
def get_signatory(signatory_id):
    return get_one("settlement_signatories", signatory_id)


def _load_own_signatory(signatory_id, caller):
    sig = require_path_resource("settlement_signatories", signatory_id)
    # Ownership (p3): the row belongs to the caller's party
    if caller.user_id != sig["intervenor_id"]:
        raise_error(ERR_FORBIDDEN_OWNERSHIP,
                    "the signatory row belongs to a different party")
    return sig


@bp.post("/settlement-signatories/<signatory_id>/sign")
def sign_signatory(signatory_id):
    body = get_body()
    no_unknown_fields(body, set())
    caller = authorized(["IntervenorRep"])
    sig = _load_own_signatory(signatory_id, caller)
    if sig["status"] != "PENDING":
        raise_error(ERR_INVALID_SIGNATORY_STATE, "sign requires PENDING")
    proposal = db["settlement_proposals"].get(sig["settlement_proposal_id"])
    if proposal is None or proposal["status"] != "UNDER_NEGOTIATION":
        raise_error(ERR_INVALID_PROPOSAL_STATE,
                    "the owning proposal must be UNDER_NEGOTIATION")
    sig["status"] = "SIGNED"
    sig["signed_at"] = CLOCK.now_iso()
    touch(sig)
    recompute_proposal_counts(proposal)
    # Unanimity bubble-up (only on a sign)
    if (
        proposal["status"] == "UNDER_NEGOTIATION"
        and proposal["required_signature_count"] > 0
        and proposal["signature_count"] == proposal["required_signature_count"]
    ):
        proposal["status"] = "ASSENTED"
        touch(proposal)
        case = db["rate_cases"].get(proposal["rate_case_id"])
        if case is not None:
            case["assented_proposal_count"] += 1
            touch(case)
    return success_object(public(sig))


@bp.post("/settlement-signatories/<signatory_id>/decline")
def decline_signatory(signatory_id):
    body = get_body()
    no_unknown_fields(body, set())
    caller = authorized(["IntervenorRep"])
    sig = _load_own_signatory(signatory_id, caller)
    if sig["status"] != "PENDING":
        raise_error(ERR_INVALID_SIGNATORY_STATE, "decline requires PENDING")
    sig["status"] = "DECLINED"
    touch(sig)
    return success_object(public(sig))


@bp.post("/settlement-signatories/<signatory_id>/rescind")
def rescind_signatory(signatory_id):
    body = get_body()
    no_unknown_fields(body, set())
    caller = authorized(["IntervenorRep"])
    sig = _load_own_signatory(signatory_id, caller)
    if sig["status"] != "SIGNED":
        raise_error(ERR_INVALID_SIGNATORY_STATE, "rescind requires SIGNED")
    proposal = db["settlement_proposals"].get(sig["settlement_proposal_id"])
    if proposal is None or proposal["status"] not in ("UNDER_NEGOTIATION", "ASSENTED"):
        raise_error(ERR_INVALID_PROPOSAL_STATE,
                    "the owning proposal must be UNDER_NEGOTIATION or ASSENTED")
    sig["status"] = "RESCINDED"
    touch(sig)
    recompute_proposal_counts(proposal)
    if proposal["status"] == "ASSENTED":
        proposal["status"] = "UNDER_NEGOTIATION"
        touch(proposal)
        case = db["rate_cases"].get(proposal["rate_case_id"])
        if case is not None:
            case["assented_proposal_count"] -= 1
            touch(case)
    return success_object(public(sig))
