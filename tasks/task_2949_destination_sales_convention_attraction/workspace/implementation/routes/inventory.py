"""Meeting planners, hotels and convention center halls (PRD 3.1)."""

from flask import Blueprint, request

import aggregates
import domain
import resolve
import serialize
from auth import (BOARD_ANALYST, BUREAU_ADMIN, CENTER_SCHEDULER, HOTEL_PARTNER,
                  INCENTIVE_APPROVER, SALES_MANAGER, endpoint)
from response import created, list_response, object_response, pagination
from store import db, ordered, touch
from validation import (body_json, opt_enum, opt_int, query_enum, req_enum,
                        req_int, req_str)

bp = Blueprint("inventory", __name__)


# ==========================================================================
# meeting planners
# ==========================================================================
@bp.route("/meeting-planners", methods=["POST"])
@endpoint(BUREAU_ADMIN)
def create_planner():
    body = body_json()
    org_name = req_str(body, "org_name", min_len=1, max_len=120)
    contact_email = req_str(body, "contact_email", min_len=5, max_len=120,
                            must_contain="@")
    legacy_definite_count = opt_int(body, "legacy_definite_count", default=0,
                                   minimum=0)
    legacy_room_nights = opt_int(body, "legacy_definite_room_nights", default=0,
                                 minimum=0)

    row = db.new_row()
    row.update({
        "org_name": org_name,
        "contact_email": contact_email,
        "legacy_definite_count": legacy_definite_count,
        "legacy_definite_room_nights": legacy_room_nights,
        "definite_count": 0,
        "lost_count": 0,
        "lifetime_definite_room_nights": 0,
        "relationship_score_lifetime": 0,
        "relationship_score_rolling_24m": 0,
        "tier": "TIER_C",
        "engagement_status": "PROSPECT",
        "last_touch_at": None,
    })
    db.planners[row["id"]] = row
    # the scores and tier are computed from the migrated counters alone
    aggregates.recompute_planner(row)
    return created(serialize.planner(row))


@bp.route("/meeting-planners/<row_id>", methods=["GET"])
@endpoint(BUREAU_ADMIN, SALES_MANAGER, INCENTIVE_APPROVER, BOARD_ANALYST)
def get_planner(row_id):
    return object_response(serialize.planner(resolve.planner(row_id)))


@bp.route("/meeting-planners", methods=["GET"])
@endpoint(BUREAU_ADMIN, SALES_MANAGER, BOARD_ANALYST)
def list_planners():
    tier = query_enum(request.args, "tier", domain.TIERS)
    status = query_enum(request.args, "engagement_status", domain.ENGAGEMENT_STATUSES)
    limit, offset = pagination(request.args)
    rows = ordered(list(db.planners.values()))
    if tier is not None:
        rows = [r for r in rows if r["tier"] == tier]
    if status is not None:
        rows = [r for r in rows if r["engagement_status"] == status]
    return list_response(rows, serialize.planner, limit, offset)


# ==========================================================================
# hotels
# ==========================================================================
@bp.route("/hotels", methods=["POST"])
@endpoint(BUREAU_ADMIN)
def create_hotel():
    body = body_json()
    name = req_str(body, "name", min_len=1, max_len=120)
    committable_rooms = req_int(body, "committable_rooms", minimum=1)
    walk_distance_blocks = opt_int(body, "walk_distance_blocks", default=0,
                                   minimum=0)
    participation_status = opt_enum(body, "participation_status",
                                    domain.PARTICIPATION_STATUSES,
                                    default="PARTICIPATING")

    row = db.new_row()
    row.update({
        "name": name,
        "committable_rooms": committable_rooms,
        "walk_distance_blocks": walk_distance_blocks,
        "participation_status": participation_status,
        "committed_peak_rooms": 0,
        "committed_room_nights": 0,
        "pickup_room_nights": 0,
    })
    db.hotels[row["id"]] = row
    return created(serialize.hotel(row))


@bp.route("/hotels/<row_id>", methods=["GET"])
@endpoint(BUREAU_ADMIN, SALES_MANAGER, HOTEL_PARTNER, BOARD_ANALYST)
def get_hotel(row_id):
    return object_response(serialize.hotel(resolve.hotel(row_id)))


@bp.route("/hotels", methods=["GET"])
@endpoint(BUREAU_ADMIN, SALES_MANAGER)
def list_hotels():
    status = query_enum(request.args, "participation_status",
                        domain.PARTICIPATION_STATUSES)
    limit, offset = pagination(request.args)
    rows = ordered(list(db.hotels.values()))
    if status is not None:
        rows = [r for r in rows if r["participation_status"] == status]
    return list_response(rows, serialize.hotel, limit, offset)


@bp.route("/hotels/<row_id>/participation", methods=["POST"])
@endpoint(BUREAU_ADMIN)
def set_participation(row_id):
    hotel = resolve.hotel(row_id)
    body = body_json()
    status = req_enum(body, "participation_status", domain.PARTICIPATION_STATUSES)
    # replaced outright: existing committed blocks are left completely untouched
    hotel["participation_status"] = status
    touch(hotel)
    return object_response(serialize.hotel(hotel))


# ==========================================================================
# center halls
# ==========================================================================
@bp.route("/center-halls", methods=["POST"])
@endpoint(BUREAU_ADMIN, CENTER_SCHEDULER)
def create_hall():
    body = body_json()
    name = req_str(body, "name", min_len=1, max_len=120)
    exhibit_sqft = req_int(body, "exhibit_sqft", minimum=1)
    capacity_persons = req_int(body, "capacity_persons", minimum=1)
    turnaround_hours = opt_int(body, "turnaround_hours",
                               default=domain.DEFAULT_TURNAROUND_HOURS, minimum=0)
    hall_status = opt_enum(body, "hall_status", domain.HALL_STATUSES,
                           default="AVAILABLE")

    row = db.new_row()
    row.update({
        "name": name,
        "exhibit_sqft": exhibit_sqft,
        "capacity_persons": capacity_persons,
        "turnaround_hours": turnaround_hours,
        "hall_status": hall_status,
        "confirmed_hold_count": 0,
    })
    db.halls[row["id"]] = row
    return created(serialize.hall(row))


@bp.route("/center-halls/<row_id>", methods=["GET"])
@endpoint(BUREAU_ADMIN, CENTER_SCHEDULER, SALES_MANAGER)
def get_hall(row_id):
    return object_response(serialize.hall(resolve.hall(row_id)))


@bp.route("/center-halls", methods=["GET"])
@endpoint(BUREAU_ADMIN, CENTER_SCHEDULER, SALES_MANAGER)
def list_halls():
    status = query_enum(request.args, "hall_status", domain.HALL_STATUSES)
    limit, offset = pagination(request.args)
    rows = ordered(list(db.halls.values()))
    if status is not None:
        rows = [r for r in rows if r["hall_status"] == status]
    return list_response(rows, serialize.hall, limit, offset)
