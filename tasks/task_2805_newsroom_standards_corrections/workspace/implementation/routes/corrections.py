"""Correction intake, investigation, adjudication and the published notice."""

from flask import Blueprint

import calc
import serialize as ser
from auth import auth, require_not_party
from envelope import respond_object
from errors import ApiError
from helpers import correction_or_404
from store import base_record, db, now, touch
from validation import (ERROR_CATEGORIES, OUTCOME_TYPES, SUBMITTER_TYPES, b, e,
                        i, read_raw_body, resolve_body_ids, s, validate_body)

bp = Blueprint("corrections", __name__)

INTAKE_SPEC = {
    "story_id": s(required=True),
    "submitter_type": e(SUBMITTER_TYPES, required=True),
    "submitter_email": s(required=True, min_len=1, max_len=320, contains="@"),
    "claim_text": s(required=True, min_len=1, max_len=4000),
    "claimed_error_category": e(ERROR_CATEGORIES, required=True),
    "reader_reported_reach": i(minimum=0, default=0),
    "subject_named": b(default=False),
}

START_SPEC = {"assigned_note": s(min_len=0, max_len=4000)}

OUTREACH_SPEC = {
    "outreach_channel": s(required=True, min_len=1, max_len=200),
    "outreach_note": s(min_len=0, max_len=4000),
}

ADJUDICATE_SPEC = {
    "outcome_type": e(OUTCOME_TYPES, required=True),
    "adjudicated_error_category": e(ERROR_CATEGORIES, required=True),
    "verified_reach": i(required=True, minimum=0),
    "notice_text": s(min_len=1, max_len=4000),
}

RESOLVE_SPEC = {"resolution_note": s(min_len=0, max_len=4000)}

NOTICE_OUTCOMES = ("CORRECTION", "CLARIFICATION", "UPDATE", "EDITORS_NOTE")


@bp.route("/correction-requests", methods=["POST"])
def create_correction():
    auth(["PublicEditor", "StandardsEditor"])
    raw = read_raw_body()
    resolved = resolve_body_ids(raw, ["story_id"])
    body = validate_body(raw, INTAKE_SPEC)
    story = resolved["story_id"]
    if story["standards_status"] not in ("CLEAN", "CORRECTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Intake is admissible only while the story is CLEAN or CORRECTED.")

    # The provisional grading runs from the complainant's own account.
    score, band = calc.severity_score(body["claimed_error_category"],
                                      body["reader_reported_reach"],
                                      body["submitter_type"] == "SUBJECT")
    newsroom = db.newsrooms.get(story["newsroom_id"])
    sla_hours = newsroom["correction_response_sla_hours"] if newsroom else 72
    correction = base_record()
    correction.update({
        "story_id": story["id"],
        "submitter_type": body["submitter_type"],
        "submitter_email": body["submitter_email"],
        "claim_text": body["claim_text"],
        "claimed_error_category": body["claimed_error_category"],
        "reader_reported_reach": body["reader_reported_reach"],
        "subject_named": bool(body["subject_named"]),
        "provisional_severity_score": score,
        "provisional_severity_band": band,
        "adjudicated_error_category": None,
        "verified_reach": None,
        "adjudicated_severity_score": None,
        "adjudicated_severity_band": None,
        "outcome_type": None,
        "placement": None,
        "notice_text": None,
        "notice_published_at": None,
        # Pinned once, at intake, and never recomputed.
        "response_due_at": calc.response_due_at(sla_hours, band,
                                                body["submitter_type"], now()),
        "breach_flag": False,
        "status": "INTAKE",
        "resolved_at": None,
    })
    db.corrections[correction["id"]] = correction

    story["standards_status"] = "UNDER_INQUIRY"
    story["open_correction_request_count"] += 1
    touch(story)
    return respond_object(ser.correction_out(correction), 201)


@bp.route("/correction-requests/<request_id>/start-investigation", methods=["POST"])
def start_investigation(request_id):
    auth(["PublicEditor", "StandardsEditor"])
    correction = correction_or_404(request_id)
    validate_body(read_raw_body(), START_SPEC)
    if correction["status"] != "INTAKE":
        raise ApiError("ERR_INVALID_STATE",
                       "The investigation may only be opened from INTAKE.")
    correction["status"] = "INVESTIGATING"
    touch(correction)
    return respond_object(ser.correction_out(correction))


@bp.route("/correction-requests/<request_id>/subject-outreach", methods=["POST"])
def subject_outreach(request_id):
    auth(["PublicEditor"])
    correction = correction_or_404(request_id)
    validate_body(read_raw_body(), OUTREACH_SPEC)
    if correction["status"] != "INVESTIGATING":
        raise ApiError("ERR_INVALID_STATE",
                       "Outreach is only available from INVESTIGATING.")
    correction["status"] = "AWAITING_SUBJECT"
    touch(correction)
    return respond_object(ser.correction_out(correction))


