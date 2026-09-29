"""Plagiarism, fabrication and conflict investigations, and the disciplinary
ledger they feed."""

from flask import Blueprint

import calc
import serialize as ser
from auth import auth, require_not_party
from envelope import filter_param, paged, respond_object
from errors import ApiError
from helpers import investigation_or_404, rows
from store import base_record, db, now, ordered, touch
from validation import (ALLEGATION_TYPES, APPEAL_OUTCOMES, DISPOSITIONS,
                        SEVERITIES, e, read_raw_body, resolve_body_ids, s,
                        validate_body)

bp = Blueprint("misconduct", __name__)

NON_TERMINAL_REVIEW = ("SUBMITTED", "LEGAL_CLEARED", "STANDARDS_CLEARED", "CHANGES_REQUESTED")

OPEN_SPEC = {
    "journalist_id": s(required=True),
    "allegation_type": e(ALLEGATION_TYPES, required=True),
    "severity": e(SEVERITIES, required=True),
    "allegation_summary": s(required=True, min_len=1, max_len=4000),
    "story_id": s(min_len=1),
}

ADVANCE_SPEC = {"advance_note": s(min_len=0, max_len=4000)}

DECIDE_SPEC = {
    "disposition": e(DISPOSITIONS, required=True),
    "decision_note": s(min_len=0, max_len=4000),
}

APPEAL_SPEC = {
    "appeal_outcome": e(APPEAL_OUTCOMES, required=True),
    "appeal_note": s(min_len=0, max_len=4000),
}


def _suspension_cascade(journalist):
    """The four arms of a suspension.  Returns the revoked activities so the
    caller can log one ACTIVITY_REVOKED event for each."""
    revoked = []
    for activity in ordered(list(db.activities.values())):
        if activity["journalist_id"] == journalist["id"] and activity["status"] == "APPROVED":
            activity["status"] = "REVOKED"
            activity["revocation_reason"] = "JOURNALIST_SUSPENDED"
            touch(activity)
            revoked.append(activity)

    affected_reviewers = []
    for story in ordered(list(db.stories.values())):
        if story["lead_journalist_id"] != journalist["id"]:
            continue
        if story["publication_status"] == "IN_REVIEW":
            story["publication_status"] = "DRAFT"
            touch(story)
        for review in ordered(list(db.reviews.values())):
            if review["story_id"] != story["id"]:
                continue
            if review["status"] not in NON_TERMINAL_REVIEW:
                continue
            review["status"] = "BLOCKED"
            touch(review)
            for assignment in ordered(list(db.assignments.values())):
                if (assignment["review_id"] == review["id"]
                        and assignment["status"] == "SCHEDULED"):
                    assignment["status"] = "CANCELLED"
                    touch(assignment)
                    affected_reviewers.append(assignment["reviewer_id"])
    # One ledger re-aggregation per distinct reviewer, however many bookings.
    calc.recompute_reviewers(affected_reviewers)
    return revoked


@bp.route("/misconduct-investigations", methods=["POST"])
def open_investigation():
    actor = auth(["StandardsEditor", "ExecutiveEditor"])
    raw = read_raw_body()
    resolved = resolve_body_ids(raw, ["journalist_id", "story_id"])
    body = validate_body(raw, OPEN_SPEC)
    journalist = resolved["journalist_id"]
    story = resolved.get("story_id")

    investigation = base_record()
    investigation.update({
        "journalist_id": journalist["id"],
        "story_id": story["id"] if story else None,
        "allegation_type": body["allegation_type"],
        "severity": body["severity"],
        "allegation_summary": body["allegation_summary"],
        "status": "OPENED",
        "penalty_points": 0,
        "prior_sustained_count": calc.prior_sustained_count(journalist["id"]),
        "disclosure_obligation": "NONE",
        "opened_by_user_id": actor.user_id,
        "decided_by_user_id": None,
        "opened_at": now(),
        "decided_at": None,
        "appeal_outcome": None,
    })
    db.investigations[investigation["id"]] = investigation
    # A newly opened serious or egregious inquiry is itself a high-severity matter.
    newsroom = db.newsrooms.get(journalist["newsroom_id"])
    if newsroom is not None:
        calc.recompute_posture(newsroom)
    return respond_object(ser.investigation_out(investigation), 201)


@bp.route("/misconduct-investigations/<investigation_id>/advance", methods=["POST"])
def advance_investigation(investigation_id):
    auth(["StandardsEditor", "ExecutiveEditor"])
    investigation = investigation_or_404(investigation_id)
    validate_body(read_raw_body(), ADVANCE_SPEC)
    if investigation["status"] == "OPENED":
        investigation["status"] = "EVIDENCE_REVIEW"
    elif investigation["status"] == "EVIDENCE_REVIEW":
        investigation["status"] = "RESPONSE_PENDING"
    else:
        raise ApiError("ERR_INVALID_STATE",
                       "There is no further pre-decision stage from %s."
                       % investigation["status"])
    touch(investigation)
    return respond_object(ser.investigation_out(investigation))


