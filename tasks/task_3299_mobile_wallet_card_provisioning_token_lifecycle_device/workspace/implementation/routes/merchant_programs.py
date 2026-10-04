# =============================================================================
# Merchant programs + enrollments (MerchantCardProgram)
# =============================================================================
from flask import Blueprint, request

import db
from errors import ApiError, forbidden
from helpers import (
    list_response, new_common_row, resolve_card_account, resolve_enrollment,
    resolve_issuer, resolve_program,
)
from middleware import (
    get_body, opt_bool, req_int, req_str, require_roles,
)
from response import success_object

bp = Blueprint("merchant_programs", __name__)


@bp.post("/merchant-programs")
def create_program():
    body = get_body()
    issuer_id = req_str(body, "issuer_id")
    program_code = req_str(body, "program_code")
    merchant_name = req_str(body, "merchant_name")
    required_pan_last4 = req_str(body, "required_pan_last4")
    max_auth_amount_cents = req_int(body, "max_auth_amount_cents")
    active_sessions_required = opt_bool(body, "active_sessions_required", True)
    require_roles(["IssuerOperator", "PlatformAdmin"])
    resolve_issuer(issuer_id)
    # program_code unique per issuer among non-retired programs
    for p in db.merchant_programs.values():
        if (p["issuer_id"] == issuer_id and p["program_code"] == program_code
                and p["status"] != "RETIRED"):
            raise ApiError("ERR_VALIDATION",
                           "program_code must be unique per issuer among non-retired programs")
    row = new_common_row({
        "issuer_id": issuer_id,
        "program_code": program_code,
        "merchant_name": merchant_name,
        "required_pan_last4": required_pan_last4,
        "max_auth_amount_cents": max_auth_amount_cents,
        "active_sessions_required": active_sessions_required,
        "status": "ACTIVE",
    })
    db.merchant_programs[row["id"]] = row
    return success_object(row, 201)


@bp.get("/merchant-programs/<programId>")
def get_program(programId):
    return success_object(resolve_program(programId), 200)


@bp.get("/merchant-programs")
def list_programs():
    return list_response(db.merchant_programs.values(), filters={
        "issuer_id": request.args.get("issuer_id"),
        "status": request.args.get("status"),
    })


@bp.get("/merchant-programs/<programId>/enrollments")
def list_program_enrollments(programId):
    resolve_program(programId)
    rows = [e for e in db.merchant_card_programs.values()
            if e["merchant_program_id"] == programId]
    return list_response(rows)


@bp.post("/merchant-card-programs")
def enroll_card():
    body = get_body()
    merchant_program_id = req_str(body, "merchant_program_id")
    card_account_id = req_str(body, "card_account_id")
    user_id, role = require_roles(["Cardholder", "IssuerOperator"])
    program = resolve_program(merchant_program_id)
    account = resolve_card_account(card_account_id)
    if role == "Cardholder" and account["cardholder_id"] != user_id:
        raise forbidden("Cardholder may only enroll their own card accounts")

    # Priority 18: program ACTIVE
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", "Merchant program is not ACTIVE")
    # Account must be OPEN (active_sessions_required=false does not widen the
    # account-state gate — CardAccount has no SUSPENDED status)
    if account["status"] != "OPEN":
        raise ApiError("ERR_CARD_ACCOUNT_RESTRICTED", "Card account must be OPEN")
    # required_pan_last4: empty string skips the constraint; otherwise the
    # earliest-created artifact's pan_last4 must match exactly
    if program["required_pan_last4"] != "":
        artifacts = [a for a in db.card_artifacts.values()
                     if a["card_account_id"] == account["id"]]
        artifacts.sort(key=lambda a: (a["created_at"], a["id"]))
        earliest = artifacts[0] if artifacts else None
        if earliest is None or earliest["pan_last4"] != program["required_pan_last4"]:
            raise ApiError("ERR_PROGRAM_INELIGIBLE",
                           "Card fails program eligibility (artifact pan_last4)")

    row = new_common_row({
        "merchant_program_id": program["id"],
        "card_account_id": account["id"],
        "enrolled_at": db.get_clock(),
        "status": "ACTIVE",
    })
    db.merchant_card_programs[row["id"]] = row
    return success_object(row, 201)


@bp.get("/merchant-card-programs/<enrollmentId>")
def get_enrollment(enrollmentId):
    return success_object(resolve_enrollment(enrollmentId), 200)


@bp.get("/merchant-card-programs")
def list_enrollments():
    return list_response(db.merchant_card_programs.values(), filters={
        "merchant_program_id": request.args.get("merchant_program_id"),
        "card_account_id": request.args.get("card_account_id"),
        "status": request.args.get("status"),
    })


@bp.get("/card-accounts/<cardAccountId>/merchant-enrollments")
def list_account_enrollments(cardAccountId):
    resolve_card_account(cardAccountId)
    rows = [e for e in db.merchant_card_programs.values()
            if e["card_account_id"] == cardAccountId]
    return list_response(rows)
