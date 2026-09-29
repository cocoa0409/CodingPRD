"""Grade appeals, adjudication and the accuracy-recovery cascade (PRD 3.7)."""

from datetime import timedelta

from flask import Blueprint

import errors
import validation as v
from db import base_row, db, now, touch
from errors import fail
from middleware import (ANY_ROLE, ROLE_GRADING_SUPERVISOR, ROLE_OFFICIAL,
                        caller_id, endpoint)
from response import list_response, object_response
from services import calc, derive

bp = Blueprint("appeals", __name__)

OUTCOMES = ["UPHELD", "OVERTURNED", "MODIFIED"]


def _require_grade_owner(grade):
    """PRD 2.1: "when an `Official` files or withdraws a grade appeal, the server
    compares `X-User-ID` to the `official_id` of the appealed play grade, and
    rejects a mismatch with `ERR_NOT_GRADE_OWNER`.\""""
    if caller_id() != grade["official_id"]:
        fail(errors.ERR_NOT_GRADE_OWNER,
             "The caller is not the official this grade was written against.")


def _require_not_author(grade):
    """"a `GradingSupervisor` whose `X-User-ID` equals the `graded_by_user_id` of
    the graded play may neither take the appeal under review nor decide it.\""""
    if caller_id() == grade["graded_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The authoring supervisor may not adjudicate this appeal.")


@bp.route("/grade-appeals", methods=["POST"])
@endpoint([ROLE_OFFICIAL])
def file_appeal():
    data = v.body()
    play_grade_id = v.req_str(data, "play_grade_id")
    basis_note = v.req_str(data, "basis_note", 1, 500)

    grade = derive.get_play_grade(play_grade_id)
    _require_grade_owner(grade)

    official = db.officials.get(grade["official_id"])
    program = derive.program_of_grade(grade)
    derive.require_program_open(program)

    if grade["grade_status"] != "POSTED" or grade["appeal_state"] != "NOT_APPEALED":
        fail(errors.ERR_GRADE_STATE_INVALID,
             "Only a POSTED grade that is not already under appeal may be appealed.")

    # "The appeal window runs from the grade's posted_at forward by the program's
    # appeal_window_hours, and its boundary is inclusive."
    deadline = grade["posted_at"] + timedelta(hours=program["appeal_window_hours"])
    if now() > deadline:
        fail(errors.ERR_APPEAL_WINDOW_CLOSED,
             "The appeal window for this grade has closed.")
    if official["appeal_credits_remaining"] <= 0:
        fail(errors.ERR_APPEAL_CREDITS_EXHAUSTED,
             "The official has no appeal credits remaining.")

    row = base_row()
    row.update({
        "play_grade_id": grade["id"],
        "basis_note": basis_note,
        "status": "SUBMITTED",
        "submitted_at": now(),
        "decided_by_user_id": None,
        "decision_note": None,
        "revised_grade_code": None,
    })
    db.appeals[row["id"]] = row

    grade["appeal_state"] = "APPEAL_PENDING"
    touch(grade)
    official["appeal_credits_remaining"] = official["appeal_credits_remaining"] - 1
    touch(official)
    return object_response(row, 201)


@bp.route("/grade-appeals/<appeal_id>/start-review", methods=["POST"])
@endpoint([ROLE_GRADING_SUPERVISOR])
def start_review(appeal_id):
    """"Taking the appeal under review is legal only from `SUBMITTED`, only while
    the program is `OPEN`, and moves the appeal `SUBMITTED -> UNDER_REVIEW`.\""""
    appeal = derive.get_appeal(appeal_id)
    grade = db.play_grades.get(appeal["play_grade_id"])
    _require_not_author(grade)
    derive.require_program_open(derive.program_of_grade(grade))
    if appeal["status"] != "SUBMITTED":
        fail(errors.ERR_APPEAL_STATE_INVALID,
             "Only a SUBMITTED appeal may be taken under review.")
    appeal["status"] = "UNDER_REVIEW"
    touch(appeal)
    return object_response(appeal)


