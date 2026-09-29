"""ReimbursementClaim endpoints: submission, substantiation, adjudication and
settlement (PRD 3.7)."""

from flask import Blueprint, request

import calc
import errors
from auth import (ALL_ROLES, ROLE_BILLING_CLERK, ROLE_ENROLLMENT_COUNSELOR,
                  ROLE_HRA_ADMINISTRATOR, ROLE_RETIREE, require_caller,
                  require_ownership)
from domain import body_reference, get_claim, get_hra_account
from envelope import object_response, paginate
from errors import fail
from store import base_record, db, now, order_asc, touch
from validate import read_body

bp = Blueprint("claims", __name__)

EXPENSE_CATEGORIES = ("MEDICARE_PART_B_PREMIUM", "MEDIGAP_PREMIUM",
                      "PART_D_PREMIUM", "EXCHANGE_PREMIUM",
                      "DENTAL_VISION_PREMIUM", "QUALIFIED_MEDICAL")
CLAIM_STATUSES = ("SUBMITTED", "PENDING_SUBSTANTIATION", "APPROVED", "PAID",
                  "DENIED", "REVERSED")
REVIEW_DECISIONS = ("APPROVE", "DENY", "REQUEST_SUBSTANTIATION")
CLAIM_DENIAL_REASON_CODES = ("UNSUBSTANTIATED", "INELIGIBLE_CATEGORY",
                             "ACCOUNT_NOT_OPEN", "REVIEWER_DENIAL")
DEFAULT_CLAIM_DENIAL_REASON_CODE = "REVIEWER_DENIAL"
SETTLEMENT_ACTIONS = ("PAY", "REVERSE")

FILER_ROLES = (ROLE_RETIREE, ROLE_ENROLLMENT_COUNSELOR)


@bp.post("/retiree-benefits/reimbursement-claims")
def create_claim():
    caller = require_caller(FILER_ROLES)
    body = read_body()
    account = body_reference(body, "hra_account_id", get_hra_account)
    if account is not None:
        require_ownership(caller, account["retiree_id"])

    account_id = body.string("hra_account_id")
    expense_category = body.enum("expense_category", EXPENSE_CATEGORIES)
    service_date = body.date("service_date")
    submitted_cents = body.cents("submitted_cents", strictly_positive=True)
    expected_version = body.integer("expected_hra_account_version")
    documentation_reference = body.string("documentation_reference",
                                         required=False, nullable=True,
                                         default=None)

    if expected_version != account["version"]:
        fail(errors.ERR_STALE_HRA_ACCOUNT_VERSION)

    if account["status"] != "OPEN":
        fail(errors.ERR_HRA_ACCOUNT_NOT_OPEN)

    plan_year = db.plan_years.get(account["plan_year_id"])
    window_start = plan_year["coverage_start"]
    window_end = calc.plus_year_minus_day(window_start)
    service_instant = calc.midnight(service_date)
    if service_instant < window_start or service_instant > window_end:
        fail(errors.ERR_EXPENSE_OUTSIDE_PLAN_YEAR)

    if account["available_balance_cents"] <= 0:
        fail(errors.ERR_HRA_BALANCE_INSUFFICIENT)

    provisional = calc.provisional_eligible_cents(
        submitted_cents, account["available_balance_cents"])

    record = base_record()
    record.update({
        "hra_account_id": account_id,
        "expense_category": expense_category,
        "service_date": service_date,
        "submitted_cents": submitted_cents,
        "documentation_reference": documentation_reference,
        "provisional_eligible_cents": provisional,
        "eligible_cents": provisional,
        "status": "SUBMITTED",
        "substantiation_resubmit_count": 0,
        "denial_reason_code": None,
        "created_by_user_id": caller.user_id,
        "reviewed_by_user_id": None,
        "paid_at": None,
    })
    db.claims[record["id"]] = record

    account["pending_hold_cents"] += provisional
    account["available_balance_cents"] -= provisional
    touch(account)

    return object_response(record, 201)


@bp.get("/retiree-benefits/reimbursement-claims/<claim_id>")
def read_claim(claim_id):
    require_caller(ALL_ROLES)
    return object_response(get_claim(claim_id))


