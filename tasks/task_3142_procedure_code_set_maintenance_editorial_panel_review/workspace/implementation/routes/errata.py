"""Errata correction, its proration arithmetic and the review that can reverse it."""

from flask import Blueprint, request

import auth
import parsers as P
import resolvers as R
import store
from clock import logical_now
from errors import (
    ERR_CORRECTION_INVALID,
    ERR_ERRATA_WINDOW_CLOSED,
    ERR_INVALID_STATE,
    ERR_UNAUTHORIZED,
    ApiError,
)
from money import cents, dec, round_half_up
from response import object_response
from routes.common import guard, list_response, one
from services import valuation as VA

bp = Blueprint("errata", __name__)

STAFF = (auth.EDITORIAL_STAFF,)
CHAIR = (auth.EDITORIAL_PANEL_CHAIR,)
READERS = (auth.EDITORIAL_STAFF, auth.LICENSING_OFFICER, auth.EDITORIAL_PANEL_CHAIR)
NOTICE_READERS = (auth.EDITORIAL_STAFF, auth.LICENSING_OFFICER)
REVIEW_READERS = (auth.EDITORIAL_PANEL_CHAIR, auth.EDITORIAL_STAFF)

REVIEW_OUTCOMES = ("UPHELD", "REVERSED")


def _cycle_for_code_value(code_value):
    release_id = code_value.get("release_id") if code_value else None
    return store.release_cycles.get(release_id) if release_id else None


def _valid_ratio(value):
    """A corrected proration ratio must sit strictly between zero and one."""
    if value is None or value == "":
        return False
    try:
        ratio = dec(value)
    except Exception:
        return False
    return ratio > 0 and ratio < 1


@bp.post("/errata-notices")
@guard(STAFF)
def propose_notice(actor):
    data = P.body()
    code_value = R.code_value(P.text_or_none(data.get("code_value_id")) or "")

    notice = store.create(store.errata_notices, {
        "code_value_id": code_value["id"],
        "errata_effective_date": P.dt(data.get("errata_effective_date")),
        "prior_facility_payment_cents": P.integer(
            data.get("prior_facility_payment_cents"), 0
        ),
        "corrected_facility_payment_cents": 0,
        "proration_numerator_days": 0,
        "proration_denominator_days": 0,
        "reason": P.text_or_none(data.get("reason")),
        "status": "PROPOSED",
        "published_at": None,
    })
    VA.errata_proration(notice, code_value)
    return object_response(one(notice), 201)


@bp.get("/errata-notices")
@guard(READERS)
def list_notices(actor):
    rows = store.sorted_rows(store.errata_notices)
    args = request.args
    for field in ("status", "code_value_id"):
        wanted = args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    from_at = P.dt(args.get("errata_effective_date_from"))
    to_at = P.dt(args.get("errata_effective_date_to"))
    if from_at is not None:
        rows = [r for r in rows
                if r.get("errata_effective_date") is not None
                and r["errata_effective_date"] >= from_at]
    if to_at is not None:
        rows = [r for r in rows
                if r.get("errata_effective_date") is not None
                and r["errata_effective_date"] <= to_at]
    return list_response(rows)


@bp.get("/errata-notices/<notice_id>")
@guard(READERS)
def read_notice(actor, notice_id):
    return object_response(one(R.errata_notice(notice_id)))


@bp.get("/code-values/<value_id>/errata-notices")
@guard(NOTICE_READERS)
def list_value_notices(actor, value_id):
    value = R.code_value(value_id)
    rows = [n for n in store.sorted_rows(store.errata_notices)
            if n.get("code_value_id") == value["id"]]
    return list_response(rows)


@bp.post("/errata-notices/<notice_id>/publications")
@guard(STAFF)
def publish_notice(actor, notice_id):
    notice = R.errata_notice(notice_id)
    code_value = store.code_values.get(notice.get("code_value_id"))
    if code_value is None:
        from errors import ERR_NOT_FOUND

        raise ApiError(ERR_NOT_FOUND, "the named code value not found")
    if notice.get("status") != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, "the notice is not in a proposable state")

    effective = notice.get("errata_effective_date")
    value_effective = code_value.get("effective_date")
    if effective is None or value_effective is None or effective < value_effective:
        raise ApiError(ERR_INVALID_STATE,
                       "an errata may not take effect before the code value's effective date")
    if code_value.get("value_status") != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "the named code value is not active")

    cycle = _cycle_for_code_value(code_value)
    deadline = cycle.get("errata_deadline") if cycle else None
    if deadline is not None and effective > deadline:
        raise ApiError(ERR_ERRATA_WINDOW_CLOSED,
                       "the errata takes effect after the release's errata deadline")
    if logical_now() < effective:
        raise ApiError(ERR_INVALID_STATE,
                       "the logical clock has not reached the errata effective date")

    # Recompute the proration and overwrite the affected published figure.
    VA.errata_proration(notice, code_value)
    code_value["facility_payment_cents"] = int(notice["corrected_facility_payment_cents"])
    store.bump(code_value)
    notice["status"] = "PUBLISHED"
    notice["published_at"] = logical_now()
    notice["_published_by"] = actor.user_id
    store.bump(notice)
    return object_response(one(notice), 200)


