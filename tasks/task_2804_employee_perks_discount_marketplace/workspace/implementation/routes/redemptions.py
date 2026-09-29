"""Redemptions: reservation, screening, verification, fulfilment (PRD 3.7 / 3.8)."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import derive
import response
import support
import validate
from errors import ApiError

bp = Blueprint("redemptions", __name__)

VERIFY_ELIGIBLE_EMPLOYMENT = ("ACTIVE", "LEAVE")


def _privacy_guard(principal):
    """PRD 2.10: evaluated BEFORE existence so a probe cannot leak existence."""
    if principal.is_employer_admin:
        raise ApiError("ERR_PRIVACY_RESTRICTED",
                       "An employer may not read individual redemption data.")


def _posture_of(employer):
    return derive.program_posture(employer) if employer is not None else "SETUP"


def _screening_priors(membership_id, exclude_id=None):
    rows = []
    for row in db.redemptions.values():
        if row["membership_id"] != membership_id:
            continue
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        rows.append(row)
    return rows


@bp.post("/perks/redemptions")
def create_redemption():
    principal = auth.require(auth.EMPLOYEE)
    body = validate.json_body()
    # The Employee's X-User-ID *is* its membership id, so the scope decision is
    # available before the row is looked up (band 1 precedes band 2).
    named = body.get("membership_id") if isinstance(body, dict) else None
    if isinstance(named, str) and named.strip() and named != principal.user_id:
        auth.deny_scope()
    offer = support.resolve_fk(body, "offer_id", "offers")
    membership = support.resolve_fk(body, "membership_id", "memberships")
    data = validate.fields(body, [
        {"name": "offer_id", "type": "str", "required": True},
        {"name": "membership_id", "type": "str", "required": True},
        {"name": "intended_gross_amount_cents", "type": "int", "required": True,
         "min": 100, "max": 5000000},
    ])
    now = clock.now()
    merchant = db.merchants.get(offer["merchant_id"])
    if merchant is None or merchant["status"] in ("SUSPENDED", "TERMINATED"):
        raise ApiError("ERR_MERCHANT_SUSPENDED", "The partner cannot honour redemptions.")
    if membership["status"] != "ELIGIBLE" or membership["employment_status"] == "TERMINATED":
        raise ApiError("ERR_MEMBERSHIP_NOT_ELIGIBLE", "The membership is not eligible.")
    employer = db.employers.get(membership["employer_id"])
    posture = _posture_of(employer)
    if posture == "SETUP":
        raise ApiError("ERR_PROGRAM_NOT_LIVE", "The employer programme is not live.")
    if posture == "FROZEN":
        raise ApiError("ERR_PROGRAM_FROZEN", "The employer programme is frozen.")
    if posture == "RESTRICTED":
        # Only a LIVE programme accepts a NEW reservation, though a RESTRICTED
        # one still permits verification of reservations already held.
        raise ApiError("ERR_PROGRAM_RESTRICTED",
                       "The employer programme is restricted to existing reservations.")
    if membership["region_code"] not in offer["region_codes"]:
        raise ApiError("ERR_REGION_NOT_COVERED",
                       "The member's region is outside the offer's regions.")
    if not (offer["window_start"] <= now < offer["window_end"]):
        raise ApiError("ERR_OFFER_WINDOW_CLOSED", "The offer's redemption window is closed.")
    if not (membership["eligibility_valid_from"] <= now < membership["eligibility_valid_until"]):
        raise ApiError("ERR_MEMBERSHIP_WINDOW_CLOSED",
                       "The membership's eligibility window is closed.")
    if derive.sold_out(offer):
        raise ApiError("ERR_OFFER_SOLD_OUT", "The offer is sold out.")
    held = 0
    for row in db.redemptions.values():
        if row["offer_id"] != offer["id"] or row["membership_id"] != membership["id"]:
            continue
        if row["verification_status"] in ("PENDING", "VERIFIED"):
            held += 1
    if held >= int(offer["per_member_limit"]):
        raise ApiError("ERR_PER_MEMBER_LIMIT",
                       "The member's per-offer allowance is used up.")
    screening = calc.fraud_score(
        "SCREENING", membership, _screening_priors(membership["id"]))
    row = db.insert(db.redemptions, {
        "offer_id": offer["id"],
        "membership_id": membership["id"],
        "employer_id": membership["employer_id"],
        "merchant_id": offer["merchant_id"],
        "statement_id": None,
        "intended_gross_amount_cents": data["intended_gross_amount_cents"],
        "gross_amount_cents": None,
        "discount_amount_cents": None,
        "net_charged_cents": None,
        "commission_amount_cents": None,
        "employer_share_cents": None,
        "provider_net_cents": None,
        "verification_token": support.token(),
        "verification_expires_at": None,
        "verification_status": "PENDING",
        "fulfillment_status": "AWAITING",
        "screening_risk_score": screening,
        "audit_risk_score": None,
        "risk_block_reason": None,
        "verified_at": None,
        "fulfilled_at": None,
        "refunded_at": None,
        "voided_at": None,
        "void_reason": None,
    })
    row["verification_expires_at"] = clock.plus_hours(
        row["created_at"], calc.VERIFICATION_TTL_HOURS)
    # The reserved unit is a derivation over PENDING redemptions, so creating the
    # row is itself the reservation; sold_out follows on the next read.
    return response.created(derive.redemption_json(row, include_token=True))


@bp.get("/perks/redemptions/<row_id>")
def get_redemption(row_id):
    principal = auth.require(auth.EMPLOYEE, auth.MERCHANT, auth.PLATFORM_ADMIN,
                             auth.EMPLOYER_ADMIN)
    _privacy_guard(principal)
    row = support.fetch("redemptions", row_id)
    auth.check_merchant_scope(principal, row["merchant_id"])
    auth.check_membership_scope(principal, row["membership_id"])
    return response.ok(derive.redemption_json(row))


@bp.get("/perks/redemptions")
def list_redemptions():
    principal = auth.require(auth.EMPLOYEE, auth.MERCHANT, auth.PLATFORM_ADMIN,
                             auth.EMPLOYER_ADMIN)
    _privacy_guard(principal)
    filters = {
        "offer_id": support.arg("offer_id"),
        "membership_id": support.arg("membership_id"),
        "employer_id": support.arg("employer_id"),
        "merchant_id": support.arg("merchant_id"),
        "statement_id": support.arg("statement_id"),
        "verification_status": support.arg("verification_status"),
        "fulfillment_status": support.arg("fulfillment_status"),
    }
    rows = []
    for row in db.redemptions.values():
        # Filters never widen visibility.
        if principal.is_merchant and row["merchant_id"] != principal.user_id:
            continue
        if principal.is_employee and row["membership_id"] != principal.user_id:
            continue
        if any(not support.matches(row, key, value) for key, value in filters.items()):
            continue
        rows.append(row)
    return support.paged_sorted(rows, derive.redemption_json)


@bp.post("/perks/redemptions/<row_id>/verify")
def verify_redemption(row_id):
    principal = auth.require(auth.MERCHANT)
    row = support.fetch("redemptions", row_id)
    auth.check_merchant_scope(principal, row["merchant_id"])
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "verification_token", "type": "str", "required": True},
        {"name": "gross_amount_cents", "type": "int", "required": True},
    ])
    if row["verification_status"] != "PENDING":
        raise ApiError("ERR_REDEMPTION_INVALID_STATE",
                       "Only a PENDING redemption can be verified.")
    membership = db.memberships.get(row["membership_id"])
    if (membership is None or membership["status"] != "ELIGIBLE"
            or membership["employment_status"] not in VERIFY_ELIGIBLE_EMPLOYMENT):
        raise ApiError("ERR_MEMBERSHIP_NOT_ELIGIBLE", "The membership is not eligible.")
    employer = db.employers.get(row["employer_id"])
    posture = _posture_of(employer)
    if posture == "SETUP":
        raise ApiError("ERR_PROGRAM_NOT_LIVE", "The employer programme is not live.")
    if posture == "FROZEN":
        raise ApiError("ERR_PROGRAM_FROZEN", "The employer programme is frozen.")
    now = clock.now()
    if not now < row["verification_expires_at"]:
        raise ApiError("ERR_VERIFICATION_EXPIRED",
                       "The verification time-to-live has elapsed.")
    offer = db.offers.get(row["offer_id"])
    gross = data["gross_amount_cents"]
    min_spend = int(offer["min_spend_cents"] or 0) if offer is not None else 0
    if gross < min_spend:
        raise ApiError("ERR_MIN_SPEND_NOT_MET",
                       "The ticket is below the offer's minimum spend.")
    if data["verification_token"] != row["verification_token"]:
        raise ApiError("ERR_VERIFICATION_TOKEN_INVALID",
                       "The echoed verification token does not match.")
    audit = calc.fraud_score(
        "AUDIT", membership, _screening_priors(row["membership_id"], row["id"]),
        gross_amount_cents=gross,
        merchant_failure_score=derive.merchant_failure_score(row["merchant_id"]),
    )
    row["audit_risk_score"] = audit
    if audit >= calc.FRAUD_BLOCK_THRESHOLD:
        # The refusal is persisted: the score that justified it is kept for audit.
        row["verification_status"] = "FAILED"
        row["risk_block_reason"] = "FRAUD_RISK_THRESHOLD"
        db.touch(row)
        raise ApiError("ERR_FRAUD_RISK_BLOCKED",
                       "The audit fraud score is at or above the block threshold.")
    agreement = db.agreements.get(offer["agreement_id"]) if offer is not None else None
    economics = calc.line_economics(
        gross,
        offer["discount_type"],
        offer["discount_value_bps"],
        offer["discount_value_cents"],
        agreement["commission_rate_bps"] if agreement else 0,
        agreement["employer_revenue_share_bps"] if agreement else 0,
        bool(employer["revenue_share_enabled"]) if employer is not None else False,
    )
    row["gross_amount_cents"] = gross
    row["discount_amount_cents"] = economics["discount_amount_cents"]
    row["net_charged_cents"] = economics["net_charged_cents"]
    row["commission_amount_cents"] = economics["commission_amount_cents"]
    row["employer_share_cents"] = economics["employer_share_cents"]
    row["provider_net_cents"] = economics["provider_net_cents"]
    row["verification_status"] = "VERIFIED"
    row["verified_at"] = now
    db.touch(row)
    cascade.write_ledger(
        "COMMISSION_ACCRUAL",
        economics["commission_amount_cents"],
        row["merchant_id"],
        "Commission accrual for redemption %s" % row["id"],
        redemption_id=row["id"],
        employer_id=row["employer_id"],
    )
    if economics["employer_share_cents"] > 0:
        cascade.write_ledger(
            "EMPLOYER_SHARE",
            -economics["employer_share_cents"],
            row["merchant_id"],
            "Employer revenue share for redemption %s" % row["id"],
            redemption_id=row["id"],
            employer_id=row["employer_id"],
        )
    return response.ok(derive.redemption_json(row))


@bp.post("/perks/redemptions/<row_id>/fulfill")
def fulfill_redemption(row_id):
    principal = auth.require(auth.MERCHANT)
    row = support.fetch("redemptions", row_id)
    auth.check_merchant_scope(principal, row["merchant_id"])
    if row["verification_status"] != "VERIFIED" or row["fulfillment_status"] != "AWAITING":
        raise ApiError("ERR_REDEMPTION_INVALID_STATE",
                       "Fulfilment requires a VERIFIED redemption still AWAITING.")
    row["fulfillment_status"] = "FULFILLED"
    row["fulfilled_at"] = clock.now()
    db.touch(row)
    return response.ok(derive.redemption_json(row))


@bp.post("/perks/redemptions/<row_id>/void")
def void_redemption_route(row_id):
    principal = auth.require(auth.EMPLOYEE, auth.PLATFORM_ADMIN)
    row = support.fetch("redemptions", row_id)
    auth.check_membership_scope(principal, row["membership_id"])
    if row["verification_status"] != "PENDING":
        raise ApiError("ERR_REDEMPTION_INVALID_STATE",
                       "Only a PENDING redemption can be cancelled.")
    cascade.void_redemption(row, "MEMBER_CANCELLED")
    return response.ok(derive.redemption_json(row))


@bp.post("/perks/redemptions/<row_id>/disputes")
def file_dispute(row_id):
    principal = auth.require(auth.EMPLOYEE)
    redemption = support.fetch("redemptions", row_id)
    auth.check_membership_scope(principal, redemption["membership_id"])
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "reason", "type": "enum", "required": True,
         "values": ["NOT_HONORED", "WRONG_DISCOUNT", "OFFER_EXPIRED",
                    "OUT_OF_STOCK", "OTHER"]},
        {"name": "description", "type": "str", "required": True,
         "min_len": 1, "max_len": 1000},
    ])
    if (redemption["verification_status"] != "VERIFIED"
            or redemption["fulfillment_status"] not in ("AWAITING", "FULFILLED")):
        raise ApiError("ERR_REDEMPTION_INVALID_STATE",
                       "Only a VERIFIED redemption awaiting or claiming fulfilment "
                       "can be disputed.")
    now = clock.now()
    # The filing window is measured from verification, never from fulfilment.
    if not now < clock.plus_days(redemption["verified_at"], calc.DISPUTE_FILING_DAYS):
        raise ApiError("ERR_DISPUTE_WINDOW_CLOSED", "The dispute filing window has closed.")
    dispute = db.insert(db.disputes, {
        "redemption_id": redemption["id"],
        "raised_by_membership_id": redemption["membership_id"],
        "merchant_id": redemption["merchant_id"],
        "reason": data["reason"],
        "description": data["description"],
        "status": "OPEN",
        "response_note": None,
        "remedy_offered_cents": None,
        "info_request_count": 0,
        "response_deadline_at": clock.plus_hours(now, calc.DISPUTE_RESPONSE_HOURS),
        "outcome_credit_cents": None,
        "default_judged": False,
        "resolved_at": None,
    })
    # An already-fulfilled redemption keeps its fulfilled_at exactly as it was.
    redemption["fulfillment_status"] = "DISPUTED"
    db.touch(redemption)
    return response.created(derive.dispute_json(dispute))


@bp.get("/perks/redemptions/<row_id>/ledger-entries")
def list_redemption_ledger(row_id):
    principal = auth.require(auth.PLATFORM_ADMIN, auth.MERCHANT)
    row = support.fetch("redemptions", row_id)
    auth.check_merchant_scope(principal, row["merchant_id"])
    entry_type = support.arg("entry_type")
    rows = []
    for entry in db.ledger_entries.values():
        if entry["redemption_id"] != row["id"]:
            continue
        if not support.matches(entry, "entry_type", entry_type):
            continue
        rows.append(entry)
    return support.paged_sorted(rows, derive.ledger_json)
