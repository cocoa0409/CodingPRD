"""RefundRequest endpoints: get/list, decide (APPROVE/DENY), mark-paid.

Segregation of duties (PRD section 3.8, tier 3): a staff requester may not
self-decide (account-holder and 'system' requesters are exempt), and the
payer must differ from the decider ('system' deciders never conflict).
DENY computes the would-be payout with the same formula and, when positive,
moves it into the account's unclaimed (escheat-eligible) balance.
"""

from flask import Blueprint

from calc import refund_payout
from core import (ALL_ROLES, CLOCK, DB, append_ledger, auth, body, err,
                  ledger_of, list_response, ok_obj, opt_str, pub, req_enum,
                  settled_totals, touch, apply_filters)

bp = Blueprint("refunds", __name__)


def refund_or_404(refund_id):
    refund = DB.refunds.get(refund_id)
    if refund is None:
        err("ERR_REFUND_REQUEST_NOT_FOUND", 404,
            "RefundRequest %s does not exist" % refund_id)
    return refund


@bp.get("/comm-services/refund-requests/<refund_id>")
def get_refund(refund_id):
    auth(ALL_ROLES)
    return ok_obj(pub(refund_or_404(refund_id)))


@bp.get("/comm-services/refund-requests")
def list_refunds():
    auth(ALL_ROLES)
    items = apply_filters(DB.refunds.values(),
                          ["account_id", "status", "source"])
    return list_response(items, pub)


@bp.post("/comm-services/refund-requests/<refund_id>/decide")
def decide_refund(refund_id):
    user_id, role = auth(["ComplianceOfficer"])
    data = body()
    refund = refund_or_404(refund_id)
    # Tier 3 segregation of duties: only non-holder, non-system requesters
    # are barred from deciding their own request.
    if (refund["requested_by_role"] not in ("AccountHolder", "system")
            and refund["requested_by_user_id"] == user_id):
        err("ERR_SOD_VIOLATION", 403,
            "The requesting staff member may not decide their own refund")
    decision = req_enum(data, "decision", ("APPROVE", "DENY"))
    denial_reason = opt_str(data, "denial_reason")
    if decision == "DENY" and not denial_reason:
        err("ERR_INVALID_REQUEST", 400,
            "denial_reason is required on a DENY decision")
    if refund["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", 409,
            "Only a REQUESTED refund can be decided")
    account = DB.accounts.get(refund["account_id"])
    # Recompute with the same formula and inputs as at closure: the ledger is
    # frozen while the request pends, and the close-time closure fee and
    # jurisdiction refund-method variant were pinned on the account.
    method = account.get("_refund_method", "SIMPLE_BALANCE")
    fee = account.get("_closure_fee_cents", 0)
    payout = refund_payout(method, ledger_of(account["id"]),
                           account["balance_at_closure_cents"] or 0, fee)
    refund["computed_payout_cents"] = payout
    refund["refund_method_applied"] = method
    refund["decided_by_user_id"] = user_id
    if decision == "APPROVE":
        refund["status"] = "APPROVED"
    else:
        refund["status"] = "DENIED"
        refund["denial_reason"] = denial_reason
        if payout > 0:
            # The would-be payout becomes the unclaimed, escheat-eligible
            # balance; escheat_status stays NONE until the dormancy scan.
            account["unclaimed_balance_cents"] = payout
            account["unclaimed_since"] = CLOCK.now()
            touch(account)
    touch(refund)
    return ok_obj(pub(refund))


@bp.post("/comm-services/refund-requests/<refund_id>/mark-paid")
def mark_paid(refund_id):
    user_id, role = auth(["ComplianceOfficer"])
    refund = refund_or_404(refund_id)
    # Tier 3 segregation of duties: the payer must differ from the decider;
    # a 'system' decider never conflicts.
    if (refund["decided_by_user_id"] is not None
            and refund["decided_by_user_id"] != "system"
            and refund["decided_by_user_id"] == user_id):
        err("ERR_SOD_VIOLATION", 403,
            "The disbursing officer must differ from the deciding officer")
    if refund["status"] != "APPROVED":
        err("ERR_REFUND_NOT_PAYABLE", 409,
            "Only an APPROVED refund request can be paid")
    account = DB.accounts.get(refund["account_id"])
    payout = refund["computed_payout_cents"]
    closure_balance = account["balance_at_closure_cents"] or 0
    refunded_prior, escheated_prior = settled_totals(account["id"])
    append_ledger(account, "REFUND_PAYOUT", -payout, refund["id"],
                  "Refund payout")
    # Settling CLOSURE_FEE: negative of the snapshot minus this payout minus
    # everything already settled; a credit when restored deposit fees exceed
    # the closure fee (the ledger's one unusual credit case).
    settling = -(closure_balance - refunded_prior - escheated_prior - payout)
    append_ledger(account, "CLOSURE_FEE", settling, refund["id"],
                  "Settling closure fee on refund disbursement")
    if refund["source"] == "ESCHEAT_CLAIM":
        account["unclaimed_balance_cents"] = 0
        account["unclaimed_since"] = None
    touch(account)
    refund["status"] = "PAID"
    refund["paid_by_user_id"] = user_id
    refund["paid_at"] = CLOCK.now()
    touch(refund)
    return ok_obj(pub(refund))
