"""Reviewer minutes as a conserved ledger: booking and releasing slots."""

from datetime import timedelta

from flask import Blueprint

import calc
import serialize as ser
from auth import auth
from envelope import filter_param, paged, respond_object
from errors import ApiError
from helpers import assignment_or_404, rows
from store import base_record, db, touch
from validation import dt, i, read_raw_body, resolve_body_ids, s, validate_body

bp = Blueprint("assignments", __name__)

TURNAROUND_BUFFER = timedelta(minutes=30)

BOOKING_SPEC = {
    "review_id": s(required=True),
    "reviewer_id": s(required=True),
    "starts_at": dt(required=True),
    "ends_at": dt(required=True),
    "expected_reviewer_version": i(required=True),
}

CANCEL_SPEC = {"cancellation_reason": s(required=True, min_len=1, max_len=4000)}

READ_ROLES = ["StandardsEditor", "LegalCounsel", "ExecutiveEditor"]


def _required_discipline(review):
    """The stage the round is actually waiting on."""
    if review["status"] == "SUBMITTED" and review["requires_legal_review"]:
        return "LEGAL"
    return "STANDARDS"


def _collides(starts_at, ends_at, other):
    return (starts_at < other["ends_at"] + TURNAROUND_BUFFER
            and other["starts_at"] < ends_at + TURNAROUND_BUFFER)


@bp.route("/review-assignments", methods=["POST"])
def create_assignment():
    auth(["LegalCounsel", "StandardsEditor"])
    raw = read_raw_body()
    resolved = resolve_body_ids(raw, ["review_id", "reviewer_id"])
    body = validate_body(raw, BOOKING_SPEC)
    review = resolved["review_id"]
    reviewer = resolved["reviewer_id"]

    starts_at = body["starts_at"]
    ends_at = body["ends_at"]
    if ends_at <= starts_at:
        raise ApiError("ERR_INVALID_INTERVAL",
                       "ends_at must be strictly after starts_at.")
    if body["expected_reviewer_version"] != reviewer["version"]:
        raise ApiError("ERR_STALE_REVIEWER_VERSION",
                       "expected_reviewer_version does not match the reviewer's "
                       "current version.")

    story = db.stories.get(review["story_id"])
    if story is not None and reviewer["newsroom_id"] != story["newsroom_id"]:
        raise ApiError("ERR_CROSS_NEWSROOM_REFERENCE",
                       "The reviewer does not belong to the story's newsroom.")
    required = _required_discipline(review)
    if reviewer["discipline"] != required:
        raise ApiError("ERR_REVIEWER_DISCIPLINE_MISMATCH",
                       "This round is waiting on a %s reviewer." % required)
    for other in calc.ordered(list(db.assignments.values())):
        if (other["reviewer_id"] == reviewer["id"] and other["status"] == "SCHEDULED"
                and _collides(starts_at, ends_at, other)):
            raise ApiError("ERR_REVIEWER_SLOT_CONFLICT",
                           "The slot collides with another booking once the "
                           "thirty-minute turnaround buffer is applied.")

    minutes = calc.duration_minutes(starts_at, ends_at)
    if calc.reserved_minutes(reviewer["id"]) + minutes > reviewer["weekly_capacity_minutes"]:
        raise ApiError("ERR_REVIEWER_CAPACITY_EXCEEDED",
                       "The booking would exceed the reviewer's weekly capacity.")

    assignment = base_record()
    assignment.update({
        "review_id": review["id"],
        "reviewer_id": reviewer["id"],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "duration_minutes": minutes,
        "status": "SCHEDULED",
        "cancellation_reason": None,
    })
    db.assignments[assignment["id"]] = assignment
    calc.recompute_reviewer(reviewer)
    return respond_object(ser.assignment_out(assignment), 201)


@bp.route("/review-assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_assignment(assignment_id):
    auth(["LegalCounsel", "StandardsEditor", "ExecutiveEditor"])
    assignment = assignment_or_404(assignment_id)
    body = validate_body(read_raw_body(), CANCEL_SPEC)
    if assignment["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SCHEDULED booking may be released.")

    assignment["status"] = "CANCELLED"
    assignment["cancellation_reason"] = body["cancellation_reason"]
    touch(assignment)
    reviewer = db.reviewers.get(assignment["reviewer_id"])
    if reviewer is not None:
        calc.recompute_reviewer(reviewer)
    return respond_object(ser.assignment_out(assignment))


@bp.route("/review-assignments/<assignment_id>", methods=["GET"])
def read_assignment(assignment_id):
    auth(READ_ROLES)
    return respond_object(ser.assignment_out(assignment_or_404(assignment_id)))


@bp.route("/review-assignments", methods=["GET"])
def list_assignments():
    auth(READ_ROLES)
    review_id = filter_param("review_id")
    reviewer_id = filter_param("reviewer_id")
    status = filter_param("status")
    records = rows("assignments", lambda a: (
        (review_id is None or a["review_id"] == review_id)
        and (reviewer_id is None or a["reviewer_id"] == reviewer_id)
        and (status is None or a["status"] == status)))
    return paged(records, ser.assignment_out)
