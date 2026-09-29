"""Referral intake, consent-request issuance and the compliance view (PRD 3.3, 3.4)."""
from flask import Blueprint

from db import base_row, clock_date, db, fmt_date, now_utc, touch
from errors import ApiError
from middleware import endpoint
from response import object_response
from routes.common import matches, paged
from services import calc, derive, rules
from validation import (
    CONSENT_STATUS,
    ELIGIBILITY_PATHWAY,
    INTAKE_STATUS,
    INTERPRETER_MODALITY,
    NOTICE_DELIVERY_METHOD,
    NPI_RE,
    REFERRAL_SOURCE,
    bad,
    body,
    opt_enum,
    opt_id,
    opt_str,
    q_enum,
    q_str,
    req_enum,
    req_id,
    req_lang,
)

bp = Blueprint("referrals", __name__)

READ_ROLES = (
    "ChildFindCoordinator",
    "EvaluationChair",
    "PlacementAdministrator",
    "Parent",
    "DistrictAdmin",
)


def _npi(data):
    value = opt_str(data, "referring_provider_npi")
    if value is not None and not NPI_RE.match(value):
        bad("Field 'referring_provider_npi' must be exactly ten digits")
    return value


@bp.post("/referrals")
@endpoint("ChildFindCoordinator", "DistrictAdmin")
def create_referral():
    data = body()
    child_id = req_id(data, "child_id")
    source = req_enum(data, "source", REFERRAL_SOURCE)
    npi = _npi(data)
    slot_id = opt_id(data, "originating_screening_slot_id")
    if source == "PEDIATRICIAN" and npi is None:
        bad("Field 'referring_provider_npi' is required when source is PEDIATRICIAN")

    # rung 5: body foreign keys in declared input order.
    child = rules.fetch("children", child_id)
    rules.fetch_optional_fk("screening_slots", slot_id)

    # rung 17: a manual intake outside 33..71 completed months is refused outright.
    age_months, pathway = calc.referral_age_and_pathway(
        child["date_of_birth"], now_utc(), child["part_c_enrolled"]
    )
    if pathway == "AGE_INELIGIBLE":
        raise ApiError(
            "ERR_AGE_INELIGIBLE",
            "Child is %d completed months old at receipt, outside the 33-71 month preschool span"
            % age_months,
        )

    row = rules.create_referral(child, source, npi, slot_id)
    return object_response(derive.referral_out(row), 201)


@bp.post("/referrals/<referral_id>/consent-requests")
@endpoint("ChildFindCoordinator", "DistrictAdmin")
def issue_consent_request(referral_id):
    data = body()
    notice_language_code = req_lang(data, "notice_language_code")
    notice_delivery_method = req_enum(data, "notice_delivery_method", NOTICE_DELIVERY_METHOD)
    interpreter_id = opt_id(data, "interpreter_provider_id")
    interpreter_modality = opt_enum(data, "interpreter_modality", INTERPRETER_MODALITY)
    if interpreter_id is not None and interpreter_modality is None:
        bad("Field 'interpreter_modality' is required when an interpreter_provider_id is named")

    referral = rules.fetch("referrals", referral_id)                     # rung 4
    interpreter = rules.fetch_optional_fk("providers", interpreter_id)   # rung 5

    # rung 11, carve-out A: a live PENDING/GRANTED notice pre-empts the own-state rule.
    live = [
        c
        for c in derive.consents_of_referral(referral_id)
        if c["kind"] == "EVALUATION_CONSENT" and c["decision"] in ("PENDING", "GRANTED")
    ]
    if live:
        raise ApiError(
            "ERR_CONSENT_ALREADY_REQUESTED",
            "Referral already holds a live evaluation-consent record",
        )
    # The pathway can never be AGE_INELIGIBLE with intake RECEIVED: a manual intake is
    # refused at rung 17 and a screening-generated one is DECLINED on creation, so the
    # own-state rule below is the only reachable refusal.
    if referral["intake_status"] != "RECEIVED":
        raise ApiError(
            "ERR_INVALID_REFERRAL_STATE",
            "Referral intake_status is %s; a notice may only be issued from RECEIVED"
            % referral["intake_status"],
        )

    child = db.children[referral["child_id"]]
    rules.require_language_access(child, notice_language_code, interpreter)   # rung 14

    # rung 16: the chair of this referral's case may not be the interpreter of record.
    if interpreter is not None:
        for case in derive.cases_of_referral(referral_id):
            if case["chair_provider_id"] == interpreter["id"]:
                raise ApiError(
                    "ERR_SEGREGATION_OF_DUTIES",
                    "The case chair may not be the interpreter of record on the same case",
                )
    if interpreter is not None:
        rules.require_provider_active(interpreter)          # rung 18
        rules.require_interpreter_available(interpreter)    # rung 38

    row = base_row()
    row.update(
        {
            "referral_id": referral_id,
            "kind": "EVALUATION_CONSENT",
            "requested_at": now_utc(),
            "decision": "PENDING",
            "decided_at": None,
            "notice_language_code": notice_language_code,
            "notice_delivery_method": notice_delivery_method,
            "interpreter_provider_id": interpreter_id,
            "interpreter_modality": interpreter_modality,
            "service_plan_id": None,
        }
    )
    db.consent_records[row["id"]] = row
    referral["intake_status"] = "CONSENT_PENDING"
    referral["consent_status"] = "REQUESTED"
    touch(referral)
    return object_response(derive.consent_out(row), 201)


