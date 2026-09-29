"""Routes: chart-review oversight and communication to the PCP."""

from datetime import timedelta

from flask import Blueprint

import calc
import serial
from auth import (
    ROLE_CLINIC_ADMIN,
    ROLE_CLINICIAN,
    ROLE_FRONT_DESK,
    ROLE_PATIENT,
    ROLE_PHYSICIAN,
    authenticate,
)
from common import (
    collection,
    get_chart_review,
    get_clinic,
    get_visit_summary,
    state_rule_or_404,
)
from envelope import object_response
from errors import (
    ERR_CHART_REVIEW_INVALID_STATE,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_TIME_RANGE,
    ERR_NO_ELIGIBLE_REVIEWER,
    ERR_REVIEW_CYCLE_LIMIT,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SUMMARY_INVALID_STATE,
    raise_error,
)
from shapes import (
    json_body,
    query_enum,
    query_string,
    read_enum,
    read_instant,
    read_string,
    reject_unknown,
)
from store import db, new_row, touch

bp = Blueprint("oversight", __name__)

REVIEW_STATUSES = ("PENDING", "CHANGES_REQUESTED", "ATTESTED", "ESCALATED")
SAMPLED_REASONS = ("RANDOM_SAMPLE", "MANDATORY_REFERRAL", "CONTROLLED_RX")
OUTCOMES = ("WITHIN_SCOPE", "SCOPE_DEVIATION")
SUMMARY_STATUSES = ("QUEUED", "SENT", "FAILED", "UNDELIVERABLE")
DESTINATION_KINDS = ("DIRECT_MESSAGE", "FAX", "PATIENT_PORTAL")
TRANSPORT_OUTCOMES = ("SENT", "FAILED")


# ---------------------------------------------------------------------------
# POST /clinics/{clinicId}/chart-review-samplings
# ---------------------------------------------------------------------------

@bp.route("/clinics/<clinic_id>/chart-review-samplings", methods=["POST"])
def run_sampling(clinic_id):
    authenticate([ROLE_PHYSICIAN, ROLE_CLINIC_ADMIN])
    body = json_body(required=True)
    reject_unknown(body, {"window_start", "window_end"})
    window_start = read_instant(body, "window_start")
    window_end = read_instant(body, "window_end")

    clinic = get_clinic(clinic_id)

    # rung 8 - state rule presence
    state_rule = state_rule_or_404(clinic["state_code"])

    # rung 29 - interval sanity
    if not window_start < window_end:
        raise_error(
            ERR_INVALID_TIME_RANGE,
            "Field 'window_start' must fall strictly before 'window_end'.",
        )

    eligible, mandatory, picked, selected = calc.sampling_plan(
        clinic, state_rule, window_start, window_end
    )
    due_at = db.clock + timedelta(hours=state_rule["review_deadline_hours"])

    created_ids = []
    for visit, reason in selected:
        assessment = calc.assessment_for_visit(visit["id"])
        clinician = db.clinicians.get(visit["clinician_id"])
        reviewer_id = (
            clinician["supervising_physician_id"] if clinician is not None else None
        )
        row = new_row()
        row.update({
            "visit_id": visit["id"],
            "assessment_id": assessment["id"] if assessment is not None else None,
            "reviewer_physician_id": reviewer_id,
            "sampled_reason": reason,
            "due_at": due_at,
            "changes_requested_count": 0,
            "outcome": None,
            "status": "PENDING",
        })
        db.chart_reviews[row["id"]] = row
        created_ids.append(row["id"])

    return object_response({
        "sampled_count": len(selected),
        "mandatory_count": len(mandatory),
        "random_count": len(picked),
        "chart_review_ids": created_ids,
    }, 200)


# ---------------------------------------------------------------------------
# POST /chart-reviews/{chartReviewId}/request-changes
# ---------------------------------------------------------------------------

@bp.route("/chart-reviews/<chart_review_id>/request-changes", methods=["POST"])
def request_changes(chart_review_id):
    actor = authenticate([ROLE_PHYSICIAN])
    body = json_body(required=True)
    reject_unknown(body, {"change_note"})
    read_string(body, "change_note")

    row = get_chart_review(chart_review_id)

    # rung 10 - declared transition
    if row["status"] != "PENDING":
        raise_error(
            ERR_CHART_REVIEW_INVALID_STATE,
            "Chart review %s is %s." % (row["id"], row["status"]),
        )

    # rung 25 - ownership
    if row["reviewer_physician_id"] != actor.user_id:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "Only the current reviewer may request changes.",
        )

    # rung 32 - review cycle limit
    if row["changes_requested_count"] >= calc.MAX_CHANGE_CYCLES:
        raise_error(ERR_REVIEW_CYCLE_LIMIT)

    row["status"] = "CHANGES_REQUESTED"
    row["changes_requested_count"] = row["changes_requested_count"] + 1
    touch(row)
    return object_response(serial.chart_review(row), 200)


