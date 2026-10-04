"""TravelSupportGrant endpoints (PRD §3.7)."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from errors import ApiError, ERR_GRANT_NOT_FOUND, invalid_state
from helpers import (get_body, haversine_miles, new_id, now_iso, req_enum)
from middleware import require_auth
from response import success_list, success_object, paginate
from routes.applications import get_application_or_404
from views import grant_view

bp = Blueprint("grants", __name__)

LIST_ROLES = ["NetworkAdmin", "CareCoordinator", "PhilanthropyOfficer"]

GRANT_TYPES = {"TRAVEL", "LODGING", "TRAVEL_AND_LODGING"}

ROAD_CIRCUITY_FACTOR = Decimal("1.3")
DISTANCE_THRESHOLD_MILES = Decimal("100.0")
LODGING_TIER1_CENTS = 15000
LODGING_TIER2_CENTS = 22500
TRAVEL_PER_MILE_CENTS = 58
TRAVEL_CAP_CENTS = 100000


def get_grant_or_404(grant_id):
    g = db.grants.get(grant_id)
    if g is None:
        raise ApiError(ERR_GRANT_NOT_FOUND, 404, "Travel support grant id does not exist")
    return g


def _round1(value):
    """Round to 1 decimal, round-half-up."""
    return float(Decimal(repr(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _round_whole(value):
    """Round to the nearest whole number, round-half-up."""
    return int(Decimal(repr(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@bp.post("/applications/<id>/travel-support-grants")
def create_grant(id):
    require_auth(["CareCoordinator"])
    a = get_application_or_404(id)
    body = get_body()
    grant_type = req_enum(body, "grant_type", GRANT_TYPES)
    if a["status"] != "ACCEPTED":
        raise invalid_state("Application must be ACCEPTED to create a travel support grant")

    program = db.programs.get(a["program_id"])
    hospital = db.hospitals.get(program["hospital_id"])

    # PROVISIONAL variant: haversine straight-line, 1 decimal half-up (display only)
    straight_line = _round1(haversine_miles(a["home_latitude"], a["home_longitude"],
                                            hospital["latitude"], hospital["longitude"]))
    # FINAL variant: circuity-adjusted road distance, 1 decimal half-up
    road = _round1(straight_line * float(ROAD_CIRCUITY_FACTOR))

    distance_eligible = Decimal(str(road)) >= DISTANCE_THRESHOLD_MILES

    nightly_lodging_stipend_cents = 0
    travel_allowance_cents = 0
    if distance_eligible:
        if grant_type in ("LODGING", "TRAVEL_AND_LODGING"):
            if road >= 300.0:
                nightly_lodging_stipend_cents = LODGING_TIER2_CENTS
            else:
                nightly_lodging_stipend_cents = LODGING_TIER1_CENTS
        if grant_type in ("TRAVEL", "TRAVEL_AND_LODGING"):
            whole_miles = _round_whole(road)
            travel_allowance_cents = min(TRAVEL_PER_MILE_CENTS * whole_miles,
                                         TRAVEL_CAP_CENTS)

    now = now_iso()
    g = {
        "id": new_id(),
        "application_id": a["id"],
        "grant_type": grant_type,
        "straight_line_distance_miles": straight_line,
        "road_distance_miles": road,
        "distance_eligible": distance_eligible,
        "nightly_lodging_stipend_cents": nightly_lodging_stipend_cents,
        "travel_allowance_cents": travel_allowance_cents,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.grants[g["id"]] = g
    return success_object(grant_view(g), 201)


@bp.get("/applications/<id>/travel-support-grants")
def list_grants(id):
    require_auth(LIST_ROLES)
    a = get_application_or_404(id)
    items = [g for g in db.grants.values() if g["application_id"] == a["id"]]
    page, total, limit, offset = paginate(items, request.args)
    return success_list([grant_view(g) for g in page], total, limit, offset)


@bp.get("/travel-support-grants/<grantId>")
def get_grant(grantId):
    require_auth(LIST_ROLES)
    g = get_grant_or_404(grantId)
    return success_object(grant_view(g))
