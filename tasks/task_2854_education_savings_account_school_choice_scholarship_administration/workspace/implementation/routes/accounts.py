"""Account ledger reads, status actions and purchase-request filing."""
from flask import Blueprint

import cascades
import lookups
from envelope import list_response, object_response, public, touch
from errors import fail, invalid
from store import (by_seq, day_last_second_instant, day_start_instant, new_id,
                   store)
from validators import (ACCOUNT_STATUSES, authenticate, body, paginate, q_enum,
                        q_str, v_enum, v_instant, v_int, v_str)

bp = Blueprint("accounts", __name__)

CLOSED_CASE_STATUSES = ("DISMISSED", "RESOLVED", "REVERSED")


def provider_eligible_for_flow(prov, flow):
    if flow == "REIMBURSEMENT":
        return prov["status"] == "APPROVED"
    return prov["status"] in ("APPROVED", "PROBATION")


def committed_in_category(account_id, expense_category_id, exclude_id=None):
    total = 0
    for pr in store.purchase_requests.values():
        if pr["account_id"] != account_id:
            continue
        if pr["expense_category_id"] != expense_category_id:
            continue
        if exclude_id is not None and pr["id"] == exclude_id:
            continue
        if pr["approval_status"] != "APPROVED":
            continue
        total += pr["amount_cents"]
    return total


@bp.get("/accounts/<acid>")
def read_account(acid):
    authenticate("ProgramAdmin", "ComplianceOfficer", "ExpenseReviewer",
                 "EligibilityOfficer", "AppealsOfficer", "Guardian")
    return object_response(public(lookups.account(acid)))


@bp.get("/accounts")
def list_accounts():
    authenticate("ProgramAdmin", "ComplianceOfficer", "ExpenseReviewer",
                 "EligibilityOfficer", "Guardian")
    application_id = q_str("application_id")
    program_year_id = q_str("program_year_id")
    status = q_enum("status", ACCOUNT_STATUSES)
    rows = by_seq(list(store.accounts.values()))
    if application_id:
        rows = [a for a in rows if a["application_id"] == application_id]
    if program_year_id:
        rows = [a for a in rows if a["program_year_id"] == program_year_id]
    if status:
        rows = [a for a in rows if a["status"] == status]
    page, meta = paginate(rows)
    return list_response([public(a) for a in page], meta)


@bp.get("/accounts/<acid>/disbursements")
def list_account_disbursements(acid):
    authenticate("ProgramAdmin", "ComplianceOfficer", "Guardian")
    lookups.account(acid)
    rows = by_seq([d for d in store.disbursements.values()
                   if d["account_id"] == acid])
    page, meta = paginate(rows)
    return list_response([public(r) for r in page], meta)


@bp.get("/accounts/<acid>/clawback-entries")
def list_account_clawback_entries(acid):
    authenticate("ProgramAdmin", "ComplianceOfficer", "AppealsOfficer",
                 "Guardian")
    lookups.account(acid)
    rows = by_seq([e for e in store.clawback_entries.values()
                   if e["account_id"] == acid])
    page, meta = paginate(rows)
    return list_response([public(r) for r in page], meta)