@bp.route("/misconduct-investigations/<investigation_id>/decide", methods=["POST"])
def decide_investigation(investigation_id):
    actor = auth(["StandardsEditor", "ExecutiveEditor"])
    investigation = investigation_or_404(investigation_id)
    # Step 5: neither the subject nor the editor who opened the case.
    require_not_party(actor, [investigation["journalist_id"],
                              investigation["opened_by_user_id"]])
    body = validate_body(read_raw_body(), DECIDE_SPEC)
    if investigation["status"] != "RESPONSE_PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "A finding may only be recorded from RESPONSE_PENDING.")

    journalist = db.journalists.get(investigation["journalist_id"])
    newsroom = db.newsrooms.get(journalist["newsroom_id"]) if journalist else None
    investigation["decided_by_user_id"] = actor.user_id
    investigation["decided_at"] = now()

    if body["disposition"] == "UNFOUNDED":
        investigation["status"] = "UNFOUNDED"
        touch(investigation)
        if newsroom is not None:
            calc.recompute_posture(newsroom)
        return respond_object(ser.investigation_out(investigation))

    # The prior count is evaluated against the clock at decision time, so the
    # order in which two allegations are processed is part of the specification.
    prior = calc.prior_sustained_count(investigation["journalist_id"],
                                       exclude_id=investigation["id"])
    investigation["status"] = "SUSTAINED"
    investigation["prior_sustained_count"] = prior
    investigation["penalty_points"] = calc.investigation_points(
        investigation["severity"], investigation["allegation_type"], prior)
    investigation["disclosure_obligation"] = calc.disclosure_obligation_for(
        investigation["allegation_type"], investigation["severity"])
    touch(investigation)

    revoked = []
    if journalist is not None:
        changed, previous = calc.recompute_journalist_points(journalist)
        if changed:
            touch(journalist)
        if previous == "ACTIVE" and journalist["employment_status"] == "SUSPENDED":
            revoked = _suspension_cascade(journalist)

    if newsroom is not None:
        calc.emit_audit(newsroom["id"], "INVESTIGATION_SUSTAINED",
                        "MisconductInvestigation", investigation["id"],
                        actor.role, actor.user_id,
                        "%s allegation sustained at %s severity."
                        % (investigation["allegation_type"], investigation["severity"]))
        for activity in revoked:
            calc.emit_audit(newsroom["id"], "ACTIVITY_REVOKED",
                            "OutsideActivityRequest", activity["id"], "system", None,
                            "Outside activity revoked because the journalist was suspended.")
        calc.recompute_posture(newsroom)
    return respond_object(ser.investigation_out(investigation))


@bp.route("/misconduct-investigations/<investigation_id>/appeal", methods=["POST"])
def appeal_investigation(investigation_id):
    actor = auth(["ExecutiveEditor"])
    investigation = investigation_or_404(investigation_id)
    # Step 5: neither the subject nor the editor who decided the case.
    require_not_party(actor, [investigation["journalist_id"],
                              investigation["decided_by_user_id"]])
    body = validate_body(read_raw_body(), APPEAL_SPEC)
    if investigation["status"] != "SUSTAINED":
        raise ApiError("ERR_APPEAL_NOT_ALLOWED",
                       "Only a SUSTAINED finding may be appealed.")

    journalist = db.journalists.get(investigation["journalist_id"])
    newsroom = db.newsrooms.get(journalist["newsroom_id"]) if journalist else None
    investigation["appeal_outcome"] = body["appeal_outcome"]

    if body["appeal_outcome"] == "UPHELD":
        touch(investigation)
        if newsroom is not None:
            calc.recompute_posture(newsroom)
        return respond_object(ser.investigation_out(investigation))

    # An overturn is the compensating action for the sustained decision, but it
    # does not undo the cascade.
    investigation["status"] = "OVERTURNED"
    investigation["penalty_points"] = 0
    investigation["disclosure_obligation"] = "NONE"
    touch(investigation)
    if journalist is not None:
        changed, _previous = calc.recompute_journalist_points(journalist)
        if changed:
            touch(journalist)
    if newsroom is not None:
        calc.emit_audit(newsroom["id"], "INVESTIGATION_OVERTURNED",
                        "MisconductInvestigation", investigation["id"],
                        actor.role, actor.user_id,
                        "Sustained finding overturned on appeal.")
        calc.recompute_posture(newsroom)
    return respond_object(ser.investigation_out(investigation))


@bp.route("/misconduct-investigations/<investigation_id>", methods=["GET"])
def read_investigation(investigation_id):
    auth(["StandardsEditor", "ExecutiveEditor"])
    return respond_object(ser.investigation_out(investigation_or_404(investigation_id)))


@bp.route("/misconduct-investigations", methods=["GET"])
def list_investigations():
    auth(["StandardsEditor", "ExecutiveEditor"])
    journalist_id = filter_param("journalist_id")
    story_id = filter_param("story_id")
    status = filter_param("status")
    allegation_type = filter_param("allegation_type")
    records = rows("investigations", lambda inv: (
        (journalist_id is None or inv["journalist_id"] == journalist_id)
        and (story_id is None or inv["story_id"] == story_id)
        and (status is None or inv["status"] == status)
        and (allegation_type is None or inv["allegation_type"] == allegation_type)))
    return paged(records, ser.investigation_out)
