"""Rating engagements and agency presentations (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint

import db
import lookup
import response
import serializers
from errors import ApiError
from middleware import (
    ALL_ROLES,
    authenticate,
    require_deal_ownership,
    require_pinned_analyst,
)
from validation import parse_body, query_value, sorted_rows, spec

bp = Blueprint("ratings", __name__)

AGENCIES = ["MOODYS", "SP", "FITCH", "KBRA"]
OUTLOOKS = ["POSITIVE", "STABLE", "NEGATIVE", "DEVELOPING"]
MAX_PRESENTATION_MINUTES = 180
PRESENTATION_BUFFER_MINUTES = 60
MAX_ATTENDEE_COUNT = 25
LIVE_ENGAGEMENT_STATUSES = ("REQUESTED", "UNDER_REVIEW", "INFO_REQUESTED")


@bp.route("/bond-offerings/deals/<deal_id>/rating-engagements", methods=["POST"])
def create_engagement(deal_id):
    actor = authenticate(["MunicipalAdvisor", "IssuerOfficial"])
    deal = lookup.get_deal(deal_id)
    body = parse_body([spec("agency", "enum", values=AGENCIES)])
    require_deal_ownership(actor, deal)
    # tier 15: at most one non-withdrawn engagement per (deal, agency)
    for existing in lookup.engagements_of_deal(deal_id):
        if existing["agency"] == body["agency"] and existing["status"] != "WITHDRAWN":
            raise ApiError("ERR_DUPLICATE_RATING_ENGAGEMENT")
    row = db.new_row(
        deal_id=deal_id,
        agency=body["agency"],
        status="REQUESTED",
        assigned_analyst_user_id=None,
        info_request_count=0,
        latest_information_request=None,
        assigned_rating=None,
        outlook=None,
    )
    db.db.engagements[row["id"]] = row
    return response.created(serializers.engagement(row))


@bp.route("/bond-offerings/deals/<deal_id>/rating-engagements", methods=["GET"])
def list_deal_engagements(deal_id):
    authenticate(ALL_ROLES)
    lookup.get_deal(deal_id)
    rows = sorted_rows(lookup.engagements_of_deal(deal_id))
    agency = query_value("agency")
    if agency is not None:
        rows = [row for row in rows if row["agency"] == agency]
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return response.paginated(rows, serializers.engagement)


@bp.route("/bond-offerings/rating-engagements/<engagement_id>", methods=["GET"])
def read_engagement(engagement_id):
    authenticate(ALL_ROLES)
    row = lookup.get_engagement(engagement_id)
    return response.ok(serializers.engagement(row))


@bp.route("/bond-offerings/rating-engagements/<engagement_id>/acknowledge", methods=["POST"])
def acknowledge_engagement(engagement_id):
    actor = authenticate(["RatingAnalyst"])
    engagement = lookup.get_engagement(engagement_id)
    parse_body([])
    if engagement["status"] != "REQUESTED":
        raise ApiError("ERR_RATING_ENGAGEMENT_INVALID_STATE")
    engagement["status"] = "UNDER_REVIEW"
    engagement["assigned_analyst_user_id"] = actor.user_id
    db.touch(engagement)
    return response.ok(serializers.engagement(engagement))


@bp.route("/bond-offerings/rating-engagements/<engagement_id>/request-info", methods=["POST"])
def request_info(engagement_id):
    actor = authenticate(["RatingAnalyst"])
    engagement = lookup.get_engagement(engagement_id)
    body = parse_body([spec("information_request", "string", min_len=1)])
    require_pinned_analyst(actor, engagement)
    if engagement["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_RATING_ENGAGEMENT_INVALID_STATE")
    engagement["status"] = "INFO_REQUESTED"
    engagement["info_request_count"] = engagement["info_request_count"] + 1
    engagement["latest_information_request"] = body["information_request"]
    db.touch(engagement)
    return response.ok(serializers.engagement(engagement))


@bp.route("/bond-offerings/rating-engagements/<engagement_id>/respond-info", methods=["POST"])
def respond_info(engagement_id):
    actor = authenticate(["MunicipalAdvisor"])
    engagement = lookup.get_engagement(engagement_id)
    parse_body([spec("response_summary", "string", min_len=1)])
    deal = lookup.deal_of_engagement(engagement)
    require_deal_ownership(actor, deal)
    if engagement["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_RATING_ENGAGEMENT_INVALID_STATE")
    engagement["status"] = "UNDER_REVIEW"
    db.touch(engagement)
    return response.ok(serializers.engagement(engagement))


@bp.route("/bond-offerings/rating-engagements/<engagement_id>/assign-rating", methods=["POST"])
def assign_rating(engagement_id):
    actor = authenticate(["RatingAnalyst"])
    engagement = lookup.get_engagement(engagement_id)
    body = parse_body(
        [
            spec("assigned_rating", "string", min_len=1),
            spec("outlook", "enum", values=OUTLOOKS),
        ]
    )
    require_pinned_analyst(actor, engagement)
    if engagement["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_RATING_ENGAGEMENT_INVALID_STATE")
    # tier 13: a rating requires a presentation that actually took place
    held = [
        row
        for row in lookup.presentations_of_engagement(engagement_id)
        if row["status"] == "HELD"
    ]
    if not held:
        raise ApiError("ERR_PRESENTATION_REQUIRED")
    engagement["status"] = "RATED"
    engagement["assigned_rating"] = body["assigned_rating"]
    engagement["outlook"] = body["outlook"]
    db.touch(engagement)
    return response.ok(serializers.engagement(engagement))


PRESENTATION_SPECS = [
    spec("starts_at", "datetime"),
    spec("ends_at", "datetime"),
    spec("attendee_count", "integer", minimum=1, maximum=MAX_ATTENDEE_COUNT),
]


@bp.route("/bond-offerings/rating-engagements/<engagement_id>/presentations", methods=["POST"])
def create_presentation(engagement_id):
    actor = authenticate(["MunicipalAdvisor", "Underwriter"])
    engagement = lookup.get_engagement(engagement_id)
    body = parse_body(PRESENTATION_SPECS)
    starts_at = body["starts_at"]
    ends_at = body["ends_at"]
    # tier 5: the window must be positive and no longer than three hours
    if ends_at <= starts_at:
        raise ApiError("ERR_INVALID_REQUEST")
    if ends_at - starts_at > timedelta(minutes=MAX_PRESENTATION_MINUTES):
        raise ApiError("ERR_INVALID_REQUEST")
    deal = lookup.deal_of_engagement(engagement)
    require_deal_ownership(actor, deal)
    # tier 11: a closed credit review takes no further sessions
    if engagement["status"] in ("RATED", "WITHDRAWN"):
        raise ApiError("ERR_PRESENTATION_INVALID_STATE")
    # tier 14: one clear hour around each agency's schedule on this deal
    buffer = timedelta(minutes=PRESENTATION_BUFFER_MINUTES)
    window_start = starts_at - buffer
    window_end = ends_at + buffer
    for other_engagement in lookup.engagements_of_deal(deal["id"]):
        if other_engagement["agency"] != engagement["agency"]:
            continue
        for other in lookup.presentations_of_engagement(other_engagement["id"]):
            if other["status"] == "CANCELLED":
                continue
            if other["ends_at"] > window_start and other["starts_at"] < window_end:
                raise ApiError("ERR_PRESENTATION_BUFFER_CONFLICT")
    row = db.new_row(
        rating_engagement_id=engagement_id,
        starts_at=starts_at,
        ends_at=ends_at,
        attendee_count=body["attendee_count"],
        status="SCHEDULED",
        cancellation_reason=None,
    )
    db.db.presentations[row["id"]] = row
    return response.created(serializers.presentation(row))


@bp.route("/bond-offerings/rating-engagements/<engagement_id>/presentations", methods=["GET"])
def list_engagement_presentations(engagement_id):
    authenticate(ALL_ROLES)
    lookup.get_engagement(engagement_id)
    rows = sorted_rows(lookup.presentations_of_engagement(engagement_id))
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return response.paginated(rows, serializers.presentation)


@bp.route("/bond-offerings/rating-presentations/<presentation_id>", methods=["GET"])
def read_presentation(presentation_id):
    authenticate(ALL_ROLES)
    row = lookup.get_presentation(presentation_id)
    return response.ok(serializers.presentation(row))


@bp.route("/bond-offerings/rating-presentations/<presentation_id>/cancel", methods=["POST"])
def cancel_presentation(presentation_id):
    actor = authenticate(["MunicipalAdvisor", "Underwriter"])
    presentation = lookup.get_presentation(presentation_id)
    body = parse_body([spec("cancellation_reason", "string", min_len=1)])
    deal = lookup.deal_of_presentation(presentation)
    require_deal_ownership(actor, deal)
    if presentation["status"] != "SCHEDULED":
        raise ApiError("ERR_PRESENTATION_INVALID_STATE")
    presentation["status"] = "CANCELLED"
    presentation["cancellation_reason"] = body["cancellation_reason"]
    db.touch(presentation)
    return response.ok(serializers.presentation(presentation))
