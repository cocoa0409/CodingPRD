"""The purchase lifecycle: approval track, provider claim and settlement."""
from flask import Blueprint

import lookups
from envelope import list_response, object_response, public, touch
from errors import fail
from routes.accounts import committed_in_category, provider_eligible_for_flow
from store import by_seq, new_id, store
from validators import (APPROVAL_STATUSES, SETTLEMENT_STATUSES, authenticate,
                        body, paginate, q_enum, q_str, v_enum, v_int, v_str)

bp = Blueprint("purchase_requests", __name__)

READ_ROLES = ("ProgramAdmin", "ExpenseReviewer", "ComplianceOfficer",
              "AppealsOfficer", "Guardian", "Provider")


@bp.get("/purchase-requests/<prid>")
def read_purchase_request(prid):
    authenticate(*READ_ROLES)
    return object_response(public(lookups.purchase_request(prid)))


@bp.get("/purchase-requests")
def list_purchase_requests():
    authenticate(*READ_ROLES)
    account_id = q_str("account_id")
    provider_id = q_str("provider_id")
    expense_category_id = q_str("expense_category_id")
    approval_status = q_enum("approval_status", APPROVAL_STATUSES)
    settlement_status = q_enum("settlement_status", SETTLEMENT_STATUSES)
    rows = by_seq(list(store.purchase_requests.values()))
    if account_id:
        rows = [p for p in rows if p["account_id"] == account_id]
    if provider_id:
        rows = [p for p in rows if p["provider_id"] == provider_id]
    if expense_category_id:
        rows = [p for p in rows if p["expense_category_id"] == expense_category_id]
    if approval_status:
        rows = [p for p in rows if p["approval_status"] == approval_status]
    if settlement_status:
        rows = [p for p in rows if p["settlement_status"] == settlement_status]
    page, meta = paginate(rows)
    return list_response([public(p) for p in page], meta)


def _open_duplicate_invoice_case(pr, acct):
    created_at = store.next_created_at()
    case = {
        "id": new_id(),
        "account_id": acct["id"],
        "purchase_request_id": pr["id"],
        "detection_rule": "DUPLICATE_INVOICE",
        "disallowed_principal_cents": pr["paid_amount_cents"],
        "narrative": "Auto-opened by settlement-time duplicate-invoice detection.",
        "status": "OPEN",
        "opened_by_user_id": "system",
        "reviewed_by_user_id": None,
        "adjudicated_by_user_id": None,
        "penalty_rate": None,
        "penalty_cents": None,
        "clawback_total_cents": None,
        "account_debit_cents": None,
        "receivable_cents": None,
        "auto_opened": True,
        "created_at": created_at,
        "updated_at": created_at,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.misuse_cases[case["id"]] = case
    return case["id"]


def apply_settlement(pr, acct, user_id):
    """CLAIMED -> PAID plus the ledger movement and duplicate detection."""
    claimed = pr["claimed_amount_cents"] or 0
    pr["paid_amount_cents"] = claimed
    pr["settled_by_user_id"] = user_id
    pr["settlement_status"] = "PAID"
    released = pr["amount_cents"] - claimed
    acct["encumbered_cents"] -= pr["amount_cents"]
    acct["lifetime_spent_cents"] += claimed
    acct["balance_cents"] += released
    touch(pr)
    touch(acct)

    opened_case_id = None
    for other in lookups.purchase_requests_of_account(acct["id"]):
        if other["id"] == pr["id"]:
            continue
        if other["settlement_status"] != "PAID":
            continue
        if other["provider_id"] != pr["provider_id"]:
            continue
        if other["invoice_reference"] != pr["invoice_reference"]:
            continue
        pr["flagged_rule"] = "DUPLICATE_INVOICE"
        opened_case_id = _open_duplicate_invoice_case(pr, acct)
        break
    return released, opened_case_id


@bp.post("/purchase-requests/<prid>/decision")
def decide_purchase_request(prid):
    user_id, _role = authenticate("ExpenseReviewer")
    payload = body()
    decision = v_enum(payload, "decision", ("APPROVED", "DENIED", "VOID"))
    reason = v_str(payload, "reason", required=False, default=None)
    pr = lookups.purchase_request(prid)
    acct = store.accounts[pr["account_id"]]

    if decision == "APPROVED":
        if pr["approval_status"] != "PENDING_REVIEW":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "only a PENDING_REVIEW request may be approved")
        if acct["status"] == "CLOSED":
            fail("ERR_INVALID_STATE_TRANSITION", "the account is closed")
        if acct["status"] != "ACTIVE":
            fail("ERR_ACCOUNT_SUSPENDED", "the account is suspended")
        prov = store.providers[pr["provider_id"]]
        if not provider_eligible_for_flow(prov, pr["flow"]):
            fail("ERR_PROVIDER_NOT_ELIGIBLE",
                 "provider is not participation-eligible for this flow")
        category = store.expense_categories[pr["expense_category_id"]]
        if category["code"] not in prov["authorized_category_codes"]:
            fail("ERR_CATEGORY_NOT_AUTHORIZED",
                 "the provider is no longer authorised for this category")
        committed = committed_in_category(acct["id"], category["id"],
                                         exclude_id=pr["id"])
        if pr["amount_cents"] > category["per_year_cap_cents"] - committed:
            fail("ERR_CATEGORY_CAP_EXCEEDED",
                 "the category annual cap does not admit this amount")
        if pr["amount_cents"] > acct["balance_cents"]:
            fail("ERR_INSUFFICIENT_BALANCE",
                 "the account balance does not cover the hold")

        pr["approval_status"] = "APPROVED"
        pr["approved_by_user_id"] = user_id
        if reason is not None:
            pr["decision_reason"] = reason
        acct["balance_cents"] -= pr["amount_cents"]
        acct["encumbered_cents"] += pr["amount_cents"]
        touch(pr)
        touch(acct)
        # Reimbursement shortcut: an already-claimed reimbursement settles now.
        if pr["flow"] == "REIMBURSEMENT" and pr["settlement_status"] == "CLAIMED":
            apply_settlement(pr, acct, user_id)

    elif decision == "DENIED":
        if pr["approval_status"] != "PENDING_REVIEW":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "only a PENDING_REVIEW request may be denied")
        pr["approval_status"] = "DENIED"
        pr["settlement_status"] = "CANCELLED"
        if reason is not None:
            pr["decision_reason"] = reason
        touch(pr)

    else:
        if (pr["approval_status"] != "APPROVED"
                or pr["settlement_status"] not in ("UNSETTLED", "CLAIMED")):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "only an APPROVED, unsettled request may be voided")
        pr["approval_status"] = "VOID"
        pr["settlement_status"] = "CANCELLED"
        if reason is not None:
            pr["decision_reason"] = reason
        acct["encumbered_cents"] -= pr["amount_cents"]
        acct["balance_cents"] += pr["amount_cents"]
        touch(pr)
        touch(acct)

    return object_response(public(pr))