@bp.post("/accounts/<acid>/status-actions")
def account_status_action(acid):
    authenticate("ComplianceOfficer")
    payload = body()
    action = v_enum(payload, "action", ("SUSPEND", "REINSTATE"))
    reason = v_str(payload, "reason")
    acct = lookups.account(acid)

    if action == "SUSPEND":
        if acct["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "only an ACTIVE account may be suspended")
        cascades.suspend_account(acct, reason)
    else:
        if acct["status"] != "SUSPENDED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "only a SUSPENDED account may be reinstated")
        for case in lookups.misuse_cases_of_account(acid):
            if case["status"] not in CLOSED_CASE_STATUSES:
                fail("ERR_INVALID_STATE_TRANSITION",
                     "a misuse case on this account is still live")
        acct["status"] = "ACTIVE"
        acct["suspension_reason"] = None
        touch(acct)
    return object_response(public(acct))


@bp.post("/accounts/<acid>/purchase-requests")
def create_purchase_request(acid):
    user_id, _role = authenticate("Guardian")
    payload = body()
    provider_id = v_str(payload, "provider_id")
    expense_category_id = v_str(payload, "expense_category_id")
    flow = v_enum(payload, "flow", ("PREAPPROVAL", "REIMBURSEMENT"))
    amount_cents = v_int(payload, "amount_cents", minimum=1)
    service_start_at = v_instant(payload, "service_start_at")
    service_end_at = v_instant(payload, "service_end_at")
    expected_account_version = v_int(payload, "expected_account_version",
                                     minimum=0)
    invoice_reference = v_str(payload, "invoice_reference", required=False,
                             default=None)
    if flow == "REIMBURSEMENT" and not invoice_reference:
        invalid("invoice_reference is required for the REIMBURSEMENT flow")

    acct = lookups.account(acid)
    prov = lookups.provider(provider_id)
    category = lookups.expense_category(expense_category_id)

    app = store.applications.get(acct["application_id"])
    if app is None or app["student_id"] != user_id:
        fail("ERR_NOT_ACCOUNT_HOLDER",
             "only the guardian behind this account may file purchases")
    if expected_account_version != acct["version"]:
        fail("ERR_STALE_ACCOUNT_VERSION",
             "expected_account_version %s does not match the account version %s"
             % (expected_account_version, acct["version"]))
    if acct["status"] == "CLOSED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "no purchase may be filed against a CLOSED account")
    if acct["status"] != "ACTIVE":
        fail("ERR_ACCOUNT_SUSPENDED", "the account is suspended")
    if not provider_eligible_for_flow(prov, flow):
        fail("ERR_PROVIDER_NOT_ELIGIBLE",
             "provider is not participation-eligible for this flow")
    if category["code"] not in prov["authorized_category_codes"]:
        fail("ERR_CATEGORY_NOT_AUTHORIZED",
             "the provider is not authorised for category '%s'" % category["code"])
    if not category["allowable"]:
        fail("ERR_EXPENSE_NOT_ALLOWABLE",
             "category '%s' is catalogued but not allowable" % category["code"])
    if flow == "REIMBURSEMENT" and category["requires_preapproval"]:
        fail("ERR_PREAPPROVAL_REQUIRED",
             "category '%s' requires pre-approval" % category["code"])

    if category["requires_service_period"]:
        for other in lookups.purchase_requests_of_account(acid):
            if other["expense_category_id"] != expense_category_id:
                continue
            if other["approval_status"] not in ("PENDING_REVIEW", "APPROVED"):
                continue
            # Half-open intervals: touching end-to-start does not collide.
            if (service_start_at < other["service_end_at"]
                    and other["service_start_at"] < service_end_at):
                fail("ERR_DUPLICATE_SERVICE_PERIOD",
                     "an open request already covers an intersecting interval")

    py = store.program_years[acct["program_year_id"]]
    term_start = day_start_instant(py["term_start_date"])
    term_end = day_last_second_instant(py["term_end_date"])
    if (service_end_at <= service_start_at
            or service_start_at < term_start
            or service_end_at > term_end):
        fail("ERR_SERVICE_PERIOD_OUTSIDE_TERM",
             "the service interval must lie inside the instructional term")

    committed = committed_in_category(acid, expense_category_id)
    if amount_cents > category["per_year_cap_cents"] - committed:
        fail("ERR_CATEGORY_CAP_EXCEEDED",
             "the category annual cap does not admit this amount")

    created_at = store.next_created_at()
    record = {
        "id": new_id(),
        "account_id": acid,
        "provider_id": provider_id,
        "expense_category_id": expense_category_id,
        "flow": flow,
        "amount_cents": amount_cents,
        "service_start_at": service_start_at,
        "service_end_at": service_end_at,
        "invoice_reference": invoice_reference,
        "approval_status": "PENDING_REVIEW",
        "settlement_status": "UNSETTLED",
        "claimed_amount_cents": None,
        "paid_amount_cents": None,
        "approved_by_user_id": None,
        "settled_by_user_id": None,
        "decision_reason": None,
        "flagged_rule": None,
        "created_at": created_at,
        "updated_at": created_at,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.purchase_requests[record["id"]] = record
    # Filing consumes the account's version guard even though no money moves.
    touch(acct)
    return object_response(public(record), 201)
