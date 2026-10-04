# routes/docket_reviews.py — docket-review snapshot reads (the POST lives in
# routes/courts.py under /courts/<courtId>/docket-reviews).
from flask import Blueprint

import db
from auth import get_auth
from computed import serialize_docket_review
from envelope import success, list_response
from errors import ApiError
from inputs import pagination_params, filter_param, sorted_page

bp = Blueprint("docket_reviews", __name__)


@bp.get("/docket-reviews")
def list_reviews():
    get_auth()  # all roles
    limit, offset = pagination_params()
    records = list(db.docket_reviews.values())
    court_id = filter_param("court_id")
    if court_id is not None:
        records = [r for r in records if r["court_id"] == court_id]
    page, total = sorted_page(records, limit, offset)
    return list_response([serialize_docket_review(r) for r in page], total,
                         limit, offset)


@bp.get("/docket-reviews/<reviewId>")
def get_review(reviewId):
    get_auth()  # all roles
    r = db.docket_reviews.get(reviewId)
    if r is None:
        # generic 404 for DocketReview references (PRD §2.6 tier 3)
        raise ApiError("ERR_NOT_FOUND", "DocketReview id does not exist")
    return success(serialize_docket_review(r), response_type="object",
                   status=200)
