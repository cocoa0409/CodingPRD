"""The financial dimension: coverage, prior authorization, notices, signatures."""
from datetime import timedelta

from flask import Blueprint

from calc import abn_cash_quote, same_or_similar_lookback
from common import (authorize, body_json, enum_arg, fail, need_enum, need_int,
                    need_rate, now, opt_enum, opt_int, opt_str, paginate,
                    respond_list, respond_object)
from store import (ABN_OPTIONS, ABN_REASONS, ABN_SIGNERS, ABN_STATUSES,
                   DECISIONS, abn_notice_json, db, encounter_notices,
                   encounter_prior_auth, encounter_verifications,
                   find_par_level, insert, lookup, prior_auth_json,
                   sort_created, stamp, touch, verification_json)

bp = Blueprint("finance", __name__)

FINANCE_READ_ROLES = ["PracticeAdmin", "ComplianceOfficer", "InsuranceCoordinator"]

CLOSED_CLINICAL = ("DELIVERED", "RETURN_PENDING", "RETURNED", "VOIDED")
VERIFIABLE_FINANCIAL = ("UNVERIFIED", "NON_COVERED")


# ------------------------------------------------------- coverage verifications

@bp.post("/dme/encounters/<encounter_id>/coverage-verifications")
def create_verification(encounter_id):
    authorize(["InsuranceCoordinator"])
    body = body_json()
    covered = body.get("covered")
    if covered is None or not isinstance(covered, bool):
        fail("ERR_INVALID_REQUEST", "covered is required and must be a boolean.")
    deductible = need_int(body, "deductible_remaining_cents", 0)
    coinsurance = need_rate(body, "coinsurance_pct", 0, 1, max_places=4)
    valid_for_days = need_int(body, "valid_for_days", 1, 90)
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    product = db["products"].get(encounter["product_id"])
    # Validation 20 does not list this endpoint: a closed encounter and a
    # non-declared financial origin both surface as ERR_INVALID_FINANCIAL_STATE.
    if encounter["clinical_status"] in CLOSED_CLINICAL:
        fail("ERR_INVALID_FINANCIAL_STATE")
    if encounter["financial_status"] not in VERIFIABLE_FINANCIAL:
        fail("ERR_INVALID_FINANCIAL_STATE")

    conflict, prior_id, prior_on, months = same_or_similar_lookback(encounter, product)
    if covered and conflict:
        fail("ERR_SAME_OR_SIMILAR_CONFLICT")

    existing = encounter_verifications(encounter["id"])
    next_seq = (existing[-1]["verification_seq"] + 1) if existing else 1
    verified_at = now()
    row = stamp({
        "encounter_id": encounter["id"],
        "verification_seq": next_seq,
        "covered": covered,
        "deductible_remaining_cents": deductible,
        # echoed as the JSON number it arrived as; Decimal only for arithmetic
        "coinsurance_pct": body["coinsurance_pct"],
        "valid_for_days": valid_for_days,
        "allowed_amount_cents_snapshot": product["allowed_amount_cents"],
        "same_or_similar_conflict": conflict,
        "prior_delivered_encounter_id": prior_id,
        "prior_delivered_on": prior_on,
        "months_since_prior_delivery": months,
        "verified_at": verified_at,
        "expires_at": verified_at + timedelta(days=valid_for_days),
    })
    insert("verifications", row)
    encounter["financial_status"] = "VERIFIED" if covered else "NON_COVERED"
    touch(encounter)
    return respond_object(verification_json(row), 201)


@bp.get("/dme/encounters/<encounter_id>/coverage-verifications")
def list_verifications(encounter_id):
    authorize(FINANCE_READ_ROLES)
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    rows = encounter_verifications(encounter["id"])
    rows.reverse()  # newest sequence first
    page, pagination = paginate(rows)
    return respond_list([verification_json(r) for r in page], pagination, 200)


# ------------------------------------------------------------- prior authorization

@bp.post("/dme/encounters/<encounter_id>/prior-auth-requests")
def create_prior_auth(encounter_id):
    authorize(["InsuranceCoordinator"])
    body = body_json()
    requested_units = need_int(body, "requested_units", 1, 20)
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    product = db["products"].get(encounter["product_id"])
    if encounter["financial_status"] != "VERIFIED":
        fail("ERR_INVALID_FINANCIAL_STATE")
    if encounter_prior_auth(encounter["id"]) is not None:
        fail("ERR_PRIOR_AUTH_ALREADY_EXISTS")
    if not product["requires_prior_auth"]:
        fail("ERR_PRIOR_AUTH_ALREADY_EXISTS")
    row = stamp({
        "encounter_id": encounter["id"],
        "requested_units": requested_units,
        "status": "SUBMITTED",
        "approved_units": None,
        "auth_number": None,
        "appeal_round": 0,
        "decision_at": None,
        "expires_at": None,
    })
    insert("prior_auths", row)
    encounter["financial_status"] = "AUTH_PENDING"
    touch(encounter)
    return respond_object(prior_auth_json(row), 201)