@bp.get("/referrals/<referral_id>")
@endpoint(*READ_ROLES)
def get_referral(referral_id):
    row = rules.fetch("referrals", referral_id)
    rules.require_guardian(row["child_id"])
    return object_response(derive.referral_out(row))


@bp.get("/referrals")
@endpoint(*READ_ROLES)
def list_referrals():
    child_id = q_str("child_id")
    slot_id = q_str("originating_screening_slot_id")
    superseded_by = q_str("superseded_by_referral_id")
    source = q_enum("source", REFERRAL_SOURCE)
    pathway = q_enum("eligibility_pathway", ELIGIBILITY_PATHWAY)
    consent_status = q_enum("consent_status", CONSENT_STATUS)
    intake_status = q_enum("intake_status", INTAKE_STATUS)
    rows = [
        r
        for r in db.referrals.values()
        if matches(r, "child_id", child_id)
        and matches(r, "originating_screening_slot_id", slot_id)
        and matches(r, "superseded_by_referral_id", superseded_by)
        and matches(r, "source", source)
        and matches(r, "eligibility_pathway", pathway)
        and matches(r, "consent_status", consent_status)
        and matches(r, "intake_status", intake_status)
    ]
    return paged(rows, derive.referral_out)


@bp.get("/referrals/<referral_id>/timeline")
@endpoint(*READ_ROLES)
def referral_timeline(referral_id):
    referral = rules.fetch("referrals", referral_id)
    rules.require_guardian(referral["child_id"])
    child = db.children.get(referral["child_id"])
    due = derive.referral_due_date(referral)
    granted_at = referral.get("consent_granted_at")

    # The posture of PRD 3.5, read through the referral's own case when it has one.
    cases = derive.cases_of_referral(referral_id)
    case = cases[-1] if cases else None
    if due is None:
        compliance = None
        remaining = None
    else:
        status = case["status"] if case else None
        determined = case.get("_determined_at") if case else None
        compliance = calc.timeline_compliance(
            status, due, clock_date(), determined.date() if determined else None
        )
        remaining = calc.days_remaining(due, clock_date())

    return object_response(
        {
            "referral_id": referral["id"],
            "eligibility_pathway": referral["eligibility_pathway"],
            "received_date": fmt_date(referral["received_at"].date()),
            "consent_granted_date": fmt_date(granted_at.date() if granted_at else None),
            "receipt_anchored_due_date": fmt_date(
                calc.receipt_anchored_due_date(referral["received_at"])
            ),
            "consent_anchored_due_date": fmt_date(calc.consent_anchored_due_date(granted_at)),
            "third_birthday_cap_date": fmt_date(
                calc.third_birthday(child["date_of_birth"]) if child else None
            ),
            "evaluation_due_date": fmt_date(due),
            "days_remaining": remaining,
            "timeline_compliance": compliance,
        }
    )
