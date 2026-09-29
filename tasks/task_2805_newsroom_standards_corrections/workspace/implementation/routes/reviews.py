"""The pre-publication review cycle: submit, verdicts, clear, resubmit."""

from flask import Blueprint

import calc
import serialize as ser
from auth import auth, require_ownership
from envelope import respond_object
from errors import ApiError
from helpers import review_or_404
from store import base_record, db, now, touch
from validation import (VERDICTS, b, e, i, read_raw_body, resolve_body_ids, s,
                        validate_body)

bp = Blueprint("reviews", __name__)

MAX_ROUNDS = 3

SUBMIT_SPEC = {
    "story_id": s(required=True),
    "expected_story_version": i(required=True),
    "high_risk_declared": b(default=False),
    "submission_note": s(min_len=0, max_len=4000),
}

LEGAL_SPEC = {
    "legal_verdict": e(VERDICTS, required=True),
    "defamation_findings": i(required=True, minimum=0, maximum=50),
    "privacy_findings": i(required=True, minimum=0, maximum=50),
    "findings_note": s(min_len=0, max_len=4000),
}

STANDARDS_SPEC = {
    "standards_verdict": e(VERDICTS, required=True),
    "findings_note": s(min_len=0, max_len=4000),
}

RESUBMIT_SPEC = {"revision_note": s(min_len=0, max_len=4000)}


def _send_story_back(review, story):
    """The three consequences shared by every CHANGES_REQUIRED and BLOCK."""
    if story is not None:
        if story["publication_status"] == "IN_REVIEW":
            story["publication_status"] = "DRAFT"
        touch(story)
    calc.close_review_assignments(review["id"], "CANCELLED")