@bp.post("/errata-notices/<notice_id>/withdrawals")
@guard(STAFF)
def withdraw_notice(actor, notice_id):
    notice = R.errata_notice(notice_id)
    if notice.get("status") != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, "only a proposed notice may be withdrawn")

    # Withdrawal does not discard the arithmetic: the figures are recomputed
    # and retained on the row for audit.
    VA.errata_proration(notice)
    notice["status"] = "WITHDRAWN"
    notice["withdrawal_reason"] = P.text_or_none(P.body().get("reason"))
    store.bump(notice)
    return object_response(one(notice), 200)


@bp.post("/errata-reviews")
@guard(CHAIR)
def open_review(actor):
    data = P.body()
    notice = R.errata_notice(P.text_or_none(data.get("original_notice_id")) or "")
    outcome = data.get("review_outcome")
    ratio = data.get("corrected_proration_ratio")

    if outcome not in REVIEW_OUTCOMES:
        raise ApiError(ERR_INVALID_STATE, "an unsupported review outcome")
    if outcome == "REVERSED" and not _valid_ratio(ratio):
        raise ApiError(ERR_CORRECTION_INVALID,
                       "a corrected proration ratio must sit strictly between zero and one")

    review = store.create(store.errata_reviews, {
        "original_notice_id": notice["id"],
        "review_outcome": outcome,
        "corrected_proration_ratio": float(dec(ratio)) if _valid_ratio(ratio) else None,
        "applied_status": "NONE",
        "review_status": "OPEN",
        "reviewed_at": None,
    })
    return object_response(one(review), 201)


@bp.get("/errata-reviews")
@guard(REVIEW_READERS)
def list_reviews(actor):
    rows = store.sorted_rows(store.errata_reviews)
    for field in ("applied_status", "original_notice_id"):
        wanted = request.args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    return list_response(rows)


@bp.get("/errata-reviews/<review_id>")
@guard(REVIEW_READERS)
def read_review(actor, review_id):
    return object_response(one(R.errata_review(review_id)))


@bp.get("/errata-notices/<notice_id>/reviews")
@guard(REVIEW_READERS)
def list_notice_reviews(actor, notice_id):
    notice = R.errata_notice(notice_id)
    rows = [r for r in store.sorted_rows(store.errata_reviews)
            if r.get("original_notice_id") == notice["id"]]
    return list_response(rows)


@bp.post("/errata-reviews/<review_id>/outcomes")
@guard(CHAIR)
def decide_outcome(actor, review_id):
    review = R.errata_review(review_id)
    data = P.body()
    notice = store.errata_notices.get(review.get("original_notice_id"))
    if notice is None:
        from errors import ERR_NOT_FOUND

        raise ApiError(ERR_NOT_FOUND, "the notice under review not found")
    if review.get("review_status") != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "the review has already been decided")

    # Segregation of duties: the identity that published the notice may not be
    # the identity that reverses it (PRD.md 2.1 / 3.8).
    if actor.user_id == notice.get("_published_by"):
        raise ApiError(ERR_UNAUTHORIZED,
                       "the publishing identity may not reverse the same errata notice")

    ratio = data.get("corrected_proration_ratio")
    if review.get("review_outcome") == "REVERSED" and not _valid_ratio(ratio):
        if not _valid_ratio(review.get("corrected_proration_ratio")):
            raise ApiError(ERR_CORRECTION_INVALID,
                           "a corrected proration ratio must sit strictly between zero and one")

    updated_prior = data.get("updated_prior_cents")
    if updated_prior not in (None, ""):
        notice["prior_facility_payment_cents"] = P.integer(updated_prior, 0)

    if review.get("review_outcome") == "REVERSED":
        applied_ratio = dec(ratio) if _valid_ratio(ratio) else dec(
            review.get("corrected_proration_ratio")
        )
        review["corrected_proration_ratio"] = float(applied_ratio)
        notice["corrected_facility_payment_cents"] = int(cents(
            round_half_up(dec(notice.get("prior_facility_payment_cents")) * applied_ratio, 0)
        ))
        review["applied_status"] = "APPLIED"
        store.bump(notice)
    else:
        # An upholding leaves the underlying notice's figures alone.
        review["applied_status"] = "NOT_APPLICABLE"

    review["confirmation"] = P.text_or_none(data.get("confirmation"))
    review["review_status"] = "CLOSED"
    review["reviewed_at"] = logical_now()
    store.bump(review)
    return object_response(one(review), 200)