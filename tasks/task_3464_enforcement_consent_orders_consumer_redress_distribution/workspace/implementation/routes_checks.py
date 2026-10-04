"""RefundCheck lifecycle: CASHED and VOIDED with claim/fund ledger cascades."""
from flask import Blueprint

import envelope
import errors
import requtil
import store

bp = Blueprint("checks", __name__)

CHECK_STATES = {"ISSUED", "CASHED", "STALE", "VOIDED"}
# STALE is system-only (clock sweep at stale_after).
CHECK_TRANSITIONS = {
    "CASHED": {"ISSUED"},
    "VOIDED": {"ISSUED", "STALE"},
}


@bp.route("/enforcement/refund-checks/<checkId>/transition", methods=["POST"])
def transition_check(checkId):
    _user_id, role = requtil.context()
    requtil.require_role(role, ["DisbursementOfficer"])
    check = requtil.get_or_404(
        store.db.refund_checks, checkId, "ERR_REFUND_CHECK_NOT_FOUND", "RefundCheck"
    )
    body = requtil.json_body()
    target = requtil.need_enum(body, "target_state", CHECK_STATES)
    voided_reason = None
    if target == "VOIDED":
        voided_reason = requtil.need_str(body, "voided_reason")
    if target not in CHECK_TRANSITIONS or check["status"] not in CHECK_TRANSITIONS[target]:
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "RefundCheck cannot transition from {} to {}".format(
                check["status"], target
            ),
        )
    with store.db.lock:
        check["status"] = target
        store.touch(check)
        claim = store.db.claims.get(check["claim_id"])
        fund = store.db.redress_funds.get(check["redress_fund_id"])
        if target == "CASHED":
            check["cashed_at"] = store.now_str()
            if claim is not None and claim["status"] == "PAYMENT_PENDING":
                claim["status"] = "PAID"
                store.touch(claim)
            if fund is not None:
                fund["allocated_cents"] -= check["amount_cents"]
                fund["disbursed_cents"] += check["amount_cents"]
                store.touch(fund)
        elif target == "VOIDED":
            check["voided_reason"] = voided_reason
            # Only uncashed checks are voidable, so the claim always reverts
            # PAYMENT_PENDING -> APPROVED and the allocation is released.
            if claim is not None and claim["status"] == "PAYMENT_PENDING":
                claim["status"] = "APPROVED"
                store.touch(claim)
            if fund is not None:
                fund["allocated_cents"] -= check["amount_cents"]
                fund["available_cents"] += check["amount_cents"]
                store.touch(fund)
    return envelope.success(store.public(check), 200)
