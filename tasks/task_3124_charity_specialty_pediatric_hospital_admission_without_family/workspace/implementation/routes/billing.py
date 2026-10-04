"""BillingAccount and Claim endpoints (PRD §3.4, §3.5)."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_BILLING_ACCOUNT_NOT_FOUND,
                    ERR_CLAIM_NOT_FOUND, ERR_NO_BILLABLE_COVERAGE,
                    ERR_OPEN_CLAIMS_EXIST, bad_request, invalid_state)
from helpers import (get_body, iso_date, is_int, new_id, now_iso, req_dt,
                     req_str, touch)
from middleware import require_auth
from response import success_list, success_object, paginate
from routes.applications import get_application_or_404
from views import billing_account_view, claim_view

bp = Blueprint("billing", __name__)

LIST_ROLES = ["NetworkAdmin", "BillingSpecialist", "CareCoordinator"]

ESTIMATED_RATE = Decimal("0.62")   # per-line provisional estimation rate
CONTRACT_RATE = Decimal("0.60")    # single adjudication rate on the summed total


def get_account_or_404(account_id):
    b = db.billing_accounts.get(account_id)
    if b is None:
        raise ApiError(ERR_BILLING_ACCOUNT_NOT_FOUND, 404, "Billing account id does not exist")
    return b


def get_claim_or_404(claim_id):
    c = db.claims.get(claim_id)
    if c is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, 404, "Claim id does not exist")
    return c


def _round_half_up_cents(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _require_billable_coverage(account):
    """Claim submission/adjudication require a VERIFIED policy with coverage_exists."""
    policy_id = account.get("insurance_policy_id")
    if not policy_id:
        raise ApiError(ERR_NO_BILLABLE_COVERAGE, 409,
                       "Claim submission/adjudication requires a VERIFIED "
                       "insurance policy with coverage_exists on the account")
    policy = db.policies.get(policy_id)
    if policy is None or not policy["coverage_exists"] or policy["status"] != "VERIFIED":
        raise ApiError(ERR_NO_BILLABLE_COVERAGE, 409,
                       "Claim submission/adjudication requires a VERIFIED "
                       "insurance policy with coverage_exists on the account")
    return policy


def _family_balance(account):
    return (account["total_charged_cents"] - account["insurance_paid_cents"]
            - account["charity_writeoff_cents"] - account["open_claim_cents"])


@bp.get("/applications/<id>/billing-account")
def get_account_by_application(id):
    require_auth(LIST_ROLES)
    a = get_application_or_404(id)
    items = [b for b in db.billing_accounts.values() if b["application_id"] == a["id"]]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([billing_account_view(b) for b in page], total, limit, offset)


@bp.get("/billing-accounts")
def list_accounts():
    require_auth(LIST_ROLES)
    items = list(db.billing_accounts.values())
    application_id = request.args.get("application_id")
    if application_id:
        items = [b for b in items if b["application_id"] == application_id]
    insurance_policy_id = request.args.get("insurance_policy_id")
    if insurance_policy_id:
        items = [b for b in items if b.get("insurance_policy_id") == insurance_policy_id]
    status = request.args.get("status")
    if status:
        items = [b for b in items if b["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([billing_account_view(b) for b in page], total, limit, offset)


@bp.get("/billing-accounts/<accountId>")
def get_account(accountId):
    require_auth(LIST_ROLES)
    b = get_account_or_404(accountId)
    return success_object(billing_account_view(b))


@bp.post("/billing-accounts/<id>/claims")
def create_claim(id):
    require_auth(["BillingSpecialist"])
    account = get_account_or_404(id)
    body = get_body()
    service_date = req_dt(body, "service_date")
    lines = body.get("lines")
    if lines is None:
        raise bad_request("Missing required field: lines")
    if not isinstance(lines, list) or len(lines) < 1:
        raise bad_request("Field lines must be a non-empty array")
    parsed_lines = []
    for line in lines:
        if not isinstance(line, dict):
            raise bad_request("Each claim line must be an object")
        cpt_code = line.get("cpt_code")
        if not isinstance(cpt_code, str) or cpt_code == "":
            raise bad_request("Each claim line requires a non-empty cpt_code")
        charge_cents = line.get("charge_cents")
        if not is_int(charge_cents) or charge_cents < 1:
            raise bad_request("Each claim line requires charge_cents >= 1")
        parsed_lines.append({"cpt_code": cpt_code, "charge_cents": charge_cents})

    _require_billable_coverage(account)

    submitted = sum(l["charge_cents"] for l in parsed_lines)
    # PROVISIONAL variant: round per line at 0.62, then sum
    estimated = sum(
        _round_half_up_cents(Decimal(l["charge_cents"]) * ESTIMATED_RATE)
        for l in parsed_lines
    )
    now = now_iso()
    c = {
        "id": new_id(),
        "billing_account_id": account["id"],
        "service_date": iso_date(service_date),
        "lines": parsed_lines,
        "submitted_amount_cents": submitted,
        "estimated_allowed_cents": estimated,
        "adjudicated_amount_cents": None,
        "status": "SUBMITTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.claims[c["id"]] = c
    account["total_charged_cents"] += submitted
    account["open_claim_cents"] += submitted
    touch(account)
    return success_object(claim_view(c), 201)


@bp.get("/billing-accounts/<id>/claims")
def list_claims(id):
    require_auth(LIST_ROLES)
    account = get_account_or_404(id)
    items = [c for c in db.claims.values() if c["billing_account_id"] == account["id"]]
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([claim_view(c) for c in page], total, limit, offset)


@bp.get("/claims/<claimId>")
def get_claim(claimId):
    require_auth(LIST_ROLES)
    c = get_claim_or_404(claimId)
    return success_object(claim_view(c))


@bp.post("/claims/<claimId>/adjudicate")
def adjudicate_claim(claimId):
    require_auth(["BillingSpecialist"])
    c = get_claim_or_404(claimId)
    account = get_account_or_404(c["billing_account_id"])
    if c["status"] != "SUBMITTED":
        raise invalid_state("Claim must be SUBMITTED to adjudicate")
    _require_billable_coverage(account)

    # FINAL variant: sum raw charges, apply 0.60 once, round half-up once
    total = Decimal(sum(l["charge_cents"] for l in c["lines"]))
    adjudicated = _round_half_up_cents(total * CONTRACT_RATE)

    c["adjudicated_amount_cents"] = adjudicated
    c["status"] = "ADJUDICATED"
    touch(c)

    account["open_claim_cents"] -= c["submitted_amount_cents"]
    account["insurance_paid_cents"] += adjudicated
    account["charity_writeoff_cents"] += c["submitted_amount_cents"] - adjudicated
    account["family_balance_cents"] = _family_balance(account)
    touch(account)
    return success_object(claim_view(c))


@bp.post("/claims/<claimId>/deny")
def deny_claim(claimId):
    require_auth(["BillingSpecialist"])
    c = get_claim_or_404(claimId)
    account = get_account_or_404(c["billing_account_id"])
    if c["status"] != "SUBMITTED":
        raise invalid_state("Claim must be SUBMITTED to deny")
    c["status"] = "DENIED_CLAIM"
    touch(c)
    account["open_claim_cents"] -= c["submitted_amount_cents"]
    account["charity_writeoff_cents"] += c["submitted_amount_cents"]
    account["family_balance_cents"] = _family_balance(account)
    touch(account)
    return success_object(claim_view(c))


@bp.post("/billing-accounts/<accountId>/settle")
def settle_account(accountId):
    require_auth(["BillingSpecialist"])
    account = get_account_or_404(accountId)
    if account["status"] != "OPEN":
        raise invalid_state("Billing account must be OPEN to settle")
    if account["open_claim_cents"] != 0:
        raise ApiError(ERR_OPEN_CLAIMS_EXIST, 409,
                       "Settle blocked by SUBMITTED claims (open_claim_cents > 0)")
    # No-balance-billing invariant: sweep any nonzero residue to charity write-off
    residue = _family_balance(account)
    if residue != 0:
        account["charity_writeoff_cents"] += residue
    account["family_balance_cents"] = 0
    account["status"] = "SETTLED"
    touch(account)
    return success_object(billing_account_view(account))
