"""The advancement pipeline and the committee return loop (PRD 3.3)."""

from flask import Blueprint

import errors
import validation as v
from db import base_row, db, now, touch
from errors import fail
from middleware import (ANY_ROLE, ROLE_DIRECTOR, ROLE_FIELD_EVALUATOR,
                        ROLE_OFFICIAL, caller_id, endpoint)
from response import list_response, object_response
from services import calc, derive

bp = Blueprint("applications", __name__)

TARGET_TIERS = ["TIER_2", "TIER_1"]


def _evaluations_of(application_id):
    return derive.rows_of(db.field_evaluations, application_id=application_id)


def _refresh_evaluation_average(application):
    reports = _evaluations_of(application["id"])
    application["evaluation_average"] = calc.evaluation_average(
        [r["composite_score"] for r in reports])


@bp.route("/advancement-applications", methods=["POST"])
@endpoint([ROLE_OFFICIAL])
def create_application():
    """"An `Official` ... files an advancement application naming their own
    `official_id` and the `target_tier` they are asking to be promoted into,
    which must be `TIER_2` or `TIER_1`.\""""
    data = v.body()
    official_id = v.req_str(data, "official_id")
    target_tier = v.req_enum(data, "target_tier", TARGET_TIERS)

    official = derive.get_official(official_id)
    derive.require_program_open(derive.program_of_official(official))

    row = base_row()
    row.update({
        "official_id": official["id"],
        "target_tier": target_tier,
        "status": "SUBMITTED",
        "return_count": 0,
        "evaluation_average": None,
        "decision_note": None,
        "screened_at": None,
    })
    db.applications[row["id"]] = row
    return object_response(row, 201)


@bp.route("/advancement-applications/<application_id>/screen", methods=["POST"])
@endpoint([ROLE_FIELD_EVALUATOR])
def screen_application(application_id):
    """"Screening ... moves the application `SUBMITTED -> SCREENED`, stamping
    `screened_at` with the logical clock" once all five advancement criteria
    hold; any failure is ERR_ADVANCEMENT_CRITERIA_NOT_MET."""
    application = derive.get_application(application_id)
    official = db.officials.get(application["official_id"])
    derive.require_program_open(derive.program_of_official(official))
    if application["status"] != "SUBMITTED":
        fail(errors.ERR_APPLICATION_STATE_INVALID,
             "An application may only be screened from SUBMITTED.")

    target_tier = application["target_tier"]
    record = derive.season_record_of(official["id"])
    accuracy = record["accuracy_index"] if record else None
    if official["status"] != "ACTIVE":
        fail(errors.ERR_ADVANCEMENT_CRITERIA_NOT_MET,
             "The applicant's status is not ACTIVE.")
    if not official["preseason_cleared"]:
        fail(errors.ERR_ADVANCEMENT_CRITERIA_NOT_MET,
             "The applicant is not preseason cleared.")
    if calc.TIER_ORDER[target_tier] - calc.TIER_ORDER[official["tier"]] != 1:
        fail(errors.ERR_ADVANCEMENT_CRITERIA_NOT_MET,
             "The applicant's tier is not exactly one step below %s." % target_tier)
    if official["seasons_experience"] < calc.MIN_EXPERIENCE_FOR_TIER[target_tier]:
        fail(errors.ERR_ADVANCEMENT_CRITERIA_NOT_MET,
             "The applicant has too few completed seasons for %s." % target_tier)
    if accuracy is None or accuracy < calc.ADVANCEMENT_MIN_ACCURACY:
        fail(errors.ERR_ADVANCEMENT_CRITERIA_NOT_MET,
             "The applicant's accuracy index is below %s."
             % calc.ADVANCEMENT_MIN_ACCURACY)

    application["status"] = "SCREENED"
    application["screened_at"] = now()
    touch(application)
    return object_response(application)


@bp.route("/advancement-applications/<application_id>/field-evaluations",
          methods=["POST"])
@endpoint([ROLE_FIELD_EVALUATOR])
def file_field_evaluation(application_id):
    """An immutable report carrying `evaluator_user_id` from the filer's
    `X-User-ID` and a derived `composite_score`; filing it also refreshes the
    parent application's `evaluation_average` and bumps its `version`."""
    data = v.body()
    mechanics_score = v.req_score(data, "mechanics_score")
    rules_score = v.req_score(data, "rules_score")
    presence_score = v.req_score(data, "presence_score")

    application = derive.get_application(application_id)
    derive.require_program_open(derive.program_of_application(application))

    row = base_row(with_version=False)
    row.update({
        "application_id": application["id"],
        "evaluator_user_id": caller_id(),
        "mechanics_score": mechanics_score,
        "rules_score": rules_score,
        "presence_score": presence_score,
        "composite_score": calc.composite_score(
            mechanics_score, rules_score, presence_score),
    })
    db.field_evaluations[row["id"]] = row
    _refresh_evaluation_average(application)
    touch(application)
    return object_response(row, 201)


