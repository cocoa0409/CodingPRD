"""Season exit reviews and the logical clock (PRD 2.5, 3.9)."""

from flask import Blueprint

from db import db, new_row
from errors import ApiError
from middleware import (ROLE_CONTROLLER, ROLE_MERCHANDISE_DIRECTOR, body,
                        endpoint)
from response import created, ok
from serializers import exit_review_json
from services import lookup
from services.lifecycle import exit_reviews_of_season, reclassify_all_items
from services.review import build_scorecard

bp = Blueprint("reviews", __name__)

REVIEW_TYPES = ("PRELIMINARY", "FINAL")


@endpoint(bp, "/seasons/<season_id>/exit-reviews", ["POST"],
          (ROLE_MERCHANDISE_DIRECTOR, ROLE_CONTROLLER))
def create_exit_review(user_id, role, season_id):
    from validation import req_enum
    payload = body()
    review_type = req_enum(payload, "review_type", REVIEW_TYPES)
    season = lookup.season(season_id)

    lookup.gate_not_closed(season)
    if review_type == "PRELIMINARY":
        lookup.gate_active(season)
    else:
        lookup.gate_exit_window(season)

    for existing in exit_reviews_of_season(season):
        if existing["review_type"] == review_type:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "A %s review already exists for this season."
                           % review_type)

    review = new_row(
        versioned=False,
        season_id=season["id"],
        review_type=review_type,
        generated_at=db.clock_instant(),
        generated_by_user_id=user_id,
        **build_scorecard(season, review_type)
    )
    db.insert("exit_reviews", review)
    return created(exit_review_json(review))


@endpoint(bp, "/_clock/set_current_utc", ["POST"], None)
def set_clock(user_id, role):
    from validation import req_instant
    payload = body()
    db.clock = req_instant(payload, "current_utc")
    reclassify_all_items()
    return ok({})
