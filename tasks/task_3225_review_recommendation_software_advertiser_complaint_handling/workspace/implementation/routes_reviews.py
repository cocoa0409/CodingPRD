"""Routes: reviews (submit, get, edit, evaluate, list)."""
from datetime import timedelta
from flask import Blueprint, request

from db import store, fmt_ts, parse_ts
from errors import not_found, err, invalid_request
from middleware import require_roles
from response import ok, ok_list, paginate
from services import (
    stamp_common, touch, get_body, req_int, req_str, compute_score,
    recompute_page_aggregates, set_review_state, pub,
    EDIT_WINDOW_H, REC_THRESHOLD,
)
from routes_core import ALL_ROLES
from routes_pages import get_page

bp = Blueprint("reviews", __name__)


def get_review(review_id):
    r = store.reviews.get(review_id)
    if r is None:
        raise not_found("review not found")
    return r


def _evaluate(review):
    """Run recommendation scoring and apply DISPLAYED/FILTERED transitions."""
    if review["recommendation_state"] == "REMOVED":
        raise err("ERR_INVALID_STATE", "cannot evaluate a REMOVED review")
    author = store.users.get(review["author_user_id"])
    score = compute_score(review, author)
    review["recommendation_score_x1000"] = score
    if score >= REC_THRESHOLD:
        if review["evidence_confirmed"]:
            raise err("ERR_REVIEW_EVIDENCE_LOCKED",
                      "evidence-confirmed review can never become DISPLAYED")
        if review["recommendation_state"] != "DISPLAYED":
            set_review_state(review, "DISPLAYED")
        else:
            touch(review)
    else:
        if review["recommendation_state"] != "FILTERED":
            set_review_state(review, "FILTERED")
        else:
            touch(review)
    return review


@bp.post("/platform/business-pages/<pageId>/reviews")
@require_roles("Reviewer")
def submit_review(pageId, _actor_id, _actor_role):
    page = get_page(pageId)
    body = get_body()
    rating = req_int(body, "rating", lo=1, hi=5)
    text = req_str(body, "text", min_len=20)
    # page-side: ACTIVE + no active cooldown alert
    if page["status"] != "ACTIVE":
        raise err("ERR_PAGE_NOT_ACTIVE", "page is not ACTIVE")
    for alert in store.alerts.values():
        if (alert["page_id"] == pageId and alert["status"] == "ACTIVE"
                and alert["_cooldown_dt"] > store.now):
            raise err("ERR_PAGE_NOT_ACTIVE",
                      "page is under an active consumer-alert review cooldown")
    # author status
    author = store.users.get(_actor_id)
    if author is None or author["status"] != "ACTIVE":
        raise err("ERR_USER_NOT_ACTIVE", "author is not ACTIVE")
    # solicitation prohibition
    if page["claimed_by_user_id"] == _actor_id:
        raise err("ERR_SOLICITATION_SUSPECT", "author is the page's claimed owner")
    for case in store.cases.values():
        if case["page_id"] != pageId or case["status"] not in ("OPEN", "INVESTIGATING"):
            continue
        for rid in case["target_review_ids"]:
            r = store.reviews.get(rid)
            if r is not None and r["author_user_id"] == _actor_id:
                raise err("ERR_SOLICITATION_SUSPECT",
                          "author has an open solicitation case on this page")
    review = stamp_common({
        "page_id": pageId,
        "author_user_id": _actor_id,
        "rating": rating,
        "text": text,
        "submitted_at": fmt_ts(store.now),
        "_submitted_dt": store.now,
        "edited_flag": False,
        "evidence_confirmed": False,
        "recommendation_state": "PENDING",
        "recommendation_score_x1000": 0,
    })
    store.reviews[review["id"]] = review
    # at-submission scoring (age_days == 0); initial placement out of PENDING
    # is part of creation, so the review itself is not re-versioned.
    score = compute_score(review, author)
    review["recommendation_score_x1000"] = score
    review["recommendation_state"] = "DISPLAYED" if score >= REC_THRESHOLD else "FILTERED"
    if score >= REC_THRESHOLD:
        recompute_page_aggregates(page)
        touch(page)
    return ok(pub(review), status=201)


@bp.get("/platform/reviews")
@require_roles(*ALL_ROLES)
def list_reviews(_actor_id, _actor_role):
    items = list(store.reviews.values())
    for f in ("page_id", "author_user_id"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r.get(f) == v]
    items, limit, offset, total = paginate([pub(r) for r in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/reviews/<reviewId>")
@require_roles(*ALL_ROLES)
def get_one_review(reviewId, _actor_id, _actor_role):
    return ok(pub(get_review(reviewId)))


@bp.patch("/platform/reviews/<reviewId>")
@require_roles("Reviewer")
def edit_review(reviewId, _actor_id, _actor_role):
    review = get_review(reviewId)
    body = get_body()
    rating = req_int(body, "rating", lo=1, hi=5)
    text = req_str(body, "text", min_len=20)
    if review["recommendation_state"] != "PENDING":
        raise err("ERR_INVALID_STATE", "only a PENDING review may be edited")
    if review["author_user_id"] != _actor_id:
        raise err("ERR_FORBIDDEN", "only the author may edit this review")
    if store.now > review["_submitted_dt"] + timedelta(hours=EDIT_WINDOW_H):
        raise err("ERR_EDIT_WINDOW_EXPIRED", "edit window (72h) has expired")
    review["rating"] = rating
    review["text"] = text
    review["edited_flag"] = True
    touch(review)
    return ok(pub(review))


@bp.post("/platform/reviews/<reviewId>/evaluate")
@require_roles("PlatformOps")
def evaluate_review(reviewId, _actor_id, _actor_role):
    review = get_review(reviewId)
    _evaluate(review)
    return ok(pub(review))
