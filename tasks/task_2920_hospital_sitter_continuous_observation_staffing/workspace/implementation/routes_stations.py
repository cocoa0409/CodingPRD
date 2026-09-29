"""Monitoring consoles, video feeds and span of control (PRD 3.7)."""
from flask import Blueprint

import calc
import serializers as S
import services as SVC
from db import base_entity, db, touch
from errors import fail
from response import object_response
from validation import authenticate, body_json, req_instant, req_int, req_str

bp = Blueprint("stations", __name__)

OBSERVER_ROLES = ("RemoteObserver", "SystemAdmin")


def _competency_ok(staff, order):
    level = staff["competency_level"]
    if level == "NOT_TRAINED":
        return False
    if "SELF_HARM" in order["risk_categories"]:
        return level == "ADVANCED"
    return level in ("BASIC", "ADVANCED")


# ---------------------------------------------------------------------------
# POST /observation/monitoring-stations
# ---------------------------------------------------------------------------
@bp.post("/observation/monitoring-stations")
def create_station():
    authenticate(("StaffingCoordinator", "SystemAdmin"))
    body = body_json()
    observer_staff_id = req_str(body, "observer_staff_id")
    station_label = req_str(body, "station_label", 1, 60)
    declared_max_span = req_int(body, "declared_max_span", 1, 12)
    observer = db.staff.get(observer_staff_id)
    if observer is None:
        fail("ERR_STAFF_NOT_FOUND")
    station = base_entity()
    station.update({
        "observer_staff_id": observer["id"],
        "station_label": station_label,
        "declared_max_span": declared_max_span,
        "status": "IDLE",
        "offlined_at": None,
    })
    db.stations[station["id"]] = station
    return object_response(S.station_json(station), 201)


# ---------------------------------------------------------------------------
# POST /observation/monitoring-stations/{id}/offline
# ---------------------------------------------------------------------------
@bp.post("/observation/monitoring-stations/<station_id>/offline")
def offline_station(station_id):
    caller = authenticate(OBSERVER_ROLES)
    body_json()
    station = db.stations.get(station_id)
    if station is None:
        fail("ERR_STATION_NOT_FOUND")
    SVC.require_owner(caller, station["observer_staff_id"])
    if station["status"] == "OFFLINE":
        fail("ERR_INVALID_STATION_STATE", "The console is already offline.")
    # Rung 23 sits below rung 8, so terminal lockdown is reported first.
    if station["status"] == "ACTIVE_MONITORING" or calc.active_feed_count(station) > 0:
        fail("ERR_STATION_HAS_ACTIVE_FEEDS",
             "Release the console's live feeds before taking it offline.")
    station["status"] = "OFFLINE"
    station["offlined_at"] = db.clock
    touch(station)
    return object_response(S.station_json(station))


# ---------------------------------------------------------------------------
# POST /observation/video-feeds
# ---------------------------------------------------------------------------
@bp.post("/observation/video-feeds")
def admit_feed():
    caller = authenticate(OBSERVER_ROLES)
    body = body_json()
    station_id = req_str(body, "station_id")
    order_id = req_str(body, "order_id")
    monitor_start_at = req_instant(body, "monitor_start_at")
    monitor_end_at = req_instant(body, "monitor_end_at")
    if monitor_end_at <= monitor_start_at:
        fail("ERR_INVALID_REQUEST",
             "monitor_end_at must be strictly later than monitor_start_at.")
    station = db.stations.get(station_id)
    if station is None:
        fail("ERR_STATION_NOT_FOUND")
    order = db.orders.get(order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND")
    SVC.require_owner(caller, station["observer_staff_id"])
    if station["status"] == "OFFLINE":
        fail("ERR_INVALID_STATION_STATE", "An offline console accepts nothing further.")
    observer = db.staff.get(station["observer_staff_id"])
    if observer is None:
        fail("ERR_STAFF_NOT_FOUND")
    if observer["deescalation_cert_expires_on"] <= db.clock:
        fail("ERR_DEESCALATION_CERT_EXPIRED",
             "The observer's de-escalation certification has expired.")
    if not _competency_ok(observer, order):
        fail("ERR_COMPETENCY_INSUFFICIENT", "The observer does not clear the competency floor.")
    if observer["status"] == "SUSPENDED":
        fail("ERR_STAFF_SUSPENDED", "The observer is suspended.")
    unit = calc.unit_of_order(order)
    if not calc.video_permitted(unit, order["risk_categories"], order["elopement_risk_score"]):
        fail("ERR_VIDEO_MODALITY_NOT_PERMITTED",
             "Video monitoring is not permitted for this order.")
    # Rung 22 before rung 24, per the numbered ladder of PRD 2.6. The capacity
    # limit is read BEFORE the candidate is admitted; occupancy counts it.
    limit = calc.effective_span_limit(station)
    occupancy = calc.overlapping_active_feeds(station["id"], monitor_start_at, monitor_end_at) + 1
    if occupancy > limit:
        fail("ERR_SPAN_OF_CONTROL_EXCEEDED",
             "The console's span of control would be exceeded.")
    for existing in calc.feeds_of_order(order["id"]):
        if existing["status"] == "ACTIVE":
            fail("ERR_DUPLICATE_ACTIVE_FEED", "The order already carries a live feed.")
    feed = base_entity()
    feed.update({
        "station_id": station["id"],
        "order_id": order["id"],
        "monitor_start_at": monitor_start_at,
        "monitor_end_at": monitor_end_at,
        "status": "ACTIVE",
        "acuity_weight": calc.feed_acuity_weight(order["risk_categories"]),
        "release_reason": None,
        "released_at": None,
    })
    db.feeds[feed["id"]] = feed
    if station["status"] == "IDLE":
        station["status"] = "ACTIVE_MONITORING"
        if observer["status"] == "AVAILABLE":
            observer["status"] = "ON_ASSIGNMENT"
            touch(observer)
    touch(station)
    return object_response(S.feed_json(feed), 201)


# ---------------------------------------------------------------------------
# POST /observation/video-feeds/{id}/release
# ---------------------------------------------------------------------------
@bp.post("/observation/video-feeds/<feed_id>/release")
def release_feed(feed_id):
    caller = authenticate(OBSERVER_ROLES)
    body_json()
    feed = db.feeds.get(feed_id)
    if feed is None:
        fail("ERR_FEED_NOT_FOUND")
    station = db.stations.get(feed["station_id"])
    SVC.require_owner(caller, station["observer_staff_id"] if station else None)
    if feed["status"] != "ACTIVE":
        fail("ERR_INVALID_FEED_STATE", "The feed is already released.")
    SVC.release_feed(feed, "OBSERVER_RELEASE")
    return object_response(S.feed_json(feed))
