"""RefundTransferAgreement endpoints: create, list, accept-disclosure, void."""
from flask import Blueprint

from core import (
    ACTIVE_BANK_DISCLOSURE_VERSION,
    REGISTERED_BANK_PARTNERS,
    REFUND_TRANSFER_FEE_CENTS,
    ApiError,
    check_ownership,
    db,
    endpoint,
    expected_version,
    f_str,
    body,
    dump,
    new_row,
    paginate,
    respond_object,
    touch,
)
import svc

bp = Blueprint("refund_transfer", __name__)


def _own(return_id):
    ret = svc.get_return(return_id)
    acct = db.accounts[ret["account_id"]]
    check_ownership(acct)
    return ret, acct


def _live_agreement(ret):
    """The 0..1 live (PENDING_DISCLOSURE or ACTIVE) agreement for the return."""
    for ag in svc.agreements_of(ret):
        if ag["status"] in ("PENDING_DISCLOSURE", "ACTIVE"):
            return ag
    return None


@bp.post("/tax/returns/<return_id>/refund-transfer")
@endpoint("Taxpayer")
def create_agreement(return_id):
    ret, acct = _own(return_id)
    payload = body()
    bank = f_str(payload, "bank_partner_code")
    if bank not in REGISTERED_BANK_PARTNERS:
        raise ApiError("ERR_BANK_PARTNER_NOT_FOUND", "bank_partner_code is not a registered partner.")
    svc.require_account_active(acct)
    svc.require_return_editable(ret, error_id="ERR_INVALID_STATE")
    expected_version(payload, ret)
    if _live_agreement(ret) is not None:
        raise ApiError("ERR_INVALID_STATE", "A live refund-transfer agreement already exists for this return.")
    ag = new_row(
        "refund_transfer",
        return_id=ret["id"],
        bank_partner_code=bank,
        service_fee_cents=REFUND_TRANSFER_FEE_CENTS,
        disclosure_version=ACTIVE_BANK_DISCLOSURE_VERSION,
        status="PENDING_DISCLOSURE",
    )
    db.refund_transfers[ag["id"]] = ag
    touch(ret)
    return respond_object(dump(ag), status=201)


@bp.get("/tax/returns/<return_id>/refund-transfer")
@endpoint("Taxpayer", "PlatformOperator")
def list_agreements(return_id):
    ret, _acct = _own(return_id)
    return paginate(svc.agreements_of(ret))


@bp.post("/tax/returns/<return_id>/refund-transfer/accept-disclosure")
@endpoint("Taxpayer")
def accept_disclosure(return_id):
    ret, acct = _own(return_id)
    payload = body()
    svc.require_account_active(acct)
    if ret["status"] not in ("DRAFT", "AMENDED", "READY_FOR_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", "Disclosure cannot be accepted from this return status.")
    expected_version(payload, ret)
    ag = _live_agreement(ret)
    if ag is None or ag["status"] != "PENDING_DISCLOSURE":
        raise ApiError("ERR_INVALID_STATE", "No PENDING_DISCLOSURE agreement exists.")
    ag["status"] = "ACTIVE"
    touch(ag)
    acct["disclosure_accepted_version"] = ag["disclosure_version"]
    touch(acct)
    ret["refund_transfer_selected"] = True
    svc.recompute_fees(ret)
    touch(ret)
    return respond_object(dump(ag))


@bp.post("/tax/returns/<return_id>/refund-transfer/void")
@endpoint("Taxpayer")
def void_agreement(return_id):
    ret, acct = _own(return_id)
    payload = body()
    svc.require_account_active(acct)
    svc.require_return_editable(ret, error_id="ERR_INVALID_STATE")
    expected_version(payload, ret)
    ag = _live_agreement(ret)
    if ag is None:
        raise ApiError("ERR_INVALID_STATE", "No live refund-transfer agreement exists.")
    if ag["status"] == "ACTIVE" and svc.pending_attempt(ret) is not None:
        raise ApiError("ERR_FILING_IN_FLIGHT", "A PENDING filing attempt exists.")
    ag["status"] = "VOIDED"
    touch(ag)
    ret["refund_transfer_selected"] = False
    svc.recompute_fees(ret)
    touch(ret)
    return respond_object(dump(ag))
