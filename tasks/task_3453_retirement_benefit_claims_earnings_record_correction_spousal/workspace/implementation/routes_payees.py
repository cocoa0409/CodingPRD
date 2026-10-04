"""Representative-payee determinations (PRD §3.9): a ClaimsSpecialist opens a
case on an ENTITLED claim; a SeniorAdjudicator decides it, never the
creator; approval requires the claim still ENTITLED and capacity-1 ACTIVE
exclusivity; an ACTIVE case routes future payments to the payee.
"""

from flask import Blueprint

import validation as v
from db import store, stamp_common_new, touch
from envelope import ok
from errors import (
    ApiError,
    ERR_ACTIVE_PAYEE_EXISTS,
    ERR_CLAIM_ALREADY_TERMINAL,
    ERR_CLAIM_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PAYEE_CASE_NOT_FOUND,
    ERR_SAME_ADJUDICATOR,
)
from security import (
    ROLE_CLAIMS_SPECIALIST,
    ROLE_SENIOR_ADJUDICATOR,
    authenticate,
    require_role,
)
from serializers import payee_dict

bp = Blueprint("payees", __name__)


def load_payee(case_id):
    p = store.payees.get(case_id)
    if p is None:
        raise ApiError(ERR_PAYEE_CASE_NOT_FOUND, f"No payee case with id {case_id}.")
    return p


@bp.route("/ssa/payee-cases", methods=["POST"])
def create_payee_case():
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST})
    body = v.get_body()
    claim_id = v.req_str(body, "claim_id")
    payee_name = v.req_str(body, "payee_name")
    basis = v.req_str(body, "determination_basis")
    claim = store.claims.get(claim_id)
    if claim is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, f"No claim with id {claim_id}.")
    if claim["status"] in ("WITHDRAWN", "TERMINATED"):
        raise ApiError(ERR_CLAIM_ALREADY_TERMINAL, "The claim is WITHDRAWN or TERMINATED.")
    if claim["status"] != "ENTITLED":
        raise ApiError(
            ERR_INVALID_STATE, "A payee determination may only open on an ENTITLED claim."
        )
    case = stamp_common_new(
        {
            "claim_id": claim_id,
            "payee_name": payee_name,
            "determination_basis": basis,
            "status": "INVESTIGATING",
            "created_by": ctx["user_id"],
            "decided_by": None,
        }
    )
    store.payees[case["id"]] = case
    return ok(payee_dict(case), 201)


@bp.route("/ssa/payee-cases/<case_id>/decide", methods=["POST"])
def decide_payee_case(case_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_SENIOR_ADJUDICATOR})
    # Layer 4 — body well-formedness precedes path resolution (PRD §2.9).
    body = v.get_body()
    outcome = v.req_enum(body, "outcome", {"APPROVED", "DENIED"})
    case = load_payee(case_id)
    if case["status"] != "INVESTIGATING":
        raise ApiError(ERR_INVALID_STATE, "Only an INVESTIGATING case can be decided.")
    claim = store.claims.get(case["claim_id"])
    if outcome == "APPROVED":
        if claim is not None and claim["status"] in ("WITHDRAWN", "TERMINATED"):
            raise ApiError(ERR_CLAIM_ALREADY_TERMINAL, "The claim is WITHDRAWN or TERMINATED.")
        if claim is None or claim["status"] != "ENTITLED":
            raise ApiError(
                ERR_INVALID_STATE, "Payee approval requires the claim still ENTITLED."
            )
    # Layer 8 — segregation of duties.
    if ctx["user_id"] == case["created_by"]:
        raise ApiError(ERR_SAME_ADJUDICATOR, "The case creator may not decide it.")
    if outcome == "APPROVED":
        # Layer 9 — capacity-1 ACTIVE payee per claim.
        for other in store.payees.values():
            if (
                other["claim_id"] == case["claim_id"]
                and other["id"] != case["id"]
                and other["status"] == "ACTIVE"
            ):
                raise ApiError(
                    ERR_ACTIVE_PAYEE_EXISTS, "The claim already has an ACTIVE representative payee."
                )
        case["status"] = "ACTIVE"
        case["decided_by"] = ctx["user_id"]
        touch(case)
        claim["has_active_payee"] = True
        touch(claim)
    else:
        case["status"] = "DENIED"
        case["decided_by"] = ctx["user_id"]
        touch(case)
    return ok(payee_dict(case))
