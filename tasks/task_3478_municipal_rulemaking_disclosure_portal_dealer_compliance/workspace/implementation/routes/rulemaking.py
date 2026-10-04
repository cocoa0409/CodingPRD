"""Rule proposal lifecycle and comment letter endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import serializers
import services
import store
from errors import (
    ApiError,
    ERR_COMMENT_NOT_FOUND,
    ERR_COMMENT_PERIOD_STILL_OPEN,
    ERR_COMMENT_PERIOD_TOO_SHORT,
    ERR_COMMENT_WINDOW_CLOSED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PROPOSAL_NOT_FOUND,
    ERR_PROPOSAL_NOT_OPEN_FOR_COMMENT,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_UNRESOLVED_COMMENTS,
)
from respond import ok, ok_list
from validators import (
    get_body,
    opt_bool,
    opt_str,
    paginate,
    req_enum,
    req_int,
    req_nonempty_str,
    req_str,
    require_auth,
    require_role,
)

bp = Blueprint("rulemaking", __name__)

CATEGORIES = (
    "DEALER_CONDUCT",
    "ADVISOR_CONDUCT",
    "DISCLOSURE",
    "TRADE_REPORTING",
    "MARKET_DATA",
    "QUALIFICATION",
)
SENTIMENTS = ("SUPPORT", "OPPOSE", "NEUTRAL")
PROPOSAL_READ_ROLES = (
    "RulemakingOfficer",
    "Regulator",
    "PortalOperator",
    "ComplianceOfficer",
)
COMMENT_PERIOD_MIN_DAYS = 21
COMMENT_PERIOD_MAX_DAYS = 90


def _get_proposal(proposal_id):
    proposal = store.rule_proposals.get(proposal_id)
    if proposal is None:
        raise ApiError(ERR_PROPOSAL_NOT_FOUND, "Rule proposal not found.", 404)
    return proposal


@bp.route("/msrb/rule-proposals", methods=["POST"])
def create_proposal():
    _uid, role = require_auth()
    require_role(role, ("RulemakingOfficer",))
    body = get_body()
    rule_code = req_str(body, "rule_code")
    title = req_str(body, "title")
    rule_body = req_str(body, "body")
    category = req_enum(body, "category", CATEGORIES)
    supersedes_proposal_id = opt_str(body, "supersedes_proposal_id")
    for existing in store.rule_proposals.values():
        if existing["rule_code"] == rule_code:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "rule_code must be unique across all rule proposals.",
                400,
            )
    if supersedes_proposal_id is not None and (
        supersedes_proposal_id not in store.rule_proposals
    ):
        raise ApiError(
            ERR_PROPOSAL_NOT_FOUND, "supersedes_proposal_id does not exist.", 404
        )
    now = store.now()
    proposal = {
        "id": store.new_id(),
        "rule_code": rule_code,
        "title": title,
        "body": rule_body,
        "category": category,
        "supersedes_proposal_id": supersedes_proposal_id,
        "status": "DRAFT",
        "expedited": False,
        "comment_period_days": None,
        "comment_window_start": None,
        "comment_window_end": None,
        "comment_round": 0,
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "decision_reason": None,
        "approval_at": None,
        "effective_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.rule_proposals[proposal["id"]] = proposal
    return ok(serializers.rule_proposal(proposal), 201)


@bp.route("/msrb/rule-proposals", methods=["GET"])
def list_proposals():
    _uid, role = require_auth()
    require_role(role, PROPOSAL_READ_ROLES)
    items = list(store.rule_proposals.values())
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    category_filter = request.args.get("category")
    if category_filter is not None:
        items = [p for p in items if p["category"] == category_filter]
    supersedes_filter = request.args.get("supersedes_proposal_id")
    if supersedes_filter is not None:
        items = [
            p for p in items if p["supersedes_proposal_id"] == supersedes_filter
        ]
    items.sort(key=lambda p: p["created_at"])
    page, limit, offset, total = paginate(items)
    return ok_list(
        [serializers.rule_proposal(p) for p in page], limit, offset, total
    )


@bp.route("/msrb/rule-proposals/<proposal_id>", methods=["GET"])
def get_proposal(proposal_id):
    _uid, role = require_auth()
    require_role(role, PROPOSAL_READ_ROLES)
    return ok(serializers.rule_proposal(_get_proposal(proposal_id)), 200)


@bp.route("/msrb/rule-proposals/<proposal_id>", methods=["PATCH"])
def patch_proposal(proposal_id):
    _uid, role = require_auth()
    require_role(role, ("RulemakingOfficer",))
    body = get_body()
    expected_version = req_int(body, "expected_rule_proposal_version")
    title = opt_str(body, "title")
    new_body = opt_str(body, "body")
    category = None
    if "category" in body and body["category"] is not None:
        category = req_enum(body, "category", CATEGORIES)
    proposal = _get_proposal(proposal_id)
    if proposal["status"] not in ("DRAFT", "DISAPPROVED"):
        raise ApiError(
            ERR_INVALID_STATE,
            "A rule proposal may be edited only while DRAFT or DISAPPROVED.",
            409,
        )
    if expected_version != proposal["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_rule_proposal_version does not match the proposal's current version.",
            412,
        )
    if title is not None:
        proposal["title"] = title
    if new_body is not None:
        proposal["body"] = new_body
    if category is not None:
        proposal["category"] = category
    if proposal["status"] == "DISAPPROVED":
        # Revision cycle: reopen as DRAFT with a clean decision history.
        proposal["status"] = "DRAFT"
        proposal["submitted_by_user_id"] = None
        proposal["decided_by_user_id"] = None
        proposal["decision_reason"] = None
    services.bump(proposal)
    return ok(serializers.rule_proposal(proposal), 200)


@bp.route("/msrb/rule-proposals/<proposal_id>/open-comment-period", methods=["POST"])
def open_comment_period(proposal_id):
    _uid, role = require_auth()
    require_role(role, ("RulemakingOfficer",))
    body = get_body()
    comment_period_days = req_int(body, "comment_period_days")
    expedited = opt_bool(body, "expedited", False)
    proposal = _get_proposal(proposal_id)
    if proposal["status"] != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE,
            "A comment period can be opened only from DRAFT.",
            409,
        )
    if not (COMMENT_PERIOD_MIN_DAYS <= comment_period_days <= COMMENT_PERIOD_MAX_DAYS):
        raise ApiError(
            ERR_COMMENT_PERIOD_TOO_SHORT,
            "comment_period_days must be within [21, 90].",
            422,
        )
    now = store.now()
    proposal["comment_window_start"] = now
    proposal["comment_window_end"] = now + timedelta(days=comment_period_days)
    proposal["comment_period_days"] = comment_period_days
    proposal["expedited"] = expedited
    proposal["comment_round"] += 1
    proposal["status"] = "OPEN_FOR_COMMENT"
    services.bump(proposal)
    return ok(serializers.rule_proposal(proposal), 200)


@bp.route("/msrb/rule-proposals/<proposal_id>/submit-for-approval", methods=["POST"])
def submit_for_approval(proposal_id):
    uid, role = require_auth()
    require_role(role, ("RulemakingOfficer",))
    get_body()
    proposal = _get_proposal(proposal_id)
    if proposal["status"] != "OPEN_FOR_COMMENT":
        raise ApiError(
            ERR_INVALID_STATE,
            "Only an OPEN_FOR_COMMENT proposal can be submitted for approval.",
            409,
        )
    for letter in store.comment_letters.values():
        if letter["proposal_id"] == proposal_id and letter["status"] == "RECEIVED":
            raise ApiError(
                ERR_UNRESOLVED_COMMENTS,
                "Comment letters with status RECEIVED remain on this proposal.",
                409,
            )
    if store.now() < proposal["comment_window_end"]:
        raise ApiError(
            ERR_COMMENT_PERIOD_STILL_OPEN,
            "The comment window has not ended yet.",
            422,
        )
    proposal["status"] = "PENDING_APPROVAL"
    proposal["submitted_by_user_id"] = uid
    services.bump(proposal)
    return ok(serializers.rule_proposal(proposal), 200)


@bp.route("/msrb/rule-proposals/<proposal_id>/decide", methods=["POST"])
def decide_proposal(proposal_id):
    uid, role = require_auth()
    require_role(role, ("Regulator",))
    body = get_body()
    decision = req_enum(body, "decision", ("APPROVE", "DISAPPROVE"))
    reason = opt_str(body, "reason")
    proposal = _get_proposal(proposal_id)
    # Segregation of duties is evaluated before the generic state gate
    # (validation priority 6 < 7).
    if (
        proposal["submitted_by_user_id"] is not None
        and uid == proposal["submitted_by_user_id"]
    ):
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "The deciding Regulator must differ from the submitting officer.",
            403,
        )
    if proposal["status"] != "PENDING_APPROVAL":
        raise ApiError(
            ERR_INVALID_STATE,
            "Only a PENDING_APPROVAL proposal can be decided.",
            409,
        )
    proposal["decided_by_user_id"] = uid
    if decision == "APPROVE":
        proposal["status"] = "APPROVED"
        proposal["approval_at"] = store.now()
        delay_days = (
            services.EXPEDITED_DELAY_DAYS
            if proposal["expedited"]
            else services.STANDARD_DELAY_DAYS
        )
        proposal["effective_at"] = proposal["approval_at"] + timedelta(days=delay_days)
    else:
        proposal["status"] = "DISAPPROVED"
        proposal["decision_reason"] = reason
    services.bump(proposal)
    return ok(serializers.rule_proposal(proposal), 200)


@bp.route("/msrb/rule-proposals/<proposal_id>/comment-letters", methods=["POST"])
def create_comment_letter(proposal_id):
    _uid, role = require_auth()
    require_role(role, ("PublicReader",))
    body = get_body()
    author_name = req_str(body, "author_name")
    letter_body = req_nonempty_str(body, "body")
    sentiment = req_enum(body, "sentiment", SENTIMENTS)
    proposal = _get_proposal(proposal_id)
    if proposal["status"] != "OPEN_FOR_COMMENT":
        raise ApiError(
            ERR_PROPOSAL_NOT_OPEN_FOR_COMMENT,
            "The proposal is not OPEN_FOR_COMMENT.",
            409,
        )
    if not (store.now() < proposal["comment_window_end"]):
        raise ApiError(
            ERR_COMMENT_WINDOW_CLOSED,
            "The comment window is closed (half-open [start, end)).",
            422,
        )
    now = store.now()
    letter = {
        "id": store.new_id(),
        "proposal_id": proposal_id,
        "author_name": author_name,
        "body": letter_body,
        "sentiment": sentiment,
        "status": "RECEIVED",
        "moderation_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.comment_letters[letter["id"]] = letter
    return ok(serializers.comment_letter(letter), 201)


@bp.route("/msrb/rule-proposals/<proposal_id>/comment-letters", methods=["GET"])
def list_comment_letters(proposal_id):
    _uid, role = require_auth()
    require_role(role, PROPOSAL_READ_ROLES)
    _get_proposal(proposal_id)
    items = [
        c for c in store.comment_letters.values() if c["proposal_id"] == proposal_id
    ]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda c: c["created_at"])
    page, limit, offset, total = paginate(items)
    return ok_list(
        [serializers.comment_letter(c) for c in page], limit, offset, total
    )


@bp.route("/msrb/comment-letters/<letter_id>/moderate", methods=["POST"])
def moderate_comment_letter(letter_id):
    _uid, role = require_auth()
    require_role(role, ("PortalOperator",))
    body = get_body()
    action = req_enum(body, "action", ("PUBLISH", "DISMISS"))
    reason = None
    if action == "DISMISS":
        reason = req_nonempty_str(body, "reason")
    letter = store.comment_letters.get(letter_id)
    if letter is None:
        raise ApiError(ERR_COMMENT_NOT_FOUND, "Comment letter not found.", 404)
    if letter["status"] != "RECEIVED":
        raise ApiError(
            ERR_INVALID_STATE,
            "Only a RECEIVED comment letter can be moderated.",
            409,
        )
    if action == "PUBLISH":
        letter["status"] = "PUBLISHED"
    else:
        letter["status"] = "DISMISSED"
        letter["moderation_reason"] = reason
    services.bump(letter)
    return ok(serializers.comment_letter(letter), 200)