@bp.route("/pre-publication-reviews", methods=["POST"])
def submit_review():
    actor = auth(["Reporter"])
    raw = read_raw_body()
    # Step 4: only the story's lead journalist may open a round.
    proposed = raw.get("story_id")
    if isinstance(proposed, str):
        story = db.stories.get(proposed)
        if story is not None:
            require_ownership(actor, story["lead_journalist_id"])
    resolved = resolve_body_ids(raw, ["story_id"])
    body = validate_body(raw, SUBMIT_SPEC)
    story = resolved["story_id"]
    if body["expected_story_version"] != story["version"]:
        raise ApiError("ERR_STALE_STORY_VERSION",
                       "expected_story_version does not match the story's current version.")
    if story["publication_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "A review round may only be opened from a DRAFT story.")
    lead = db.journalists.get(story["lead_journalist_id"])
    if lead is not None and lead["employment_status"] != "ACTIVE":
        raise ApiError("ERR_JOURNALIST_SUSPENDED",
                       "The story's lead journalist is suspended.")

    # The estimate is refreshed first, so the pinned track reflects the tier
    # the desk is actually looking at.
    calc.recompute_estimate(story)
    review = base_record()
    review.update({
        "story_id": story["id"],
        "high_risk_declared": bool(body["high_risk_declared"]),
        "submission_note": body["submission_note"],
        "requires_legal_review": bool(body["high_risk_declared"]) or story["risk_tier"] == "HIGH",
        "review_round": 1,
        "status": "SUBMITTED",
        "legal_verdict": None,
        "standards_verdict": None,
        "defamation_findings": 0,
        "privacy_findings": 0,
        "cleared_at": None,
    })
    db.reviews[review["id"]] = review
    story["publication_status"] = "IN_REVIEW"
    touch(story)
    return respond_object(ser.review_out(review), 201)


@bp.route("/pre-publication-reviews/<review_id>/legal-verdict", methods=["POST"])
def legal_verdict(review_id):
    auth(["LegalCounsel"])
    review = review_or_404(review_id)
    body = validate_body(read_raw_body(), LEGAL_SPEC)
    if not review["requires_legal_review"]:
        raise ApiError("ERR_INVALID_STATE",
                       "This round does not require legal review.")
    if review["status"] != "SUBMITTED":
        raise ApiError("ERR_REVIEW_ROUND_NOT_OPEN",
                       "A legal verdict may only be recorded on a SUBMITTED round.")

    review["legal_verdict"] = body["legal_verdict"]
    review["defamation_findings"] = body["defamation_findings"]
    review["privacy_findings"] = body["privacy_findings"]
    story = db.stories.get(review["story_id"])
    if body["legal_verdict"] == "PASS":
        review["status"] = "LEGAL_CLEARED"
        touch(review)
    elif body["legal_verdict"] == "CHANGES_REQUIRED":
        review["status"] = "CHANGES_REQUESTED"
        touch(review)
        _send_story_back(review, story)
    else:
        review["status"] = "BLOCKED"
        touch(review)
        _send_story_back(review, story)
    return respond_object(ser.review_out(review))


@bp.route("/pre-publication-reviews/<review_id>/standards-verdict", methods=["POST"])
def standards_verdict(review_id):
    auth(["StandardsEditor", "ExecutiveEditor"])
    review = review_or_404(review_id)
    body = validate_body(read_raw_body(), STANDARDS_SPEC)
    # The standards track declares consequences for PASS and CHANGES_REQUIRED
    # only; a standards BLOCK has no declared transition.
    if body["standards_verdict"] == "BLOCK":
        raise ApiError("ERR_INVALID_STATE",
                       "A standards BLOCK has no declared transition.")
    if review["status"] not in ("SUBMITTED", "LEGAL_CLEARED"):
        raise ApiError("ERR_REVIEW_ROUND_NOT_OPEN",
                       "This round is closed to further verdicts.")
    if review["requires_legal_review"] and review["status"] == "SUBMITTED":
        raise ApiError("ERR_LEGAL_VERDICT_REQUIRED",
                       "The legal verdict must be recorded before the standards verdict.")

    review["standards_verdict"] = body["standards_verdict"]
    story = db.stories.get(review["story_id"])
    if body["standards_verdict"] == "PASS":
        review["status"] = "STANDARDS_CLEARED"
        touch(review)
    else:
        review["status"] = "CHANGES_REQUESTED"
        touch(review)
        _send_story_back(review, story)
    return respond_object(ser.review_out(review))


@bp.route("/pre-publication-reviews/<review_id>/clear", methods=["POST"])
def clear_review(review_id):
    actor = auth(["StandardsEditor", "ExecutiveEditor"])
    review = review_or_404(review_id)
    if review["status"] != "STANDARDS_CLEARED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a STANDARDS_CLEARED round may be closed out.")
    story = db.stories.get(review["story_id"])
    newsroom = db.newsrooms.get(story["newsroom_id"]) if story else None
    if newsroom is not None:
        if newsroom["standards_posture"] == "LOCKDOWN":
            raise ApiError("ERR_POSTURE_LOCKDOWN",
                           "Clearing is barred while the newsroom is in LOCKDOWN.")
        if (newsroom["standards_posture"] == "HEIGHTENED"
                and actor.role != "ExecutiveEditor"):
            raise ApiError("ERR_HEIGHTENED_REQUIRES_EXEC",
                           "Under HEIGHTENED posture only an ExecutiveEditor may clear.")

    review["status"] = "CLEARED"
    review["cleared_at"] = now()
    touch(review)
    if story is not None:
        if story["publication_status"] == "IN_REVIEW":
            story["publication_status"] = "CLEARED"
        touch(story)
    # A successful terminus completes the bookings instead of cancelling them.
    calc.close_review_assignments(review["id"], "COMPLETED")
    if story is not None:
        # StandardsAuditEvent.subject_type has no PrePublicationReview member,
        # so the cleared round is logged against its story.
        calc.emit_audit(story["newsroom_id"], "REVIEW_CLEARED", "Story", story["id"],
                        actor.role, actor.user_id,
                        "Review round %d cleared story '%s' for publication."
                        % (review["review_round"], story["headline"]))
    return respond_object(ser.review_out(review))


@bp.route("/pre-publication-reviews/<review_id>/resubmit", methods=["POST"])
def resubmit_review(review_id):
    actor = auth(["Reporter"])
    review = review_or_404(review_id)
    story = db.stories.get(review["story_id"])
    # Step 4: only the story's lead journalist may revive the round.
    if story is not None:
        require_ownership(actor, story["lead_journalist_id"])
    validate_body(read_raw_body(), RESUBMIT_SPEC)
    if review["status"] != "CHANGES_REQUESTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a CHANGES_REQUESTED round may be resubmitted.")
    if review["review_round"] >= MAX_ROUNDS:
        raise ApiError("ERR_INVALID_STATE",
                       "The revision cycle is bounded at three rounds.")
    lead = db.journalists.get(story["lead_journalist_id"]) if story else None
    if lead is not None and lead["employment_status"] != "ACTIVE":
        raise ApiError("ERR_JOURNALIST_SUSPENDED",
                       "The story's lead journalist is suspended.")

    review["status"] = "SUBMITTED"
    review["review_round"] += 1
    review["legal_verdict"] = None
    review["standards_verdict"] = None
    touch(review)
    if story is not None:
        story["publication_status"] = "IN_REVIEW"
        calc.recompute_estimate(story)
        touch(story)
    return respond_object(ser.review_out(review))


@bp.route("/pre-publication-reviews/<review_id>", methods=["GET"])
def read_review(review_id):
    auth(["Reporter", "StandardsEditor", "LegalCounsel", "ExecutiveEditor"])
    return respond_object(ser.review_out(review_or_404(review_id)))
