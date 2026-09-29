"""Story files, publication and removal from the site."""

from decimal import Decimal

from flask import Blueprint

import calc
import serialize as ser
from auth import auth, require_ownership
from envelope import filter_param, paged, respond_object
from errors import ApiError
from helpers import newsroom_or_404, rows, story_or_404
from store import base_record, db, now, touch
from validation import i, read_raw_body, resolve_body_ids, s, validate_body

bp = Blueprint("stories", __name__)

ALL_ROLES = ["Reporter", "StandardsEditor", "LegalCounsel", "ExecutiveEditor", "PublicEditor"]

STORY_SPEC = {
    "newsroom_id": s(required=True),
    "lead_journalist_id": s(required=True),
    "headline": s(required=True, min_len=1, max_len=200),
    "defamation_claim_count": i(minimum=0, maximum=50, default=0),
    "privacy_subject_count": i(minimum=0, maximum=50, default=0),
    "unverified_document_count": i(minimum=0, maximum=50, default=0),
}

UNPUBLISH_SPEC = {
    "removal_reason": s(required=True, min_len=1, max_len=4000),
    "editors_note_text": s(required=True, min_len=1, max_len=4000),
}


@bp.route("/stories", methods=["POST"])
def create_story():
    actor = auth(["Reporter"])
    raw = read_raw_body()
    # Step 4: a reporter must name themselves as the story's lead journalist.
    proposed = raw.get("lead_journalist_id")
    if isinstance(proposed, str):
        require_ownership(actor, proposed)
    resolved = resolve_body_ids(raw, ["newsroom_id", "lead_journalist_id"])
    body = validate_body(raw, STORY_SPEC)
    newsroom = resolved["newsroom_id"]
    lead = resolved["lead_journalist_id"]
    if lead["employment_status"] != "ACTIVE":
        raise ApiError("ERR_JOURNALIST_SUSPENDED",
                       "A story cannot be opened in the name of a suspended reporter.")
    if lead["newsroom_id"] != newsroom["id"]:
        raise ApiError("ERR_CROSS_NEWSROOM_REFERENCE",
                       "The lead journalist does not belong to the story's newsroom.")
    story = base_record()
    story.update({
        "newsroom_id": newsroom["id"],
        "lead_journalist_id": lead["id"],
        "headline": body["headline"],
        "defamation_claim_count": body["defamation_claim_count"],
        "privacy_subject_count": body["privacy_subject_count"],
        "unverified_document_count": body["unverified_document_count"],
        "publication_status": "DRAFT",
        "standards_status": "CLEAN",
        "risk_index_estimate": Decimal("0.00"),
        "risk_index_actual": None,
        "risk_tier": "STANDARD",
        "approved_anonymous_source_count": 0,
        "revoked_anonymous_source_count": 0,
        "severe_correction_count": 0,
        "open_correction_request_count": 0,
        "published_at": None,
        "unpublished_at": None,
        "editors_note_text": None,
    })
    db.stories[story["id"]] = story
    calc.recompute_estimate(story)
    return respond_object(ser.story_out(story), 201)


@bp.route("/stories/<story_id>/publish", methods=["POST"])
def publish_story(story_id):
    actor = auth(["ExecutiveEditor"])
    story = story_or_404(story_id)
    if story["publication_status"] != "CLEARED":
        raise ApiError("ERR_STORY_NOT_CLEARED",
                       "Only a CLEARED story may be published.")
    newsroom = db.newsrooms.get(story["newsroom_id"])
    if newsroom is not None and newsroom["standards_posture"] == "LOCKDOWN":
        raise ApiError("ERR_POSTURE_LOCKDOWN",
                       "Publication is barred while the newsroom is in LOCKDOWN.")
    lead = db.journalists.get(story["lead_journalist_id"])
    if story["risk_tier"] == "HIGH" and not (lead and lead["training_current"]):
        raise ApiError("ERR_TRAINING_NOT_CURRENT",
                       "A HIGH risk-tier story requires a lead journalist with current training.")
    for approval in db.source_approvals.values():
        if approval["story_id"] == story["id"] and approval["status"] in ("REQUESTED", "REVOKED"):
            raise ApiError("ERR_SOURCE_NOT_APPROVED",
                           "An anonymous source of this story is unresolved or revoked.")
    if lead is not None and lead["employment_status"] != "ACTIVE":
        raise ApiError("ERR_JOURNALIST_SUSPENDED",
                       "The story's lead journalist is suspended.")

    story["publication_status"] = "PUBLISHED"
    story["published_at"] = now()
    calc.recompute_estimate(story)
    # Publication is the moment the retrospective index comes into existence.
    story["risk_index_actual"] = calc.risk_index_actual(story)
    touch(story)
    calc.emit_audit(story["newsroom_id"], "STORY_PUBLISHED", "Story", story["id"],
                    actor.role, actor.user_id,
                    "Story '%s' was published." % story["headline"])
    return respond_object(ser.story_out(story))


