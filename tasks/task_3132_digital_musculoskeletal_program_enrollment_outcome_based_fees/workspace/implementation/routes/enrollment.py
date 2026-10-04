"""Enrollments, clinical reviews and transition reviews."""

from flask import Blueprint

from db import STORE
from middleware import body, query, require
from response import array_response, object_response, page
from services import common, intake
from utils import week_of

bp = Blueprint("enrollment", __name__)

READ_ROLES = ["EnrollmentOps", "ClinicalOps", "BillingOps"]


# --- enrollments -----------------------------------------------------------
@bp.route("/msk/enrollments", methods=["POST"])
def open_enrollment():
    require(["EnrollmentOps"], "POST /msk/enrollments")
    return object_response(dict(intake.open_enrollment(body())), 201)


@bp.route("/msk/enrollments", methods=["GET"])
def list_enrollments():
    require(READ_ROLES, "GET /msk/enrollments")
    rows = STORE.all("Enrollment")
    for name in ("member_id", "eligibility_file_id", "program_track_id",
                 "enrollment_status"):
        wanted = query(name)
        if wanted:
            rows = [r for r in rows if str(r.get(name)) == wanted]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/enrollments/<enrollment_id>", methods=["GET"])
def read_enrollment(enrollment_id):
    require(READ_ROLES, "GET /msk/enrollments/{id}")
    item = STORE.need("Enrollment", enrollment_id, "Enrollment")
    view = dict(item)
    # Refresh the projections that depend on the live clock before reporting.
    live = dict(item)
    common.recompute_projection(live)
    view["weeks_active"] = live["weeks_active"]
    view["adherence_rate"] = live["adherence_rate"]
    view["adherence_scored_through_week"] = live["adherence_scored_through_week"]
    view["projected_engagement_milestone"] = live[
        "projected_engagement_milestone"
    ]
    view["attributed_savings_cents"] = item.get("attributed_savings_cents") or 0
    return object_response(view)


@bp.route("/msk/enrollments/<enrollment_id>/drop", methods=["POST"])
def drop_enrollment(enrollment_id):
    require(["EnrollmentOps"], "POST /msk/enrollments/{id}/drop")
    return object_response(dict(intake.drop_enrollment(enrollment_id)))


@bp.route("/msk/enrollments/<enrollment_id>/complete", methods=["POST"])
def complete_enrollment(enrollment_id):
    require(["ClinicalReviewService"], "POST /msk/enrollments/{id}/complete")
    return object_response(dict(intake.complete_enrollment(enrollment_id)))


@bp.route(
    "/msk/enrollments/<enrollment_id>/transition-reviews", methods=["POST"]
)
def transition_request(enrollment_id):
    user_id, role = require(
        ["Clinician"], "POST /msk/enrollments/{id}/transition-reviews"
    )
    payload = body()
    acting = payload.get("clinician_id") or user_id
    return object_response(
        dict(intake.transition_request(enrollment_id, payload, acting)), 201
    )


@bp.route("/msk/enrollments/reconcile-reviews", methods=["POST"])
def reconcile_reviews():
    require(["ClinicalReviewService"], "POST /msk/enrollments/reconcile-reviews")
    from services import operations

    result = operations.reconcile_reviews()
    return object_response({
        "reconciled_enrollment_count": result["reconciled_enrollment_count"],
        "accelerated_enrollment_count": result["accelerated_enrollment_count"],
    })


# --- clinical reviews ------------------------------------------------------
@bp.route("/msk/clinical-reviews", methods=["POST"])
def seed_review():
    require(["EnrollmentOps"], "POST /msk/clinical-reviews")
    return object_response(dict(intake.seed_review(body())), 201)


@bp.route("/msk/clinical-reviews", methods=["GET"])
def list_reviews():
    require(["ClinicalOps", "EnrollmentOps"], "GET /msk/clinical-reviews")
    rows = STORE.all("ClinicalReview")
    enrollment_id = query("enrollment_id")
    if enrollment_id:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    status = query("review_status")
    if status:
        rows = [r for r in rows if r["review_status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/clinical-reviews/<review_id>", methods=["GET"])
def read_review(review_id):
    require(["ClinicalOps", "EnrollmentOps"], "GET /msk/clinical-reviews/{id}")
    row = STORE.need("ClinicalReview", review_id, "ClinicalReview")
    return object_response(dict(row))


@bp.route("/msk/clinical-reviews/<review_id>/conduct", methods=["POST"])
def conduct_review(review_id):
    user_id, role = require(
        ["Clinician"], "POST /msk/clinical-reviews/{id}/conduct"
    )
    return object_response(dict(intake.conduct_review(review_id, body(), user_id)))


@bp.route("/msk/clinical-reviews/<review_id>/reopen", methods=["POST"])
def reopen_review(review_id):
    require(["ClinicalReviewService"], "POST /msk/clinical-reviews/{id}/reopen")
    return object_response(dict(intake.reopen_review(review_id)))


# --- transition reviews (the id is the ENROLLMENT) -------------------------
@bp.route("/msk/transition-reviews/<enrollment_id>/approve", methods=["POST"])
def approve_transition(enrollment_id):
    user_id, role = require(
        ["Clinician"], "POST /msk/transition-reviews/{id}/approve"
    )
    return object_response(
        dict(intake.approve_transition(enrollment_id, body(), user_id))
    )


@bp.route("/msk/transition-reviews/<enrollment_id>/deny", methods=["POST"])
def deny_transition(enrollment_id):
    user_id, role = require(
        ["ClinicalReviewService"], "POST /msk/transition-reviews/{id}/deny"
    )
    return object_response(
        dict(intake.deny_transition(enrollment_id, body(), user_id))
    )