# ---------------------------------------------------------------------------
# POST /chart-reviews/{chartReviewId}/resubmit
# ---------------------------------------------------------------------------

@bp.route("/chart-reviews/<chart_review_id>/resubmit", methods=["POST"])
def resubmit_review(chart_review_id):
    actor = authenticate([ROLE_CLINICIAN])
    body = json_body(required=True)
    reject_unknown(body, {"amendment_note"})
    read_string(body, "amendment_note")

    row = get_chart_review(chart_review_id)

    # rung 10 - declared transition
    if row["status"] != "CHANGES_REQUESTED":
        raise_error(
            ERR_CHART_REVIEW_INVALID_STATE,
            "Chart review %s is %s." % (row["id"], row["status"]),
        )

    # rung 25 - ownership
    visit = db.visits.get(row["visit_id"])
    if visit is None or visit["clinician_id"] != actor.user_id:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "Only the treating clinician may resubmit this chart.",
        )

    row["status"] = "PENDING"
    touch(row)
    return object_response(serial.chart_review(row), 200)


# ---------------------------------------------------------------------------
# POST /chart-reviews/{chartReviewId}/attest
# ---------------------------------------------------------------------------

@bp.route("/chart-reviews/<chart_review_id>/attest", methods=["POST"])
def attest_review(chart_review_id):
    actor = authenticate([ROLE_PHYSICIAN])
    body = json_body(required=True)
    reject_unknown(body, {"outcome", "attestation_note"})
    outcome = read_enum(body, "outcome", OUTCOMES)
    read_string(body, "attestation_note", required=False)

    row = get_chart_review(chart_review_id)

    # rung 10 - declared transition
    if row["status"] != "PENDING":
        raise_error(
            ERR_CHART_REVIEW_INVALID_STATE,
            "Chart review %s is %s." % (row["id"], row["status"]),
        )

    # rung 24 - segregation of duties
    assessment = db.assessments.get(row["assessment_id"])
    if (
        assessment is not None
        and assessment["cosigned_by_physician_id"] == actor.user_id
    ):
        raise_error(
            ERR_SEGREGATION_OF_DUTIES,
            "The cosigning physician may not attest this review.",
        )

    # rung 25 - ownership
    if row["reviewer_physician_id"] != actor.user_id:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "Only the current reviewer may attest this chart.",
        )

    row["outcome"] = outcome
    row["status"] = "ATTESTED" if outcome == "WITHIN_SCOPE" else "ESCALATED"
    touch(row)

    if outcome == "SCOPE_DEVIATION":
        visit = db.visits.get(row["visit_id"])
        clinician = (
            db.clinicians.get(visit["clinician_id"]) if visit is not None else None
        )
        if clinician is not None and not clinician["scope_hold"]:
            clinician["scope_hold"] = True
            touch(clinician)

    return object_response(serial.chart_review(row), 200)


# ---------------------------------------------------------------------------
# POST /chart-reviews/{chartReviewId}/reassign
# ---------------------------------------------------------------------------

@bp.route("/chart-reviews/<chart_review_id>/reassign", methods=["POST"])
def reassign_review(chart_review_id):
    authenticate([ROLE_CLINIC_ADMIN])
    body = json_body(required=False)
    reject_unknown(body, set())

    row = get_chart_review(chart_review_id)

    visit = db.visits[row["visit_id"]]
    clinic = db.clinics[visit["clinic_id"]]

    # rung 8 - state rule presence
    state_rule = state_rule_or_404(clinic["state_code"])

    # rung 10 - declared transition
    if row["status"] != "PENDING":
        raise_error(
            ERR_CHART_REVIEW_INVALID_STATE,
            "Chart review %s is %s." % (row["id"], row["status"]),
        )

    assessment = db.assessments.get(row["assessment_id"])
    winner = calc.reviewer_reassignment_selection(
        row, clinic, state_rule, assessment
    )
    if winner is None:
        raise_error(ERR_NO_ELIGIBLE_REVIEWER)

    row["reviewer_physician_id"] = winner["id"]
    touch(row)
    return object_response(serial.chart_review(row), 200)


