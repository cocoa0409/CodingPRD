"""AccuracyClaim endpoints: file, list, start-review, adjudicate, reopen, pay."""
from flask import Blueprint

from core import (
    GUARANTEE_CAP_CENTS,
    ApiError,
    check_ownership,
    db,
    endpoint,
    f_int,
    body,
    bad_request,
    dump,
    new_row,
    paginate,
    respond_object,
    touch,
)
import svc

bp = Blueprint("claims", __name__)


def _own(return_id):
    ret = svc.get_return(return_id)
    acct = db.accounts[ret["account_id"]]
    check_ownership(acct)
    return ret, acct


@bp.post("/tax/returns/<return_id>/claims")
@endpoint("Taxpayer")
def file_claim(return_id):
    ret, acct = _own(return_id)
    payload = body()
    claimed = f_int(payload, "claimed_error_amount_cents")
    # Referential check is evaluated before the amount check (PRD 3.8).
    if ret["status"] not in ("ACCEPTED", "AMENDED"):
        raise ApiError("ERR_RETURN_NOT_FILED", "Claim requires the return to have reached ACCEPTED at least once.")
    if claimed <= 0:
        raise ApiError("ERR_INVALID_CLAIM_AMOUNT", "claimed_error_amount_cents must be greater than zero.")
    claim = new_row(
        "claim",
        return_id=ret["id"],
        claimed_error_amount_cents=claimed,
        reviewed_error_amount_cents=None,
        reimbursement_cents=0,
        status="FILED",
    )
    db.claims[claim["id"]] = claim
    return respond_object(dump(claim), status=201)


@bp.get("/tax/returns/<return_id>/claims")
@endpoint("Taxpayer", "ClaimsAdjuster")
def list_claims(return_id):
    ret, _acct = _own(return_id)
    return paginate(svc.claims_of(ret))


@bp.post("/tax/claims/<claim_id>/start-review")
@endpoint("ClaimsAdjuster")
def start_review(claim_id):
    claim = svc.get_claim(claim_id)
    acct = db.accounts[db.returns[claim["return_id"]]["account_id"]]
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not FILED.")
    if not acct["accuracy_guarantee_enrolled"]:
        raise ApiError("ERR_GUARANTEE_NOT_ENROLLED", "Account is not enrolled in the accuracy guarantee program.")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return respond_object(dump(claim))


@bp.post("/tax/claims/<claim_id>/adjudicate")
@endpoint("ClaimsAdjuster")
def adjudicate(claim_id):
    claim = svc.get_claim(claim_id)
    payload = body()
    reviewed = f_int(payload, "reviewed_error_amount_cents")
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW.")
    if reviewed < 0:
        raise ApiError("ERR_INVALID_CLAIM_AMOUNT", "reviewed_error_amount_cents must not be negative.")
    claim["reviewed_error_amount_cents"] = reviewed
    if reviewed == 0:
        claim["status"] = "DENIED"
        claim["reimbursement_cents"] = 0
    else:
        if reviewed == claim["claimed_error_amount_cents"]:
            claim["status"] = "APPROVED"
        elif reviewed < claim["claimed_error_amount_cents"]:
            claim["status"] = "PARTIALLY_APPROVED"
        else:
            claim["status"] = "APPROVED"
        raw = min(reviewed, claim["claimed_error_amount_cents"])
        claim["reimbursement_cents"] = min(raw, GUARANTEE_CAP_CENTS)
    touch(claim)
    return respond_object(dump(claim))


@bp.post("/tax/claims/<claim_id>/reopen-review")
@endpoint("ClaimsAdjuster")
def reopen_review(claim_id):
    claim = svc.get_claim(claim_id)
    if claim["status"] != "PARTIALLY_APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only a PARTIALLY_APPROVED claim can be reopened.")
    claim["status"] = "UNDER_REVIEW"
    claim["reimbursement_cents"] = 0
    touch(claim)
    return respond_object(dump(claim))


@bp.post("/tax/claims/<claim_id>/pay")
@endpoint("ClaimsAdjuster")
def pay_claim(claim_id):
    claim = svc.get_claim(claim_id)
    if claim["status"] not in ("APPROVED", "PARTIALLY_APPROVED"):
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED or PARTIALLY_APPROVED claim can be paid.")
    claim["status"] = "PAID"
    touch(claim)
    return respond_object(dump(claim))