@bp.route("/advancement-applications/<application_id>/field-evaluations",
          methods=["GET"])
@endpoint(ANY_ROLE)
def list_field_evaluations(application_id):
    limit, offset = v.pagination()
    application = derive.get_application(application_id)
    rows = _evaluations_of(application["id"])
    return list_response(v.paginate(rows, limit, offset), limit, offset, len(rows))


@bp.route("/advancement-applications/<application_id>/submit-to-committee",
          methods=["POST"])
@endpoint([ROLE_FIELD_EVALUATOR])
def submit_to_committee(application_id):
    """"legal from either `SCREENED` or `RETURNED_FOR_TAPE` ... the report count
    must be at least 2 plus the current `return_count` ... and
    `evaluation_average` must be at least 75.00.\""""
    application = derive.get_application(application_id)
    derive.require_program_open(derive.program_of_application(application))
    if application["status"] not in ("SCREENED", "RETURNED_FOR_TAPE"):
        fail(errors.ERR_APPLICATION_STATE_INVALID,
             "An application may only be forwarded from SCREENED or "
             "RETURNED_FOR_TAPE.")
    required = calc.MIN_EVALUATIONS + application["return_count"]
    reports = _evaluations_of(application["id"])
    if len(reports) < required:
        fail(errors.ERR_EVALUATION_REQUIREMENTS_NOT_MET,
             "At least %d field evaluation reports are required." % required)
    average = application["evaluation_average"]
    if average is None or average < calc.MIN_EVAL_AVERAGE:
        fail(errors.ERR_EVALUATION_REQUIREMENTS_NOT_MET,
             "The evaluation average is below %s." % calc.MIN_EVAL_AVERAGE)
    application["status"] = "COMMITTEE_REVIEW"
    touch(application)
    return object_response(application)


@bp.route("/advancement-applications/<application_id>/return-for-tape",
          methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def return_for_tape(application_id):
    """"While `return_count` is strictly less than the program's
    `max_application_returns`, the return increments `return_count` by 1 ... When
    `return_count` has already reached `max_application_returns`, the very same
    call ... moves the application `COMMITTEE_REVIEW -> DENIED`.\""""
    data = v.body()
    note = v.req_str(data, "note")

    application = derive.get_application(application_id)
    program = derive.program_of_application(application)
    derive.require_program_open(program)
    if application["status"] != "COMMITTEE_REVIEW":
        fail(errors.ERR_APPLICATION_STATE_INVALID,
             "An application may only be returned from COMMITTEE_REVIEW.")

    if application["return_count"] < program["max_application_returns"]:
        application["return_count"] = application["return_count"] + 1
        application["status"] = "RETURNED_FOR_TAPE"
    else:
        application["status"] = "DENIED"
    application["decision_note"] = note
    touch(application)
    return object_response(application)


@bp.route("/advancement-applications/<application_id>/decide", methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def decide_application(application_id):
    """"On `APPROVED` the application moves `COMMITTEE_REVIEW -> APPROVED` and
    the applicant's `tier` is raised to the application's `target_tier`, bumping
    the official's `version` by 1 ... On `DENIED` ... the official's `tier` is
    left exactly as it was.\""""
    data = v.body()
    outcome = v.req_enum(data, "outcome", ["APPROVED", "DENIED"])
    note = v.opt_str(data, "note", 1, None, None)

    application = derive.get_application(application_id)
    official = db.officials.get(application["official_id"])
    derive.require_program_open(derive.program_of_application(application))
    if application["status"] != "COMMITTEE_REVIEW":
        fail(errors.ERR_APPLICATION_STATE_INVALID,
             "A committee decision is only legal from COMMITTEE_REVIEW.")

    application["status"] = outcome
    if note is not None:
        application["decision_note"] = note
    if outcome == "APPROVED" and official is not None:
        official["tier"] = application["target_tier"]
        touch(official)
    touch(application)
    return object_response(application)


@bp.route("/advancement-applications/<application_id>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_application(application_id):
    return object_response(derive.get_application(application_id))


@bp.route("/advancement-applications", methods=["GET"])
@endpoint(ANY_ROLE)
def list_applications():
    limit, offset = v.pagination()
    rows = derive.rows_of(db.applications)
    for name in ("official_id", "status", "target_tier"):
        wanted = v.query_filter(name)
        if wanted is not None:
            rows = [r for r in rows if r.get(name) == wanted]
    return list_response(v.paginate(rows, limit, offset), limit, offset, len(rows))
