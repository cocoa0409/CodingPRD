"""Advisory committee review: opening, closing and comment records."""

from flask import Blueprint, request

import auth
import parsers as P
import resolvers as R
import store
from clock import logical_now
from errors import (
    ERR_ADVISORY_REVIEW_INCOMPLETE,
    ERR_ADVISORY_REVIEW_NOT_READY,
    ERR_INVALID_STATE,
    ApiError,
)
from response import object_response
from routes.common import guard, list_response, one
from services import changes as CH
from services import credits as CR
from services import votes as VT

bp = Blueprint("committee", __name__)

REVIEWERS = (auth.COMMITTEE_REVIEWER,)
READERS = (auth.COMMITTEE_REVIEWER, auth.EDITORIAL_STAFF, auth.EDITORIAL_PANEL_CHAIR)

REVIEWABLE_TIERS = ("TIER_I", "TIER_II", "TIER_III")
COMMITTEE_NAMES = ("CPT_ADVISOR", "CPT_ASSISTANT", "HCPAC", "RUC_HEALTH_CARE_PROFESSIONALS")
RECOMMENDATIONS = ("RECOMMEND_APPROVE", "RECOMMEND_REJECT", "RECOMMEND_MODIFY")


@bp.post("/advisory-committee-reviews")
@guard(REVIEWERS)
def open_review(actor):
    data = P.body()
    change = R.code_change(P.text_or_none(data.get("change_id")) or "")

    # Reviewability conditions are evaluated first, so ERR_ADVISORY_REVIEW_NOT_READY
    # is reported in preference to ERR_SUPPORT_DATA_REQUIRED.
    if change.get("clinical_evidence_tier") not in REVIEWABLE_TIERS:
        raise ApiError(ERR_ADVISORY_REVIEW_NOT_READY,
                       "a TIER_IV change is not reviewable")
    if change.get("administrative_review_status") != "UNDER_ADMIN_REVIEW":
        raise ApiError(ERR_ADVISORY_REVIEW_NOT_READY,
                       "administrative screening has already completed")

    if not CH.support_data_present(change):
        CH.support_data_error()

    review = store.create(store.committee_reviews, {
        "change_id": change["id"],
        "committee_name": P.text(data.get("committee_name")),
        "recommendation": P.text_or_none(data.get("recommendation")),
        "quorum_met": P.boolean(data.get("quorum_met"), False),
        "yes_votes": P.integer(data.get("yes_votes"), 0),
        "no_votes": P.integer(data.get("no_votes"), 0),
        "vote_percent": None,
        "decision": "PENDING",
        "review_status": "OPEN",
        "reviewed_at": None,
    })
    return object_response(one(review), 201)


@bp.get("/advisory-committee-reviews")
@guard(READERS)
def list_reviews(actor):
    rows = store.sorted_rows(store.committee_reviews)
    for field in ("change_id", "committee_name"):
        wanted = request.args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    return list_response(rows)


@bp.get("/advisory-committee-reviews/<review_id>")
@guard(READERS)
def read_review(actor, review_id):
    return object_response(one(R.committee_review(review_id)))


@bp.get("/committee-reviews/<review_id>")
@guard(READERS)
def read_review_by_review_id(actor, review_id):
    return object_response(one(R.committee_review(review_id)))


@bp.get("/code-changes/<change_id>/committee-reviews")
@guard(READERS)
def list_change_reviews(actor, change_id):
    change = R.code_change(change_id)
    rows = [r for r in store.sorted_rows(store.committee_reviews)
            if r.get("change_id") == change["id"]]
    return list_response(rows)


@bp.post("/committee-reviews/<review_id>/decisions")
@guard(REVIEWERS)
def close_review(actor, review_id):
    review = R.committee_review(review_id)
    data = P.body()

    recommendation = data.get("recommendation")
    if not bool(review.get("quorum_met")):
        raise ApiError(ERR_ADVISORY_REVIEW_INCOMPLETE, "the committee did not achieve quorum")
    total = int(review.get("yes_votes") or 0) + int(review.get("no_votes") or 0)
    if total <= 0:
        raise ApiError(ERR_ADVISORY_REVIEW_INCOMPLETE, "no ballots were cast")
    if recommendation not in RECOMMENDATIONS:
        raise ApiError(ERR_ADVISORY_REVIEW_INCOMPLETE,
                       "the committee's recommendation must be supplied")
    if review.get("review_status") != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "review is not open")

    pct = VT.committee_recommendation_vote(review.get("yes_votes"), review.get("no_votes"))
    review["vote_percent"] = float(pct) if pct is not None else None
    review["decision"] = VT.committee_recommendation_status(pct)
    review["recommendation"] = recommendation
    review["review_status"] = "COMPLETE"
    review["reviewed_at"] = logical_now()
    store.bump(review)

    change = store.code_changes.get(review.get("change_id"))
    if change is not None:
        CR.recompute_for_change(change)
        store.bump(change)
    return object_response(one(review), 200)


@bp.post("/advisory-committee-reviews/<review_id>/comment-records")
@guard(REVIEWERS)
def record_comment_consideration(actor, review_id):
    review = R.committee_review(review_id)
    data = P.body()
    review["comment_count_considered"] = P.integer(data.get("comment_count_considered"), 0)
    review["notes"] = P.text_or_none(data.get("notes"))
    # Recording advances the review's version but does not alter its decision.
    store.bump(review)
    return object_response(one(review), 200)