# ---------------------------------------------------------------------------
# POST /visit-summaries/{visitSummaryId}/transmit
# ---------------------------------------------------------------------------

@bp.route("/visit-summaries/<visit_summary_id>/transmit", methods=["POST"])
def transmit_summary(visit_summary_id):
    authenticate([ROLE_CLINIC_ADMIN])
    body = json_body(required=True)
    reject_unknown(body, {"transport_outcome", "failure_code"})
    outcome = read_enum(body, "transport_outcome", TRANSPORT_OUTCOMES)
    failure_code = read_string(body, "failure_code", required=False)

    row = get_visit_summary(visit_summary_id)

    # rung 10 - declared transition
    if row["status"] != "QUEUED":
        raise_error(
            ERR_SUMMARY_INVALID_STATE,
            "Visit summary %s is %s and cannot be transmitted."
            % (row["id"], row["status"]),
        )

    row["attempt_count"] = row["attempt_count"] + 1
    if outcome == "SENT":
        row["sent_at"] = db.clock
        row["last_error_code"] = None
        row["status"] = "SENT"
    else:
        row["last_error_code"] = failure_code
        if row["attempt_count"] >= calc.MAX_TRANSMIT_ATTEMPTS:
            row["status"] = "UNDELIVERABLE"
        else:
            row["status"] = "FAILED"
    touch(row)
    return object_response(serial.visit_summary(row), 200)


# ---------------------------------------------------------------------------
# POST /visit-summaries/{visitSummaryId}/retry
# ---------------------------------------------------------------------------

@bp.route("/visit-summaries/<visit_summary_id>/retry", methods=["POST"])
def retry_summary(visit_summary_id):
    authenticate([ROLE_CLINIC_ADMIN])
    body = json_body(required=False)
    reject_unknown(body, set())

    row = get_visit_summary(visit_summary_id)

    # rung 10 - declared transition
    if row["status"] != "FAILED":
        raise_error(
            ERR_SUMMARY_INVALID_STATE,
            "Visit summary %s is %s and cannot be requeued."
            % (row["id"], row["status"]),
        )

    row["status"] = "QUEUED"
    touch(row)
    return object_response(serial.visit_summary(row), 200)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@bp.route("/chart-reviews/<chart_review_id>", methods=["GET"])
def read_chart_review(chart_review_id):
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN])
    row = get_chart_review(chart_review_id)
    return object_response(serial.chart_review(row), 200)


@bp.route("/chart-reviews", methods=["GET"])
def list_chart_reviews():
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN])
    visit_id = query_string("visit_id")
    assessment_id = query_string("assessment_id")
    reviewer_id = query_string("reviewer_physician_id")
    sampled_reason = query_enum("sampled_reason", SAMPLED_REASONS)
    status = query_enum("status", REVIEW_STATUSES)
    return collection(db.chart_reviews, serial.chart_review, [
        (visit_id, lambda row, v: row["visit_id"] == v),
        (assessment_id, lambda row, v: row["assessment_id"] == v),
        (reviewer_id, lambda row, v: row["reviewer_physician_id"] == v),
        (sampled_reason, lambda row, v: row["sampled_reason"] == v),
        (status, lambda row, v: row["status"] == v),
    ])


@bp.route("/visit-summaries/<visit_summary_id>", methods=["GET"])
def read_visit_summary(visit_summary_id):
    actor = authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_FRONT_DESK,
                          ROLE_PATIENT])
    row = get_visit_summary(visit_summary_id)
    if actor.is_patient:
        visit = db.visits.get(row["visit_id"])
        if visit is None or visit["patient_id"] != actor.user_id:
            raise_error(
                ERR_FORBIDDEN_OWNERSHIP,
                "A patient may only read their own visit summaries.",
            )
    return object_response(serial.visit_summary(row), 200)


@bp.route("/visit-summaries", methods=["GET"])
def list_visit_summaries():
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_FRONT_DESK])
    visit_id = query_string("visit_id")
    destination_kind = query_enum("destination_kind", DESTINATION_KINDS)
    status = query_enum("status", SUMMARY_STATUSES)
    return collection(db.visit_summaries, serial.visit_summary, [
        (visit_id, lambda row, v: row["visit_id"] == v),
        (destination_kind, lambda row, v: row["destination_kind"] == v),
        (status, lambda row, v: row["status"] == v),
    ])
