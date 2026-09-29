"""Exposure packaging and actuarial sign-off (PRD 3.2)."""
from flask import Blueprint

import db
import response
import serialize
import services
import validate
from errors import bad_request, fail
from middleware import (
    BROKER_ACTUARY,
    BROKER_PLACEMENT_LEAD,
    CEDENT_UNDERWRITER,
    own_cedent,
    require,
)
from routes._common import CEDENT_READ, ordered_filtered, paged, q
from routes.programs import score_submission
from util import pct4

bp = Blueprint("exposures", __name__)

SIGNOFF_DECISIONS = ("SIGNED_OFF", "REJECTED")


@bp.route("/exposure-submissions", methods=["GET"])
def list_exposure_submissions():
    require(CEDENT_READ)
    rows = ordered_filtered(db.exposure_submissions, [
        ("program_id", q("program_id")),
        ("status", q("status")),
    ])
    return paged(rows, serialize.exposure_submission)


@bp.route("/exposure-submissions/<submission_id>", methods=["GET"])
def read_exposure_submission(submission_id):
    require(CEDENT_READ)
    row = services.get_submission(submission_id)
    return response.object_response(serialize.exposure_submission(row), 200)


@bp.route("/exposure-submissions/<submission_id>/submit-for-review", methods=["POST"])
def submit_for_review(submission_id):
    require((BROKER_PLACEMENT_LEAD,))
    submission = services.get_submission(submission_id)
    if submission["status"] != "DRAFT":
        fail("ERR_SUBMISSION_STATE_INVALID",
             "only a DRAFT package can be sent for review")
    program = services.get_program(submission["program_id"])
    if program["placement_status"] != "DRAFT":
        fail("ERR_PROGRAM_STATE_INVALID",
             "the owning program must still be DRAFT")

    score_submission(submission)
    submission["status"] = "ACTUARY_REVIEW"
    db.touch(submission)
    return response.object_response(serialize.exposure_submission(submission), 200)


@bp.route("/exposure-submissions/<submission_id>/signoff", methods=["POST"])
def signoff(submission_id):
    actor = require((BROKER_ACTUARY,))
    shape = validate.Shape()
    decision = shape.enum("decision", SIGNOFF_DECISIONS)
    review_note = shape.string("review_note", min_len=1, max_len=500,
                               required=False, default=None)

    submission = services.get_submission(submission_id)
    if submission["status"] != "ACTUARY_REVIEW":
        fail("ERR_SUBMISSION_STATE_INVALID",
             "a decision is recorded only against a package in ACTUARY_REVIEW")

    if decision == "REJECTED":
        submission["status"] = "REJECTED"
        submission["review_note"] = review_note
        db.touch(submission)
        return response.object_response(
            serialize.exposure_submission(submission), 200)

    import calc
    if submission["completeness_score"] < calc.SIGNOFF_MIN_SCORE:
        fail("ERR_SIGNOFF_SCORE_TOO_LOW",
             "the package's completeness_score is below %s" % calc.SIGNOFF_MIN_SCORE)

    submission["status"] = "SIGNED_OFF"
    submission["actuary_signoff_user_id"] = actor.user_id
    submission["signed_off_at"] = db.now()
    submission["review_note"] = review_note
    db.touch(submission)

    # Only one signed-off package can be the live one.
    for other in db.ordered(db.exposure_submissions):
        if other["id"] == submission["id"]:
            continue
        if other["program_id"] != submission["program_id"]:
            continue
        if other["status"] == "SIGNED_OFF":
            other["status"] = "SUPERSEDED"
            db.touch(other)

    program = services.get_program(submission["program_id"])
    if program["placement_status"] == "DRAFT":
        program["placement_status"] = "SUBMISSION_READY"
        db.touch(program)

    return response.object_response(serialize.exposure_submission(submission), 200)


@bp.route("/exposure-submissions/<submission_id>/revise", methods=["POST"])
def revise(submission_id):
    actor = require((CEDENT_UNDERWRITER,))
    existing = db.exposure_submissions.get(submission_id)
    if existing is not None:
        program = db.programs.get(existing["program_id"])
        if program is not None:
            own_cedent(actor, program["cedent_id"])

    shape = validate.Shape(patch=True)
    records = shape.integer("exposure_records_count", minimum=0,
                            required=False, default=None)
    flags = shape.integer("data_quality_flags_count", minimum=0,
                          required=False, default=None)
    years = shape.integer("historical_years_supplied", minimum=0, maximum=20,
                          required=False, default=None)
    cat_model_version = shape.string("cat_model_version", min_len=1, max_len=40,
                                     required=False, default=None)
    completeness = shape.percent("loss_history_completeness_pct", minimum=0,
                                 maximum=100, required=False, default=None)
    report = shape.boolean("actuarial_report_attached", required=False, default=None)

    submission = services.get_submission(submission_id)
    if submission["status"] != "REJECTED":
        fail("ERR_SUBMISSION_STATE_INVALID",
             "only a REJECTED package may be revised")

    merged_records = submission["exposure_records_count"] if records is None else records
    merged_flags = submission["data_quality_flags_count"] if flags is None else flags
    if merged_flags > merged_records:
        bad_request("data_quality_flags_count may not exceed exposure_records_count")

    submission["exposure_records_count"] = merged_records
    submission["data_quality_flags_count"] = merged_flags
    if years is not None:
        submission["historical_years_supplied"] = years
    if cat_model_version is not None:
        submission["cat_model_version"] = cat_model_version
    if completeness is not None:
        submission["loss_history_completeness_pct"] = pct4(completeness)
    if report is not None:
        submission["actuarial_report_attached"] = report

    score_submission(submission)
    submission["status"] = "DRAFT"
    db.touch(submission)
    return response.object_response(serialize.exposure_submission(submission), 200)