@bp.get("/retiree-benefits/reimbursement-claims")
def list_claims():
    require_caller(ALL_ROLES)
    rows = list(db.claims.values())
    for field in ("hra_account_id", "status", "expense_category"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return paginate(order_asc(rows))


@bp.post("/retiree-benefits/reimbursement-claims/<claim_id>/substantiation")
def substantiate_claim(claim_id):
    caller = require_caller(FILER_ROLES)
    claim = get_claim(claim_id)
    account = db.hra_accounts[claim["hra_account_id"]]
    require_ownership(caller, account["retiree_id"])
    body = read_body()
    documentation_reference = body.string("documentation_reference")

    if account["status"] != "OPEN":
        fail(errors.ERR_HRA_ACCOUNT_NOT_OPEN)
    if claim["status"] != "PENDING_SUBSTANTIATION":
        fail(errors.ERR_INVALID_CLAIM_STATE,
             "Attaching documentation requires status PENDING_SUBSTANTIATION.")

    claim["status"] = "SUBMITTED"
    claim["documentation_reference"] = documentation_reference
    claim["substantiation_resubmit_count"] += 1
    touch(claim)
    return object_response(claim)


@bp.post("/retiree-benefits/reimbursement-claims/<claim_id>/review")
def review_claim(claim_id):
    caller = require_caller((ROLE_HRA_ADMINISTRATOR,))
    claim = get_claim(claim_id)
    body = read_body()
    decision = body.enum("decision", REVIEW_DECISIONS)
    denial_reason_code = body.enum("denial_reason_code",
                                   CLAIM_DENIAL_REASON_CODES,
                                   required=False, default=None)

    account = db.hra_accounts[claim["hra_account_id"]]
    if account["status"] != "OPEN":
        fail(errors.ERR_HRA_ACCOUNT_NOT_OPEN)
    if claim["status"] != "SUBMITTED":
        fail(errors.ERR_INVALID_CLAIM_STATE,
             "Review requires a SUBMITTED claim.")
    if decision == "APPROVE" and claim["documentation_reference"] is None:
        fail(errors.ERR_INVALID_CLAIM_STATE,
             "Approval requires a non-null documentation_reference.")

    if claim["created_by_user_id"] is not None \
            and caller.user_id == claim["created_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The submitting user may not review their own claim.")

    claim["reviewed_by_user_id"] = caller.user_id

    if decision == "REQUEST_SUBSTANTIATION":
        claim["status"] = "PENDING_SUBSTANTIATION"
        touch(claim)
        return object_response(claim)

    if decision == "DENY":
        held = claim["eligible_cents"]
        account["pending_hold_cents"] -= held
        account["available_balance_cents"] += held
        claim["eligible_cents"] = 0
        claim["status"] = "DENIED"
        claim["denial_reason_code"] = (
            denial_reason_code or DEFAULT_CLAIM_DENIAL_REASON_CODE)
        touch(claim)
        touch(account)
        return object_response(claim)

    final = calc.final_eligible_cents(
        claim["expense_category"], claim["submitted_cents"],
        account["available_balance_cents"], claim["provisional_eligible_cents"])
    difference = claim["provisional_eligible_cents"] - final
    account["pending_hold_cents"] -= difference
    account["available_balance_cents"] += difference
    claim["eligible_cents"] = final
    claim["status"] = "APPROVED"
    touch(claim)
    touch(account)
    return object_response(claim)


@bp.post("/retiree-benefits/reimbursement-claims/<claim_id>/settlement")
def settle_claim(claim_id):
    caller = require_caller((ROLE_BILLING_CLERK,))
    claim = get_claim(claim_id)
    body = read_body()
    action = body.enum("action", SETTLEMENT_ACTIONS)

    account = db.hra_accounts[claim["hra_account_id"]]
    if account["status"] != "OPEN":
        fail(errors.ERR_HRA_ACCOUNT_NOT_OPEN)

    if action == "PAY" and claim["status"] != "APPROVED":
        fail(errors.ERR_INVALID_CLAIM_STATE,
             "Payment requires an APPROVED claim.")
    if action == "REVERSE" and claim["status"] != "PAID":
        fail(errors.ERR_INVALID_CLAIM_STATE,
             "Reversal requires a PAID claim.")

    if claim["reviewed_by_user_id"] is not None \
            and caller.user_id == claim["reviewed_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The reviewing user may not settle the claim.")

    amount = claim["eligible_cents"]
    if action == "PAY":
        account["pending_hold_cents"] -= amount
        account["substantiated_paid_cents"] += amount
        claim["status"] = "PAID"
        claim["paid_at"] = now()
    else:
        account["substantiated_paid_cents"] -= amount
        account["available_balance_cents"] += amount
        claim["status"] = "REVERSED"
        claim["paid_at"] = None

    touch(claim)
    touch(account)
    return object_response(claim)