@bp.route("/stories/<story_id>/unpublish", methods=["POST"])
def unpublish_story(story_id):
    actor = auth(["ExecutiveEditor"])
    story = story_or_404(story_id)
    body = validate_body(read_raw_body(), UNPUBLISH_SPEC)
    if story["publication_status"] != "PUBLISHED":
        raise ApiError("ERR_STORY_NOT_PUBLISHED",
                       "Only a PUBLISHED story may be removed from the site.")
    sustained = any(inv["story_id"] == story["id"] and inv["status"] == "SUSTAINED"
                    for inv in db.investigations.values())
    if not sustained and story["severe_correction_count"] < 1:
        raise ApiError("ERR_UNPUBLISH_NOT_JUSTIFIED",
                       "Removal requires a sustained investigation or a severe correction.")

    story["publication_status"] = "UNPUBLISHED"
    story["standards_status"] = "RETRACTED"
    story["unpublished_at"] = now()
    story["editors_note_text"] = body["editors_note_text"]
    calc.recompute_actual(story)
    touch(story)
    calc.emit_audit(story["newsroom_id"], "STORY_UNPUBLISHED", "Story", story["id"],
                    actor.role, actor.user_id,
                    "Story '%s' was removed from the site." % story["headline"])
    return respond_object(ser.story_out(story))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@bp.route("/stories/<story_id>", methods=["GET"])
def read_story(story_id):
    auth(ALL_ROLES)
    return respond_object(ser.story_out(story_or_404(story_id)))


@bp.route("/stories", methods=["GET"])
def list_stories():
    auth(ALL_ROLES)
    newsroom_id = filter_param("newsroom_id")
    lead_journalist_id = filter_param("lead_journalist_id")
    publication_status = filter_param("publication_status")
    standards_status = filter_param("standards_status")
    risk_tier = filter_param("risk_tier")
    records = rows("stories", lambda st: (
        (newsroom_id is None or st["newsroom_id"] == newsroom_id)
        and (lead_journalist_id is None or st["lead_journalist_id"] == lead_journalist_id)
        and (publication_status is None or st["publication_status"] == publication_status)
        and (standards_status is None or st["standards_status"] == standards_status)
        and (risk_tier is None or st["risk_tier"] == risk_tier)))
    return paged(records, ser.story_out)


@bp.route("/stories/<story_id>/anonymous-source-approvals", methods=["GET"])
def list_story_approvals(story_id):
    auth(["Reporter", "StandardsEditor", "ExecutiveEditor"])
    story = story_or_404(story_id)
    status = filter_param("status")
    harm_risk = filter_param("harm_risk")
    records = rows("source_approvals", lambda a: (
        a["story_id"] == story["id"]
        and (status is None or a["status"] == status)
        and (harm_risk is None or a["harm_risk"] == harm_risk)))
    return paged(records, ser.source_approval_out)


@bp.route("/stories/<story_id>/pre-publication-reviews", methods=["GET"])
def list_story_reviews(story_id):
    auth(["Reporter", "StandardsEditor", "LegalCounsel", "ExecutiveEditor"])
    story = story_or_404(story_id)
    status = filter_param("status")
    records = rows("reviews", lambda r: (
        r["story_id"] == story["id"]
        and (status is None or r["status"] == status)))
    return paged(records, ser.review_out)


@bp.route("/stories/<story_id>/correction-requests", methods=["GET"])
def list_story_corrections(story_id):
    auth(["Reporter", "StandardsEditor", "ExecutiveEditor", "PublicEditor"])
    story = story_or_404(story_id)
    status = filter_param("status")
    submitter_type = filter_param("submitter_type")
    records = rows("corrections", lambda c: (
        c["story_id"] == story["id"]
        and (status is None or c["status"] == status)
        and (submitter_type is None or c["submitter_type"] == submitter_type)))
    return paged(records, ser.correction_out)
