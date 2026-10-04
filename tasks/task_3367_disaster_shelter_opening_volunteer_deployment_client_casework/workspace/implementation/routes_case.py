"""Recovery casework: cases, referrals, assistance requests and card lifecycle."""

import calc
import core
from core import (authenticate, base_row, clock, find, insert, list_response,
                  must_get, ok_object, parse_instant, read_json, rows, serialize,
                  touch, validate_body, validate_enum)
from errors import ApiError
from flask import Blueprint, request

bp = Blueprint("case", __name__)

CASE_ROLES = ["NationalHQAdmin", "RegionalCoordinator", "Caseworker"]
CASE_READ_ROLES = ["NationalHQAdmin", "RegionalCoordinator", "Caseworker", "FinanceOfficer"]
ASSISTANCE_TYPES = ("HOUSING", "FOOD", "MEDICAL", "TRANSPORTATION", "UTILITY",
                    "FUNERAL", "OCCUPATIONAL")
ELIGIBILITY_STATES = ("PENDING", "VERIFIED", "INELIGIBLE", "EXPIRED")
DECISIONS = ("ACCEPT", "DECLINE", "REQUEST_INFORMATION", "COMPLETE", "CANCEL")
TERMINAL_ASSISTANCE = ("DENIED", "DISBURSED", "REVERSED")


def _append_ledger(operation_id, pool_id, category, amount_cents, entry_type):
    record = base_row()
    record.update({
        "disaster_relief_operation_id": operation_id,
        "fund_pool_id": pool_id,
        "cost_category": category,
        "amount_cents": int(amount_cents),
        "entry_type": entry_type,
        "incurred_at": core.now_iso(),
    })
    insert("cost_ledger_entries", record)
    return record


def _refresh_operation_of_case(case):
    operation = find("disaster_relief_operations", case["disaster_relief_operation_id"])
    if operation is not None:
        calc.refresh_operation(operation)


# ------------------------------------------------------------------- cases


@bp.post("/api/v1/client-cases")
def create_case():
    authenticate(CASE_ROLES)
    body = read_json()
    validate_body(body, required={
        "client_id": str,
        "disaster_relief_operation_id": str,
        "assigned_caseworker_id": str,
    })
    client = must_get("clients", body["client_id"])
    operation = must_get("disaster_relief_operations", body["disaster_relief_operation_id"])
    record = base_row()
    record.update({
        "client_id": client["id"],
        "disaster_relief_operation_id": operation["id"],
        "assigned_caseworker_id": body["assigned_caseworker_id"],
        "status": "INTAKE",
        "eligibility_status": "PENDING",
        "eligibility_verified_by_user_id": None,
        "recovery_plan_revision": 1,
        "recovery_plan_summary": None,
        "entitlement_cents": 0,
        "case_closure_eligible_at": None,
    })
    insert("client_cases", record)
    calc.refresh_case_entitlement(record)
    return ok_object(serialize(record), 201)


@bp.get("/api/v1/client-cases/<case_id>")
def read_case(case_id):
    authenticate(CASE_READ_ROLES)
    case = must_get("client_cases", case_id)
    calc.refresh_case_entitlement(case)
    calc.refresh_case_closure(case)
    return ok_object(serialize(case))


@bp.get("/api/v1/client-cases")
def list_cases():
    authenticate(CASE_READ_ROLES)
    cases = rows("client_cases")
    client_id = request.args.get("client_id")
    operation_id = request.args.get("disaster_relief_operation_id")
    if client_id:
        cases = [c for c in cases if c["client_id"] == client_id]
    if operation_id:
        cases = [c for c in cases if c["disaster_relief_operation_id"] == operation_id]
    return list_response(cases)


@bp.get("/api/v1/client-cases/<case_id>/referrals")
def list_case_referrals(case_id):
    authenticate(["NationalHQAdmin", "RegionalCoordinator", "Caseworker"])
    case = must_get("client_cases", case_id)
    referrals = [r for r in rows("referrals") if r["client_case_id"] == case["id"]]
    return list_response(referrals)


