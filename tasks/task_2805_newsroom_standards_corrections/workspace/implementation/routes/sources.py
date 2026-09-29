"""Anonymous-source authorisation: request, decide, revoke."""

from flask import Blueprint

import calc
import serialize as ser
from auth import auth, require_not_party, require_ownership
from envelope import respond_object
from errors import ApiError
from helpers import approval_or_404
from store import base_record, db, now, touch
from validation import (DECISIONS, HARM_RISKS, SOURCE_CATEGORIES, b, e, i,
                        read_raw_body, resolve_body_ids, s, validate_body)

bp = Blueprint("sources", __name__)

DOCUMENTATION_MIN_JUSTIFICATION = 20
SEVERE_CORROBORATION_MIN = 2

APPROVAL_SPEC = {
    "story_id": s(required=True),
    "source_alias": s(required=True, min_len=1, max_len=80),
    "source_category": e(SOURCE_CATEGORIES, required=True),
    "harm_risk": e(HARM_RISKS, required=True),
    "identity_known_to_editor": b(required=True),
    "corroboration_count": i(minimum=0, maximum=20, default=0),
    "justification_text": s(required=True, min_len=0, max_len=2000),
}

DECIDE_SPEC = {
    "decision": e(DECISIONS, required=True),
    "decision_note": s(min_len=0, max_len=4000),
}

REVOKE_SPEC = {
    "revocation_reason": s(required=True, min_len=1, max_len=4000),
}


@bp.route("/anonymous-source-approvals", methods=["POST"])
def create_approval():
    actor = auth(["Reporter"])
    raw = read_raw_body()
    # Step 4: the request must be filed by the lead journalist of its story.
    proposed = raw.get("story_id")
    if isinstance(proposed, str):
        story = db.stories.get(proposed)
        if story is not None:
            require_ownership(actor, story["lead_journalist_id"])
    resolved = resolve_body_ids(raw, ["story_id"])
    body = validate_body(raw, APPROVAL_SPEC)
    story = resolved["story_id"]
    for other in db.source_approvals.values():
        if other["story_id"] == story["id"] and other["source_alias"] == body["source_alias"]:
            raise ApiError("ERR_DUPLICATE_SOURCE_ALIAS",
                           "This story already carries an approval with that source alias.")
    approval = base_record()
    approval.update({
        "story_id": story["id"],
        "source_alias": body["source_alias"],
        "source_category": body["source_category"],
        "harm_risk": body["harm_risk"],
        "identity_known_to_editor": body["identity_known_to_editor"],
        "corroboration_count": body["corroboration_count"],
        "justification_text": body["justification_text"],
        "documentation_complete": bool(
            body["identity_known_to_editor"]
            and len(body["justification_text"]) >= DOCUMENTATION_MIN_JUSTIFICATION),
        "status": "REQUESTED",
        "decided_by_user_id": None,
        "decided_at": None,
        "revocation_reason": None,
    })
    db.source_approvals[approval["id"]] = approval
    return respond_object(ser.source_approval_out(approval), 201)


@bp.route("/anonymous-source-approvals/<approval_id>/decide", methods=["POST"])
def decide_approval(approval_id):
    actor = auth(["StandardsEditor", "ExecutiveEditor"])
    approval = approval_or_404(approval_id)
    story = db.stories.get(approval["story_id"])
    # Step 5: the author of the story may not decide its own anonymous source.
    if story is not None:
        require_not_party(actor, [story["lead_journalist_id"]])
    body = validate_body(read_raw_body(), DECIDE_SPEC)
    if approval["status"] != "REQUESTED":
        raise ApiError("ERR_SOURCE_ALREADY_DECIDED",
                       "This anonymous-source request has already been decided.")

    if body["decision"] == "APPROVE":
        if not approval["documentation_complete"]:
            raise ApiError("ERR_INSUFFICIENT_SOURCE_DOCUMENTATION",
                           "Approval requires complete source documentation.")
        if (approval["harm_risk"] == "SEVERE"
                and approval["corroboration_count"] < SEVERE_CORROBORATION_MIN):
            raise ApiError("ERR_INSUFFICIENT_CORROBORATION",
                           "A SEVERE harm-risk source requires at least two corroborating sources.")
        approval["status"] = "APPROVED"
    else:
        approval["status"] = "DENIED"
    approval["decided_by_user_id"] = actor.user_id
    approval["decided_at"] = now()
    touch(approval)

    if story is not None:
        if approval["status"] == "APPROVED":
            story["approved_anonymous_source_count"] += 1
            calc.recompute_estimate(story)
            calc.recompute_actual(story)
        touch(story)
        event_type = "SOURCE_APPROVED" if approval["status"] == "APPROVED" else "SOURCE_DENIED"
        calc.emit_audit(story["newsroom_id"], event_type, "AnonymousSourceApproval",
                        approval["id"], actor.role, actor.user_id,
                        "Anonymous source '%s' was %s." % (
                            approval["source_alias"], approval["status"].lower()))
    return respond_object(ser.source_approval_out(approval))


@bp.route("/anonymous-source-approvals/<approval_id>/revoke", methods=["POST"])
def revoke_approval(approval_id):
    actor = auth(["StandardsEditor", "ExecutiveEditor"])
    approval = approval_or_404(approval_id)
    body = validate_body(read_raw_body(), REVOKE_SPEC)
    if approval["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE",
                       "Revocation is only available from an APPROVED source approval.")

    approval["status"] = "REVOKED"
    approval["revocation_reason"] = body["revocation_reason"]
    touch(approval)

    story = db.stories.get(approval["story_id"])
    if story is not None:
        story["approved_anonymous_source_count"] = max(
            0, story["approved_anonymous_source_count"] - 1)
        story["revoked_anonymous_source_count"] += 1
        calc.recompute_estimate(story)
        calc.recompute_actual(story)
        if story["standards_status"] in ("CLEAN", "CORRECTED"):
            story["standards_status"] = "UNDER_INQUIRY"
        touch(story)
        calc.emit_audit(story["newsroom_id"], "SOURCE_REVOKED", "AnonymousSourceApproval",
                        approval["id"], actor.role, actor.user_id,
                        "Anonymous source '%s' was revoked." % approval["source_alias"])
    return respond_object(ser.source_approval_out(approval))


@bp.route("/anonymous-source-approvals/<approval_id>", methods=["GET"])
def read_approval(approval_id):
    auth(["Reporter", "StandardsEditor", "ExecutiveEditor"])
    return respond_object(ser.source_approval_out(approval_or_404(approval_id)))