@bp.route("/correction-requests/<request_id>/adjudicate", methods=["POST"])
def adjudicate_correction(request_id):
    actor = auth(["StandardsEditor", "ExecutiveEditor"])
    correction = correction_or_404(request_id)
    story = db.stories.get(correction["story_id"])
    # Step 5: the adjudicator must not be the story's lead journalist.
    if story is not None:
        require_not_party(actor, [story["lead_journalist_id"]])
    body = validate_body(read_raw_body(), ADJUDICATE_SPEC)
    if correction["status"] not in ("INVESTIGATING", "AWAITING_SUBJECT"):
        raise ApiError("ERR_CORRECTION_NOT_INVESTIGATED",
                       "The request must be INVESTIGATING or AWAITING_SUBJECT.")
    outcome = body["outcome_type"]
    notice_text = body["notice_text"]
    if outcome in NOTICE_OUTCOMES and notice_text is None:
        raise ApiError("ERR_NOTICE_TEXT_REQUIRED",
                       "notice_text is required for a published notice.")
    if outcome == "NO_ACTION" and notice_text is not None:
        raise ApiError("ERR_NOTICE_TEXT_REQUIRED",
                       "notice_text must be absent for a NO_ACTION outcome.")

    # The adjudicated grading runs from the desk's verified account.
    score, band = calc.severity_score(body["adjudicated_error_category"],
                                      body["verified_reach"],
                                      bool(correction["subject_named"]))
    correction["adjudicated_error_category"] = body["adjudicated_error_category"]
    correction["verified_reach"] = body["verified_reach"]
    correction["outcome_type"] = outcome
    newsroom = db.newsrooms.get(story["newsroom_id"]) if story else None

    if outcome != "NO_ACTION":
        correction["adjudicated_severity_score"] = score
        correction["adjudicated_severity_band"] = band
        correction["placement"] = calc.placement_for(outcome, band)
        correction["notice_text"] = notice_text
        correction["status"] = "ADJUDICATED"
        touch(correction)
        if story is not None:
            story["standards_status"] = "CORRECTED"
            if band in ("MAJOR", "SEVERE"):
                story["severe_correction_count"] += 1
                calc.recompute_actual(story)
            touch(story)
        if newsroom is not None:
            calc.recompute_posture(newsroom)
        if story is not None:
            calc.emit_audit(story["newsroom_id"], "CORRECTION_ADJUDICATED",
                            "CorrectionRequest", correction["id"], actor.role,
                            actor.user_id,
                            "Correction request adjudicated as %s (%s)." % (outcome, band))
    else:
        # The dismissal branch is strictly smaller: no notice, no severe
        # counter, no posture cascade.
        correction["adjudicated_severity_score"] = score
        correction["adjudicated_severity_band"] = band
        correction["placement"] = None
        correction["status"] = "DISMISSED"
        touch(correction)
        if story is not None:
            was_open = story["open_correction_request_count"]
            story["open_correction_request_count"] = max(0, was_open - 1)
            if was_open == 1 and story["severe_correction_count"] == 0:
                story["standards_status"] = "CLEAN"
            touch(story)
    return respond_object(ser.correction_out(correction))


@bp.route("/correction-requests/<request_id>/resolve", methods=["POST"])
def resolve_correction(request_id):
    actor = auth(["PublicEditor", "StandardsEditor", "ExecutiveEditor"])
    correction = correction_or_404(request_id)
    validate_body(read_raw_body(), RESOLVE_SPEC)
    if correction["status"] != "ADJUDICATED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an ADJUDICATED request may be closed out.")

    instant = now()
    correction["status"] = "RESOLVED"
    correction["notice_published_at"] = instant
    correction["resolved_at"] = instant
    touch(correction)
    story = db.stories.get(correction["story_id"])
    if story is not None:
        story["open_correction_request_count"] = max(
            0, story["open_correction_request_count"] - 1)
        touch(story)
        calc.emit_audit(story["newsroom_id"], "CORRECTION_RESOLVED",
                        "CorrectionRequest", correction["id"], actor.role,
                        actor.user_id, "Correction notice published and request resolved.")
        newsroom = db.newsrooms.get(story["newsroom_id"])
        if newsroom is not None:
            # The request has left the high-severity pool, so the posture may
            # fall back.
            calc.recompute_posture(newsroom)
    return respond_object(ser.correction_out(correction))


@bp.route("/correction-requests/<request_id>", methods=["GET"])
def read_correction(request_id):
    auth(["Reporter", "StandardsEditor", "ExecutiveEditor", "PublicEditor"])
    return respond_object(ser.correction_out(correction_or_404(request_id)))