@bp.get("/dme/encounters/<encounter_id>/prior-auth-requests")
def list_prior_auths(encounter_id):
    authorize(FINANCE_READ_ROLES)
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    rows = sort_created([r for r in db["prior_auths"].values()
                         if r["encounter_id"] == encounter["id"]])
    page, pagination = paginate(rows)
    return respond_list([prior_auth_json(r) for r in page], pagination, 200)


@bp.post("/dme/prior-auth-requests/<request_id>/decision")
def decide_prior_auth(request_id):
    authorize(["InsuranceCoordinator"])
    body = body_json()
    decision = need_enum(body, "decision", DECISIONS)
    approved_units = opt_int(body, "approved_units", 0)
    auth_number = opt_str(body, "auth_number")
    valid_for_days = opt_int(body, "valid_for_days", 1)
    row = lookup("prior_auths", request_id, "ERR_PRIOR_AUTH_NOT_FOUND")
    encounter = db["encounters"].get(row["encounter_id"])
    if row["status"] not in ("SUBMITTED", "PENDED"):
        fail("ERR_INVALID_PRIOR_AUTH_STATE")
    # PENDED is a self-loop that is only declared out of SUBMITTED.
    if decision == "PENDED" and row["status"] != "SUBMITTED":
        fail("ERR_INVALID_PRIOR_AUTH_STATE")
    if decision == "APPROVED":
        if approved_units is None:
            approved_units = row["requested_units"]
        if approved_units < 1 or approved_units > row["requested_units"]:
            fail("ERR_APPROVED_UNITS_EXCEED_REQUEST")

    decision_at = now()
    row["decision_at"] = decision_at
    row["status"] = decision
    if decision == "APPROVED":
        row["approved_units"] = approved_units
        row["auth_number"] = auth_number
        row["expires_at"] = (decision_at + timedelta(days=valid_for_days)
                             if valid_for_days is not None else None)
    touch(row)
    if decision in ("APPROVED", "DENIED") and encounter is not None:
        encounter["financial_status"] = ("AUTH_APPROVED" if decision == "APPROVED"
                                        else "AUTH_DENIED")
        touch(encounter)
    return respond_object(prior_auth_json(row), 201)


@bp.post("/dme/prior-auth-requests/<request_id>/appeal")
def appeal_prior_auth(request_id):
    authorize(["InsuranceCoordinator"])
    body = body_json()
    opt_str(body, "appeal_note")  # accepted, recorded nowhere on the entity
    row = lookup("prior_auths", request_id, "ERR_PRIOR_AUTH_NOT_FOUND")
    encounter = db["encounters"].get(row["encounter_id"])
    if row["status"] not in ("PENDED", "DENIED"):
        fail("ERR_INVALID_PRIOR_AUTH_STATE")
    if row["appeal_round"] >= 2:
        fail("ERR_APPEAL_LIMIT_REACHED")
    row["status"] = "SUBMITTED"
    row["appeal_round"] += 1
    row["decision_at"] = None
    touch(row)
    if encounter is not None:
        encounter["financial_status"] = "AUTH_PENDING"
        touch(encounter)
    return respond_object(prior_auth_json(row), 201)


# --------------------------------------------------- advance beneficiary notices

def _issuable(encounter, reason, prior_auth):
    """Is issuance a declared transition out of the encounter's financial state?"""
    financial = encounter["financial_status"]
    if financial in ("NON_COVERED", "AUTH_DENIED"):
        return True
    if financial == "AUTH_APPROVED":
        approved = prior_auth["approved_units"] if prior_auth is not None else None
        return (reason == "UNITS_EXCEED_AUTH" and approved is not None
                and encounter["quantity"] > approved)
    if financial == "ABN_ISSUED":
        # the self-loop re-issues a corrected notice on an open encounter only
        return encounter["clinical_status"] not in CLOSED_CLINICAL
    return False


