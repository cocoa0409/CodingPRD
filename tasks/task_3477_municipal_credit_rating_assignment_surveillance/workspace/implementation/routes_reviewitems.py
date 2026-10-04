"""Criteria review items (PRD §3.6): listed in fan-out order, begun
(PENDING/ESCALATED -> IN_REVIEW), and completed with NO_ACTION or
RATING_ACTION (which moves the rating's notch)."""
from flask import Blueprint, request

from auth import auth, authenticate
from constants import (
    CAUSE_CRITERIA_REVIEW,
    EVENT_REVIEW_COMPLETED,
    NOTCH_SCALE,
    REVIEW_OUTCOMES,
    ROLE_SURVEILLANCE_OFFICER,
)
from envelope import paginate, parse_pagination, success_array, success_object
from errors import (
    ERR_REVIEW_ITEM_STATE_INVALID,
    ERR_REVIEW_OUTCOME_NOTCH_REQUIRED,
    raise_err,
)
from services_disclosure import recompute_review_pending
from store import db, notify, touch
from validators import (
    body,
    get_rating,
    get_review_item,
    optional_enum,
    present,
    require_enum,
    require_fields,
)

bp = Blueprint("reviewitems", __name__)


def _fanout_key(item):
    """Fan-out order (PRD §2.3): the reviewed rating's published_at ascending,
    ties broken by the rating's created_at ascending, then insertion order."""
    rating = db.ratings.get(item["rating_id"])
    if rating is None:
        return (None, None, item["_seq"])
    return (rating["published_at"], rating["created_at"], item["_seq"])


@bp.route("/muni/review-items", methods=["GET"])
def list_review_items():
    authenticate()
    items = list(db.review_items.values())
    for field in ("criteria_version_id", "rating_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [i for i in items if i.get(field) == value]
    items.sort(key=_fanout_key)
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_array(page, total, limit, offset)


@bp.route("/muni/review-items/<review_item_id>", methods=["GET"])
def get_one_review_item(review_item_id):
    authenticate()
    return success_object(get_review_item(review_item_id))


@bp.route("/muni/review-items/<review_item_id>/begin", methods=["POST"])
def begin_review(review_item_id):
    auth([ROLE_SURVEILLANCE_OFFICER])
    item = get_review_item(review_item_id)
    # Priority 6: PENDING or ESCALATED only (IN_REVIEW items are exempt from
    # escalation but already begun).
    if item["status"] not in ("PENDING", "ESCALATED"):
        raise_err(ERR_REVIEW_ITEM_STATE_INVALID, "review item is not PENDING or ESCALATED")
    item["status"] = "IN_REVIEW"
    touch(item)
    return success_object(item)


@bp.route("/muni/review-items/<review_item_id>/complete", methods=["POST"])
def complete_review(review_item_id):
    auth([ROLE_SURVEILLANCE_OFFICER])
    item = get_review_item(review_item_id)
    payload = body()
    require_fields(payload, ["outcome", "rationale"])
    outcome = require_enum(payload, "outcome", REVIEW_OUTCOMES)
    new_notch = optional_enum(payload, "new_notch", NOTCH_SCALE)

    # Priority 6: completion requires IN_REVIEW.
    if item["status"] != "IN_REVIEW":
        raise_err(ERR_REVIEW_ITEM_STATE_INVALID, "review item is not IN_REVIEW")

    # Priority 10(o): RATING_ACTION requires new_notch.
    if outcome == "RATING_ACTION" and new_notch is None:
        raise_err(ERR_REVIEW_OUTCOME_NOTCH_REQUIRED, "new_notch is required for a RATING_ACTION outcome")

    clock = db.now()
    item["status"] = "COMPLETED_NO_ACTION" if outcome == "NO_ACTION" else "COMPLETED_RATING_ACTION"
    item["outcome_notch"] = new_notch if outcome == "RATING_ACTION" else None
    item["rationale"] = payload["rationale"]
    item["completed_at"] = clock
    touch(item)

    rating = get_rating(item["rating_id"])
    if outcome == "RATING_ACTION":
        rating["notch"] = new_notch
        rating["notch_history"].append(
            {"notch": new_notch, "changed_at": clock, "cause": CAUSE_CRITERIA_REVIEW}
        )
        touch(rating)
    recompute_review_pending(rating)
    notify(
        rating["issuer_id"],
        EVENT_REVIEW_COMPLETED,
        item["id"],
        "Criteria review %s completed with outcome %s." % (item["id"], item["status"]),
    )
    return success_object(item)