@bp.post("/purchase-requests/<prid>/claim")
def claim_purchase_request(prid):
    user_id, _role = authenticate("Provider")
    payload = body()
    invoice_reference = v_str(payload, "invoice_reference")
    claimed_amount_cents = v_int(payload, "claimed_amount_cents", minimum=0)
    pr = lookups.purchase_request(prid)

    if pr["provider_id"] != user_id:
        fail("ERR_NOT_ASSIGNED_PROVIDER",
             "only the named provider may claim against this request")
    if (pr["settlement_status"] != "UNSETTLED"
            or pr["approval_status"] not in ("PENDING_REVIEW", "APPROVED")):
        fail("ERR_INVALID_STATE_TRANSITION",
             "the request is not open for an invoice claim")
    if claimed_amount_cents < 1 or claimed_amount_cents > pr["amount_cents"]:
        fail("ERR_CLAIM_AMOUNT_MISMATCH",
             "claimed_amount_cents must be between 1 and the requested amount")

    pr["settlement_status"] = "CLAIMED"
    pr["claimed_amount_cents"] = claimed_amount_cents
    pr["invoice_reference"] = invoice_reference
    touch(pr)
    return object_response(public(pr))


@bp.post("/purchase-requests/<prid>/settle")
def settle_purchase_request(prid):
    user_id, _role = authenticate("ExpenseReviewer")
    pr = lookups.purchase_request(prid)
    acct = store.accounts[pr["account_id"]]

    if pr["settlement_status"] != "CLAIMED" or pr["approval_status"] != "APPROVED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "settlement requires an APPROVED request with a CLAIMED invoice")
    if acct["status"] == "CLOSED":
        fail("ERR_INVALID_STATE_TRANSITION", "the account is closed")
    if acct["status"] != "ACTIVE":
        fail("ERR_ACCOUNT_SUSPENDED", "the account is suspended")
    if pr["approved_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the approving reviewer may not settle the same request")
    prov = store.providers[pr["provider_id"]]
    if prov["status"] not in ("APPROVED", "PROBATION"):
        fail("ERR_PROVIDER_NOT_ELIGIBLE", "the provider may not be paid")
    category = store.expense_categories[pr["expense_category_id"]]
    if category["code"] not in prov["authorized_category_codes"]:
        fail("ERR_CATEGORY_NOT_AUTHORIZED",
             "the provider is no longer authorised for this category")

    released, opened_case_id = apply_settlement(pr, acct, user_id)
    return object_response({
        "purchase_request_id": pr["id"],
        "settlement_status": pr["settlement_status"],
        "paid_amount_cents": pr["paid_amount_cents"],
        "released_cents": released,
        "account_balance_cents": acct["balance_cents"],
        "account_encumbered_cents": acct["encumbered_cents"],
        "opened_misuse_case_id": opened_case_id,
    })
