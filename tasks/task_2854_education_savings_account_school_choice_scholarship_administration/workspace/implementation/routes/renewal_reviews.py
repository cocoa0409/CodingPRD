"""Continued-eligibility renewal reviews and the minted successor offer."""
from flask import Blueprint

import calc
import cascades
import lookups
from envelope import list_response, object_response, public, touch
from errors import fail
from store import by_seq, new_id, store
from validators import (ASSESSMENT_TYPES, RENEWAL_STATUSES, authenticate, body,
                        paginate, q_enum, q_str, v_enum, v_int, v_state_code,
                        v_str)

bp = Blueprint("renewal_reviews", __name__)

READ_ROLES = ("ProgramAdmin", "EligibilityOfficer", "ComplianceOfficer",
              "AppealsOfficer", "Guardian")


@bp.post("/renewal-reviews")
def create_renewal_review():
    authenticate("Guardian")
    payload = body()
    account_id = v_str(payload, "account_id")
    next_program_year_id = v_str(payload, "next_program_year_id")
    assessment_type = v_enum(payload, "assessment_type", ASSESSMENT_TYPES)
    residency_state_attested = v_state_code(payload, "residency_state_attested")
    expected_application_version = v_int(payload, "expected_application_version",
                                        minimum=0)
    assessment_score = v_int(payload, "assessment_score", required=False,
                             default=None, minimum=0, maximum=100)
    portfolio_artifact_count = v_int(payload, "portfolio_artifact_count",
                                     required=False, default=None, minimum=0)

    lookups.program_year(next_program_year_id)
    acct = lookups.account(account_id)
    app = store.applications.get(acct["application_id"])
    current_version = app["version"] if app is not None else None
    if expected_application_version != current_version:
        fail("ERR_STALE_APPLICATION_VERSION",
             "expected_application_version %s does not match %s"
             % (expected_application_version, current_version))

    for prior in by_seq(list(store.renewal_reviews.values())):
        if prior["account_id"] == account_id and prior["status"] == "SUBMITTED":
            prior["status"] = "SUPERSEDED"
            touch(prior)

    created_at = store.next_created_at()
    record = {
        "id": new_id(),
        "account_id": account_id,
        "next_program_year_id": next_program_year_id,
        "assessment_type": assessment_type,
        "assessment_score": assessment_score,
        "portfolio_artifact_count": portfolio_artifact_count,
        "residency_state_attested": residency_state_attested,
        "status": "SUBMITTED",
        "decided_by_user_id": None,
        "renewed_application_id": None,
        "decision_note": None,
        "created_at": created_at,
        "updated_at": created_at,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.renewal_reviews[record["id"]] = record
    if app is not None:
        touch(app)
    return object_response(public(record), 201)


@bp.get("/renewal-reviews/<rid>")
def read_renewal_review(rid):
    authenticate(*READ_ROLES)
    return object_response(public(lookups.renewal_review(rid)))


@bp.get("/renewal-reviews")
def list_renewal_reviews():
    authenticate(*READ_ROLES)
    account_id = q_str("account_id")
    next_program_year_id = q_str("next_program_year_id")
    status = q_enum("status", RENEWAL_STATUSES)
    rows = by_seq(list(store.renewal_reviews.values()))
    if account_id:
        rows = [r for r in rows if r["account_id"] == account_id]
    if next_program_year_id:
        rows = [r for r in rows
                if r["next_program_year_id"] == next_program_year_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, meta = paginate(rows)
    return list_response([public(r) for r in page], meta)


@bp.post("/renewal-reviews/<rid>/decision")
def decide_renewal_review(rid):
    user_id, _role = authenticate("EligibilityOfficer")
    payload = body()
    decision = v_enum(payload, "decision", ("APPROVED", "DENIED"))
    decision_note = v_str(payload, "decision_note", required=False, default=None)
    review = lookups.renewal_review(rid)
    acct = store.accounts.get(review["account_id"])
    target = store.program_years.get(review["next_program_year_id"])

    if decision == "DENIED":
        if review["status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "only a SUBMITTED review may be decided")
        review["status"] = "DENIED"
        review["decided_by_user_id"] = user_id
        review["decision_note"] = decision_note
        touch(review)
        return object_response({
            "renewal_review_id": review["id"],
            "status": review["status"],
            "renewed_application_id": None,
            "prior_account_status": acct["status"] if acct else None,
            "next_program_year_seats_available": (
                target["seats_available"] if target else None),
        })

    if target is None or target["status"] not in ("WINDOW_OPEN", "ACTIVE"):
        fail("ERR_PROGRAM_YEAR_NOT_ACTIVE",
             "the target program year must be WINDOW_OPEN or ACTIVE")
    if review["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a SUBMITTED review may be decided")
    if review["residency_state_attested"] != target["residency_state"]:
        fail("ERR_RESIDENCY_NOT_ELIGIBLE",
             "the attested residency state does not match the target year")
    if review["assessment_type"] == "NORM_REFERENCED_TEST":
        score = review["assessment_score"]
        if score is None or score < target["min_assessment_percentile"]:
            fail("ERR_ASSESSMENT_EVIDENCE_INSUFFICIENT",
                 "the assessment percentile does not clear the target minimum")
    else:
        artifacts = review["portfolio_artifact_count"]
        if artifacts is None or artifacts < target["min_portfolio_artifacts"]:
            fail("ERR_ASSESSMENT_EVIDENCE_INSUFFICIENT",
                 "the portfolio artefact count does not clear the target minimum")
    if target["seats_available"] < 1:
        fail("ERR_NO_SEATS_AVAILABLE", "the target program year has no seats left")

    prior_app = store.applications.get(acct["application_id"]) if acct else None
    student = store.students.get(prior_app["student_id"]) if prior_app else None
    if student is None:
        fail("ERR_INVALID_STATE_TRANSITION",
             "the account has no student behind it")

    band = student["income_band"]
    flags = list(student["category_flags"] or [])
    award = calc.annual_award_amount(target["base_award_cents"], band, flags)
    created_at = store.next_created_at()
    new_app = {
        "id": new_id(),
        "program_year_id": target["id"],
        "student_id": student["id"],
        "status": "AWARD_OFFERED",
        "is_renewal": True,
        "claimed_income_band": band,
        "claimed_category_flags": list(flags),
        "provisional_award_cents": 0,
        "verified_income_band": band,
        "verified_category_flags": list(flags),
        "annual_award_cents": award,
        "final_award_cents": 0,
        "priority_tier": 1,
        "priority_score": 0,
        "waitlist_position": None,
        "submitted_at": None,
        "acceptance_deadline_at": cascades.offer_deadline(target),
        "appeal_round_count": 0,
        "created_at": created_at,
        "updated_at": created_at,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.applications[new_app["id"]] = new_app

    review["status"] = "APPROVED"
    review["decided_by_user_id"] = user_id
    review["decision_note"] = decision_note
    review["renewed_application_id"] = new_app["id"]
    touch(review)

    cascades.recount_seats(target)

    return object_response({
        "renewal_review_id": review["id"],
        "status": review["status"],
        "renewed_application_id": new_app["id"],
        "prior_account_status": acct["status"] if acct else None,
        "next_program_year_seats_available": target["seats_available"],
    })