@bp.post("/api/v1/client-cases/<case_id>/verify-eligibility")
def verify_eligibility(case_id):
    user_id, _role = authenticate(["Caseworker"])
    body = read_json()
    validate_body(body, required={"eligibility_status": str})
    validate_enum("eligibility_status", body["eligibility_status"], ELIGIBILITY_STATES)
    case = must_get("client_cases", case_id)
    if case["assigned_caseworker_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "the case belongs to another caseworker")
    if case["status"] == "INTAKE":
        case["status"] = "ELIGIBILITY_REVIEW"
        case["eligibility_status"] = body["eligibility_status"]
    elif case["status"] == "CLOSED":
        case["status"] = "REOPENED"
        case["eligibility_status"] = "PENDING"
    elif case["status"] == "REOPENED":
        # a reopened case settles its eligibility again before a new plan
        case["eligibility_status"] = body["eligibility_status"]
    else:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "the case does not admit an eligibility verification")
    case["eligibility_verified_by_user_id"] = user_id
    touch(case)
    calc.refresh_case_entitlement(case)
    return ok_object(serialize(case))


@bp.post("/api/v1/client-cases/<case_id>/recovery-plans")
def write_recovery_plan(case_id):
    authenticate(["Caseworker"])
    body = read_json()
    validate_body(body, required={
        "expected_client_case_version": int,
        "recovery_plan_summary": str,
    })
    case = must_get("client_cases", case_id)
    if body["expected_client_case_version"] != case["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "the client case version is stale")
    if case["status"] not in ("ELIGIBILITY_REVIEW", "RECOVERY_PLANNING", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE", 409, "the case is not in recovery planning")
    if case["eligibility_status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "eligibility has not been verified")
    if case["status"] in ("RECOVERY_PLANNING", "REOPENED"):
        case["recovery_plan_revision"] = int(case["recovery_plan_revision"]) + 1
    else:
        case["recovery_plan_revision"] = 1
    case["recovery_plan_summary"] = body["recovery_plan_summary"]
    case["status"] = "RECOVERY_PLANNING"
    touch(case)
    calc.refresh_case_entitlement(case)
    return ok_object(serialize(case), 201)


# ---------------------------------------------------------------- referrals


@bp.post("/api/v1/client-cases/<case_id>/referrals")
def create_referral(case_id):
    authenticate(["Caseworker"])
    body = read_json()
    validate_body(body, required={
        "agency_code": str,
        "assistance_type": str,
        "estimated_value_cents": int,
    })
    validate_enum("assistance_type", body["assistance_type"], ASSISTANCE_TYPES)
    if body["estimated_value_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "estimated_value_cents must be >= 0")
    case = must_get("client_cases", case_id)
    # PRD 3.6 places no case-status precondition on raising a referral: the raise
    # is guarded only by agency authorization and the live-duplicate rule.
    client = must_get("clients", case["client_id"])
    region = must_get("regions", client["region_id"])
    if body["agency_code"] not in (region.get("authorized_agency_codes") or []):
        raise ApiError("ERR_AGENCY_NOT_AUTHORIZED", 409,
                       "the agency is not authorized for the client's region")
    existing = [r for r in rows("referrals")
                if r["client_case_id"] == case["id"] and r["status"] != "CANCELLED"]
    for referral in existing:
        if (referral["agency_code"] == body["agency_code"]
                and referral["assistance_type"] == body["assistance_type"]):
            raise ApiError("ERR_DUPLICATION_BLOCKED", 409,
                           "a live referral to this agency already exists")
    overlap = any(r["assistance_type"] == body["assistance_type"] for r in existing)
    record = base_row()
    record.update({
        "client_case_id": case["id"],
        "agency_code": body["agency_code"],
        "assistance_type": body["assistance_type"],
        "estimated_value_cents": body["estimated_value_cents"],
        "status": "SUBMITTED",
        "duplication_check_result": "PARTIAL_OVERLAP" if overlap else "CLEAR",
        "_resolved_at": None,
    })
    insert("referrals", record)
    case["status"] = "REFERRED"
    touch(case)
    return ok_object(serialize(record), 201)


@bp.post("/api/v1/referrals/<referral_id>/resolve")
def resolve_referral(referral_id):
    authenticate(["Caseworker"])
    body = read_json()
    validate_body(body, required={"decision": str})
    validate_enum("decision", body["decision"], DECISIONS)
    referral = must_get("referrals", referral_id)
    decision = body["decision"]
    if referral["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the referral is terminal")
    status = referral["status"]
    if decision == "ACCEPT":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409, "the referral is not submitted")
        if referral["duplication_check_result"] == "DUPLICATE_BLOCKED":
            raise ApiError("ERR_INVALID_STATE", 409, "the referral is blocked as a duplicate")
        referral["status"] = "ACCEPTED"
    elif decision == "DECLINE":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409, "the referral is not submitted")
        referral["status"] = "DECLINED"
        referral["_resolved_at"] = core.now_iso()
    elif decision == "REQUEST_INFORMATION":
        if status != "ACCEPTED":
            raise ApiError("ERR_INVALID_STATE", 409, "the referral is not accepted")
        referral["status"] = "SUBMITTED"
    elif decision == "COMPLETE":
        if status != "ACCEPTED":
            raise ApiError("ERR_INVALID_STATE", 409, "the referral is not accepted")
        referral["status"] = "COMPLETED"
        referral["_resolved_at"] = core.now_iso()
    else:
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409, "the referral is not submitted")
        referral["status"] = "CANCELLED"
        referral["_resolved_at"] = core.now_iso()
    touch(referral)
    case = must_get("client_cases", referral["client_case_id"])
    core.apply(case, {
        "status": calc.case_status_after_referrals(case),
        "case_closure_eligible_at": calc.case_closure_eligible_at(case),
    })
    return ok_object(serialize(referral))


# ------------------------------------------------------- assistance requests


@bp.post("/api/v1/client-cases/<case_id>/assistance-requests")
def create_assistance_request(case_id):
    authenticate(["Caseworker", "FinanceOfficer"])
    body = read_json()
    validate_body(body, required={
        "fund_pool_id": str,
        "assistance_type": str,
        "requested_amount_cents": int,
    })
    validate_enum("assistance_type", body["assistance_type"], ASSISTANCE_TYPES)
    case = must_get("client_cases", case_id)
    pool = must_get("fund_pools", body["fund_pool_id"])
    if body["requested_amount_cents"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "requested_amount_cents must be >= 1")
    offset = calc.duplication_offset(case["id"], body["assistance_type"])
    record = base_row()
    record.update({
        "client_case_id": case["id"],
        "fund_pool_id": pool["id"],
        "assistance_type": body["assistance_type"],
        "requested_amount_cents": body["requested_amount_cents"],
        "duplication_offset_cents": offset,
        "approved_amount_cents": calc.assistance_award(body["requested_amount_cents"], offset),
        "status": "SUBMITTED",
        "approved_by_user_id": None,
        "card_number_masked": None,
        "card_status": "NOT_ISSUED",
        "redemption_deadline_at": None,
        "issued_by_user_id": None,
        "_issued_at": None,
    })
    insert("assistance_requests", record)
    return ok_object(serialize(record), 201)


@bp.get("/api/v1/assistance-requests/<request_id>")
def read_assistance_request(request_id):
    authenticate(["NationalHQAdmin", "FinanceOfficer", "Caseworker"])
    return ok_object(serialize(must_get("assistance_requests", request_id)))


@bp.get("/api/v1/assistance-requests")
def list_assistance_requests():
    authenticate(["NationalHQAdmin", "FinanceOfficer", "Caseworker"])
    requests = rows("assistance_requests")
    case_id = request.args.get("client_case_id")
    pool_id = request.args.get("fund_pool_id")
    if case_id:
        requests = [a for a in requests if a["client_case_id"] == case_id]
    if pool_id:
        requests = [a for a in requests if a["fund_pool_id"] == pool_id]
    return list_response(requests)


@bp.post("/api/v1/assistance-requests/<request_id>/approve")
def approve_assistance_request(request_id):
    user_id, _role = authenticate(["FinanceOfficer"])
    validate_body(read_json(), required={})
    assistance = must_get("assistance_requests", request_id)
    if assistance["status"] in TERMINAL_ASSISTANCE:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the assistance request is terminal")
    case = must_get("client_cases", assistance["client_case_id"])
    if assistance["status"] == "SUBMITTED":
        if case["eligibility_status"] != "VERIFIED":
            raise ApiError("ERR_INVALID_STATE", 409, "the case is not eligible for assistance")
        offset = calc.duplication_offset(case["id"], assistance["assistance_type"])
        assistance["duplication_offset_cents"] = offset
        assistance["approved_amount_cents"] = calc.assistance_award(
            assistance["requested_amount_cents"], offset)
        assistance["status"] = "ELIGIBILITY_VERIFIED"
        touch(assistance)
        return ok_object(serialize(assistance))
    if assistance["status"] != "ELIGIBILITY_VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "the request cannot be approved")
    offset = calc.duplication_offset(case["id"], assistance["assistance_type"])
    award = calc.assistance_award(assistance["requested_amount_cents"], offset)
    assistance["duplication_offset_cents"] = offset
    assistance["approved_amount_cents"] = award
    if award == 0:
        assistance["status"] = "DENIED"
        touch(assistance)
        return ok_object(serialize(assistance))
    if award < calc.MIN_ASSISTANCE_CENTS:
        raise ApiError("ERR_ASSISTANCE_BELOW_MINIMUM", 409,
                       "the award is below the minimum assistance amount")
    pool = must_get("fund_pools", assistance["fund_pool_id"])
    client = must_get("clients", case["client_id"])
    if int(pool["remaining_cents"]) < award:
        raise ApiError("ERR_INSUFFICIENT_FUNDS", 409, "the pool cannot cover the award")
    if not calc.restriction_compatible(pool, assistance["assistance_type"], client["region_id"]):
        raise ApiError("ERR_POOL_RESTRICTION_MISMATCH", 409,
                       "the pool restriction forbids this award")
    assistance["approved_by_user_id"] = user_id
    assistance["status"] = "APPROVED"
    touch(assistance)
    calc.refresh_pool(pool)
    _refresh_operation_of_case(case)
    return ok_object(serialize(assistance))


@bp.post("/api/v1/assistance-requests/<request_id>/issue-card")
def issue_card(request_id):
    user_id, _role = authenticate(["FinanceOfficer"])
    validate_body(read_json(), required={})
    assistance = must_get("assistance_requests", request_id)
    if assistance["status"] in TERMINAL_ASSISTANCE:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the assistance request is terminal")
    if assistance["card_status"] != "NOT_ISSUED":
        raise ApiError("ERR_CARD_ALREADY_ISSUED", 409, "the card has already been issued")
    if assistance["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "the award has not been approved")
    if user_id == assistance.get("approved_by_user_id"):
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "the approver may not issue the card")
    case = must_get("client_cases", assistance["client_case_id"])
    window = calc.redemption_window_days(case)
    assistance["card_number_masked"] = "****-****-****-%04d" % (
        abs(hash(assistance["id"])) % 10000)
    assistance["card_status"] = "ISSUED"
    assistance["issued_by_user_id"] = user_id
    assistance["_issued_at"] = core.now_iso()
    assistance["redemption_deadline_at"] = core.plus_days_iso(window)
    assistance["status"] = "CARD_ISSUED"
    touch(assistance)
    pool = must_get("fund_pools", assistance["fund_pool_id"])
    calc.refresh_pool(pool)
    _refresh_operation_of_case(case)
    return ok_object(serialize(assistance))


@bp.post("/api/v1/assistance-requests/<request_id>/redeem-card")
def redeem_card(request_id):
    authenticate(["FinanceOfficer"])
    validate_body(read_json(), required={})
    assistance = must_get("assistance_requests", request_id)
    if assistance["status"] in TERMINAL_ASSISTANCE:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the assistance request is terminal")
    if assistance["status"] != "CARD_ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "no card has been issued")
    deadline = assistance.get("redemption_deadline_at")
    if deadline and clock.now >= parse_instant(deadline):
        raise ApiError("ERR_INVALID_STATE", 409, "the redemption window has closed")
    case = must_get("client_cases", assistance["client_case_id"])
    assistance["card_status"] = "REDEEMED"
    assistance["status"] = "DISBURSED"
    touch(assistance)
    _append_ledger(case["disaster_relief_operation_id"], assistance["fund_pool_id"],
                   "FINANCIAL_ASSISTANCE", assistance["approved_amount_cents"], "CHARGE")
    pool = must_get("fund_pools", assistance["fund_pool_id"])
    calc.refresh_pool(pool)
    _refresh_operation_of_case(case)
    calc.refresh_case_closure(case)
    return ok_object(serialize(assistance))


@bp.post("/api/v1/assistance-requests/<request_id>/reverse")
def reverse_assistance(request_id):
    authenticate(["FinanceOfficer"])
    validate_body(read_json(), required={})
    assistance = must_get("assistance_requests", request_id)
    if assistance["status"] in TERMINAL_ASSISTANCE and assistance["status"] != "DISBURSED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the assistance request is terminal")
    if assistance["status"] != "DISBURSED":
        raise ApiError("ERR_INVALID_STATE", 409, "only a disbursed award can be reversed")
    case = must_get("client_cases", assistance["client_case_id"])
    assistance["status"] = "REVERSED"
    assistance["card_status"] = "VOIDED"
    touch(assistance)
    pool = must_get("fund_pools", assistance["fund_pool_id"])
    calc.refresh_pool(pool)
    _append_ledger(case["disaster_relief_operation_id"], assistance["fund_pool_id"],
                   "FINANCIAL_ASSISTANCE", assistance["approved_amount_cents"], "REVERSAL")
    _refresh_operation_of_case(case)
    calc.refresh_case_closure(case)
    return ok_object(serialize(assistance))