@bp.route("/grade-appeals/<appeal_id>/decide", methods=["POST"])
@endpoint([ROLE_GRADING_SUPERVISOR])
def decide_appeal(appeal_id):
    """UPHELD leaves the grade alone, MODIFIED rewrites `grade_code` to the
    supplied `revised_grade_code`, and OVERTURNED rewrites it to `CORRECT` and
    then walks the five-hop accuracy-recovery cascade."""
    data = v.body()
    outcome = v.req_enum(data, "outcome", OUTCOMES)
    decision_note = v.opt_str(data, "decision_note", 1, None, None)
    revised_grade_code = v.opt_enum(data, "revised_grade_code", calc.GRADE_CODES)
    if outcome == "MODIFIED" and revised_grade_code is None:
        fail(errors.ERR_INVALID_REQUEST,
             "A MODIFIED outcome requires a revised_grade_code.")

    appeal = derive.get_appeal(appeal_id)
    grade = db.play_grades.get(appeal["play_grade_id"])
    if outcome == "MODIFIED" and revised_grade_code == grade["grade_code"]:
        fail(errors.ERR_INVALID_REQUEST,
             "revised_grade_code must differ from the grade's current grade_code.")

    _require_not_author(grade)
    official = db.officials.get(grade["official_id"])
    derive.require_program_open(derive.program_of_grade(grade))
    if appeal["status"] != "UNDER_REVIEW":
        fail(errors.ERR_APPEAL_STATE_INVALID,
             "Only an UNDER_REVIEW appeal may be decided.")

    appeal["status"] = outcome
    appeal["decided_by_user_id"] = caller_id()
    if decision_note is not None:
        appeal["decision_note"] = decision_note
    appeal["revised_grade_code"] = (
        revised_grade_code if outcome == "MODIFIED" else None)
    touch(appeal)

    # Hop one: the grade itself.
    grade["appeal_state"] = "APPEAL_RESOLVED"
    if outcome == "MODIFIED":
        grade["grade_code"] = revised_grade_code
    elif outcome == "OVERTURNED":
        grade["grade_code"] = "CORRECT"
    if outcome in ("MODIFIED", "OVERTURNED") and official is not None:
        grade["error_points"] = calc.play_error_points(
            grade["grade_code"], grade["impact"], official["position"])
    touch(grade)

    if official is None:
        return object_response(appeal)

    record = derive.season_record_of(official["id"])
    was_accuracy_eligible = record["accuracy_eligible"] if record else False
    # Hops two and three: the season record and accuracy_eligible.
    record = derive.recompute_season_record(official, "PROVISIONAL")

    if outcome == "OVERTURNED" and record is not None:
        # Hop four: only when accuracy_eligible flips false -> true.
        if not was_accuracy_eligible and record["accuracy_eligible"]:
            for action in derive.discipline_actions_of(official["id"]):
                if action["reason_category"] != "PERFORMANCE":
                    continue
                if action["status"] not in derive.DISCIPLINE_SUPERSEDABLE:
                    continue
                action["status"] = "CLEARED"
                touch(action)
            # Hop five: the official's restoration and the eligibility re-derive.
            if (official["status"] == "PROBATION"
                    and not derive.has_blocking_discipline(official["id"])):
                official["status"] = "ACTIVE"
                touch(official)
            derive.refresh_postseason_eligible(official, bump=False)
    return object_response(appeal)


@bp.route("/grade-appeals/<appeal_id>/withdraw", methods=["POST"])
@endpoint([ROLE_OFFICIAL])
def withdraw_appeal(appeal_id):
    """"withdrawal moves the appeal to `WITHDRAWN`, returns the parent grade's
    `appeal_state` from `APPEAL_PENDING` to `NOT_APPEALED` while bumping the
    grade's `version`, and increments the official's `appeal_credits_remaining`
    by 1 while bumping the official's `version`.\""""
    appeal = derive.get_appeal(appeal_id)
    grade = db.play_grades.get(appeal["play_grade_id"])
    _require_grade_owner(grade)
    official = db.officials.get(grade["official_id"])
    derive.require_program_open(derive.program_of_grade(grade))
    if appeal["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        fail(errors.ERR_APPEAL_STATE_INVALID,
             "Only a SUBMITTED or UNDER_REVIEW appeal may be withdrawn.")

    appeal["status"] = "WITHDRAWN"
    touch(appeal)
    grade["appeal_state"] = "NOT_APPEALED"
    touch(grade)
    if official is not None:
        official["appeal_credits_remaining"] = (
            official["appeal_credits_remaining"] + 1)
        touch(official)
    return object_response(appeal)


@bp.route("/grade-appeals/<appeal_id>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_appeal(appeal_id):
    return object_response(derive.get_appeal(appeal_id))


@bp.route("/grade-appeals", methods=["GET"])
@endpoint(ANY_ROLE)
def list_appeals():
    limit, offset = v.pagination()
    rows = derive.rows_of(db.appeals)
    for name in ("play_grade_id", "status"):
        wanted = v.query_filter(name)
        if wanted is not None:
            rows = [r for r in rows if r.get(name) == wanted]
    return list_response(v.paginate(rows, limit, offset), limit, offset, len(rows))
