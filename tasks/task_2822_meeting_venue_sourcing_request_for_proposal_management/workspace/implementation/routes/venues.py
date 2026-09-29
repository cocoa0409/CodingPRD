"""Venue and supplier-performance endpoints (PRD sections 3.1, 3.9)."""
from flask import Blueprint, g

import clock
import db as store
import enums
import lookup
import middleware
import response
import serializers
import validate
from db import db, touch
from errors import ApiError
from services import calc, rollups

bp = Blueprint("venues", __name__)


@bp.route("/sourcing/venues", methods=["POST"])
@middleware.roles(middleware.ROLE_PROGRAM_ADMIN)
def create_venue():
    data = validate.body()
    name = validate.req_str(data, "name")
    city = validate.req_str(data, "city")
    country = validate.req_str(data, "country")
    destination_tier = validate.req_enum(data, "destination_tier",
                                         enums.DESTINATION_TIERS)
    guest_rooms_total = validate.req_int(data, "guest_rooms_total", minimum=1)
    largest_space_sqft = validate.req_int(data, "largest_space_sqft", minimum=0)
    preferred_supplier_status = validate.opt_enum(
        data, "preferred_supplier_status", enums.PREFERRED_STATUSES, "NONE"
    )

    row = store.base_row()
    row.update({
        "name": name,
        "city": city,
        "country": country,
        "destination_tier": destination_tier,
        "guest_rooms_total": guest_rooms_total,
        "largest_space_sqft": largest_space_sqft,
        "preferred_supplier_status": preferred_supplier_status,
        "performance_score": None,
        "performance_score_simple_mean": None,
        "performance_review_count": 0,
        "blocked_room_nights": 0,
    })
    db.venues[row["id"]] = row
    return response.obj(serializers.venue(row), 201)


@bp.route("/sourcing/venues/<venue_id>/preferred-status", methods=["PATCH"])
@middleware.roles(middleware.ROLE_PROGRAM_ADMIN)
def patch_preferred_status(venue_id):
    venue = lookup.venue(venue_id)
    data = validate.body()
    status = validate.req_enum(data, "preferred_supplier_status",
                               enums.PREFERRED_STATUSES)
    venue["preferred_supplier_status"] = status
    touch(venue)
    return response.obj(serializers.venue(venue))


@bp.route("/sourcing/venues/<venue_id>", methods=["GET"])
@middleware.roles(*middleware.ALL_ROLES)
def get_venue(venue_id):
    return response.obj(serializers.venue(lookup.venue(venue_id)))


@bp.route("/sourcing/venues", methods=["GET"])
@middleware.roles(*middleware.ALL_ROLES)
def list_venues():
    destination_tier = validate.enum_filter("destination_tier",
                                            enums.DESTINATION_TIERS)
    preferred_supplier_status = validate.enum_filter(
        "preferred_supplier_status", enums.PREFERRED_STATUSES
    )
    city = validate.str_filter("city")
    limit, offset = validate.pagination()
    rows = store.ordered(db.venues.values())
    if destination_tier:
        rows = [r for r in rows if r["destination_tier"] == destination_tier]
    if preferred_supplier_status:
        rows = [r for r in rows
                if r["preferred_supplier_status"] == preferred_supplier_status]
    if city:
        rows = [r for r in rows if r["city"] == city]
    return validate.page(rows, limit, offset, serializers.venue)


@bp.route("/sourcing/venues/<venue_id>/performance-reviews", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER, middleware.ROLE_PROGRAM_ADMIN)
def create_review(venue_id):
    venue = lookup.venue(venue_id)
    data = validate.body()

    event = None
    raw_event_id = data.get("event_id")
    if raw_event_id is not None:
        if not isinstance(raw_event_id, str):
            validate.bad("Field event_id must be a string")
        event = lookup.event(raw_event_id)

    review_source = validate.req_enum(data, "review_source", enums.REVIEW_SOURCES)
    service_score = validate.req_int(data, "service_score", minimum=1, maximum=5)
    value_score = validate.req_int(data, "value_score", minimum=1, maximum=5)
    av_quality_score = validate.req_int(data, "av_quality_score", minimum=1,
                                        maximum=5)
    responsiveness_score = validate.req_int(data, "responsiveness_score",
                                            minimum=1, maximum=5)
    comment = validate.opt_str(data, "comment")

    if review_source == "EVENT":
        if event is None:
            raise ApiError("ERR_REVIEW_EVENT_INVALID",
                           "An EVENT review must name an event")
        if event["status"] != "COMPLETED":
            raise ApiError("ERR_REVIEW_EVENT_INVALID",
                           "The named event is not COMPLETED")
        contract = lookup.executed_contract_of_event(event["id"])
        if contract is None or contract["venue_id"] != venue["id"]:
            raise ApiError("ERR_REVIEW_EVENT_INVALID",
                           "The named event was not awarded to this venue")
    else:
        if event is not None:
            raise ApiError("ERR_REVIEW_EVENT_INVALID",
                           "An EXTERNAL review must not name an event")

    row = store.base_row()
    row.update({
        "venue_id": venue["id"],
        "event_id": event["id"] if event else None,
        "review_source": review_source,
        "service_score": service_score,
        "value_score": value_score,
        "av_quality_score": av_quality_score,
        "responsiveness_score": responsiveness_score,
        "composite_score": calc.composite_score(
            service_score, value_score, av_quality_score, responsiveness_score
        ),
        "reviewer_user_id": g.user_id,
        "comment": comment,
    })
    db.reviews[row["id"]] = row

    rollups.refresh_venue_scores(venue)
    touch(venue)
    return response.obj(serializers.review(row), 201)


@bp.route("/sourcing/performance-reviews/<review_id>", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def get_review(review_id):
    return response.obj(serializers.review(lookup.review(review_id)))


@bp.route("/sourcing/performance-reviews", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def list_reviews():
    review_source = validate.enum_filter("review_source", enums.REVIEW_SOURCES)
    venue_id = validate.str_filter("venue_id")
    event_id = validate.str_filter("event_id")
    limit, offset = validate.pagination()
    rows = store.ordered(db.reviews.values())
    if review_source:
        rows = [r for r in rows if r["review_source"] == review_source]
    if venue_id:
        rows = [r for r in rows if r["venue_id"] == venue_id]
    if event_id:
        rows = [r for r in rows if r["event_id"] == event_id]
    return validate.page(rows, limit, offset, serializers.review)