@bp.post("/dme/encounters/<encounter_id>/abn-notices")
def issue_abn_notice(encounter_id):
    user_id, _ = authorize(["InsuranceCoordinator"])
    body = body_json()
    reason = need_enum(body, "reason_non_covered", ABN_REASONS)
    expected_version = need_int(body, "expected_encounter_version", 0)
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    product = db["products"].get(encounter["product_id"])
    prior_auth = encounter_prior_auth(encounter["id"])
    if not _issuable(encounter, reason, prior_auth):
        fail("ERR_INVALID_FINANCIAL_STATE")
    if expected_version != encounter["version"]:
        fail("ERR_STALE_ENCOUNTER_VERSION")

    existing = encounter_notices(encounter["id"])
    for notice in existing:
        if notice["status"] == "ISSUED":
            notice["status"] = "VOIDED"
            touch(notice)
    next_seq = (existing[-1]["notice_seq"] + 1) if existing else 1
    approved_units = prior_auth["approved_units"] if prior_auth is not None else None
    quote = abn_cash_quote(encounter, product, reason, approved_units)
    row = stamp({
        "encounter_id": encounter["id"],
        "notice_seq": next_seq,
        "reason_non_covered": reason,
        "status": "ISSUED",
        "option_selected": None,
        "signed_by": None,
        "patient_signed_at": None,
        "witness_user_id": user_id,
        "unit_net_price_cents": quote["unit_net_price_cents"],
        "estimated_subtotal_cents": quote["estimated_subtotal_cents"],
        "dispensing_fee_cents": quote["dispensing_fee_cents"],
        "estimated_cost_cents": quote["estimated_cost_cents"],
    })
    insert("abn_notices", row)
    encounter["financial_status"] = "ABN_ISSUED"
    touch(encounter)
    return respond_object(abn_notice_json(row), 201)


@bp.get("/dme/encounters/<encounter_id>/abn-notices")
def list_abn_notices(encounter_id):
    authorize(FINANCE_READ_ROLES)
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    rows = encounter_notices(encounter["id"])
    status = enum_arg("status", ABN_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.reverse()  # newest sequence first
    page, pagination = paginate(rows)
    return respond_list([abn_notice_json(r) for r in page], pagination, 200)


VOIDABLE_CLINICAL = ("DRAFT", "DOCUMENTED", "RESERVED")


@bp.post("/dme/abn-notices/<notice_id>/signature")
def sign_abn_notice(notice_id):
    authorize(["InsuranceCoordinator"])
    body = body_json()
    signed_by = opt_enum(body, "signed_by", ABN_SIGNERS)
    option_selected = opt_enum(body, "option_selected", ABN_OPTIONS)
    notice = lookup("abn_notices", notice_id, "ERR_ABN_NOTICE_NOT_FOUND")
    encounter = db["encounters"].get(notice["encounter_id"])
    # Priority 23 precedes priority 49: a VOIDED notice is diagnosed by state.
    if notice["status"] != "ISSUED":
        fail("ERR_INVALID_ABN_STATE")
    siblings = encounter_notices(notice["encounter_id"])
    if siblings and siblings[-1]["id"] != notice["id"]:
        fail("ERR_ABN_SUPERSEDED")

    clock = now()
    if option_selected is None:
        # A declined signature leaves the financial dimension at ABN_ISSUED so a
        # replacement notice can be issued; the encounter is not touched at all.
        notice["status"] = "DECLINED"
        notice["signed_by"] = signed_by
        notice["patient_signed_at"] = clock
        touch(notice)
        return respond_object(abn_notice_json(notice), 201)

    notice["status"] = "SIGNED"
    notice["option_selected"] = option_selected
    notice["signed_by"] = signed_by
    notice["patient_signed_at"] = clock
    touch(notice)
    if encounter is not None:
        if option_selected == "OPTION_3":
            encounter["financial_status"] = "WRITTEN_OFF"
            encounter["patient_responsibility_cents"] = 0
            encounter["billable_amount_cents"] = 0
            if encounter["clinical_status"] in VOIDABLE_CLINICAL:
                if encounter["clinical_status"] == "RESERVED":
                    shelf = find_par_level(encounter["clinic_id"],
                                           encounter["product_id"])
                    if shelf is not None:
                        shelf["reserved_qty"] -= encounter["quantity"]
                        if shelf["reserved_qty"] < 0:
                            shelf["reserved_qty"] = 0
                        # stock_posture untouched: on_hand_qty never moved
                        touch(shelf)
                encounter["clinical_status"] = "VOIDED"
        else:
            encounter["financial_status"] = "SELF_PAY"
        touch(encounter)
    return respond_object(abn_notice_json(notice), 201)
