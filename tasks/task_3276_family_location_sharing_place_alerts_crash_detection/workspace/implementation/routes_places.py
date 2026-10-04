"""Place routes and place-alert listing."""
import math
from flask import Blueprint, request
from db import db, touch, new_entity
from errors import (ApiError, err_not_found, err_invalid_request,
                    ERR_PLACE_CONFIG_INVALID, ERR_PLACE_OVERLAP,
                    ERR_INVALID_STATE)
from middleware import (get_actor, require_roles, require_circle_member,
                        require_circle_admin, require_not_frozen)
from response import success, created, list_response, pagination_params
from serializers import ser, ser_many
import calculations as calc
from routes_circles import _get_circle_or_404

bp = Blueprint("places", __name__)

DWELL_BUCKETS = {60, 180, 300}


def _get_place_or_404(circle, place_id):
    place = db.places.get(place_id)
    if place is None or place["circle_id"] != circle["id"]:
        raise err_not_found("Place not found")
    return place


def _validate_place_fields(body, existing=None):
    label = body.get("label", existing["label"] if existing else None)
    center_lat = body.get("center_lat", existing["center_lat"] if existing else None)
    center_lng = body.get("center_lng", existing["center_lng"] if existing else None)
    radius_m = body.get("radius_m", existing["radius_m"] if existing else None)
    accuracy_floor_m = body.get("accuracy_floor_m",
                                existing["accuracy_floor_m"] if existing else 100)
    notify_arrive = body.get("notify_on_arrive",
                             existing["notify_on_arrive"] if existing else True)
    notify_depart = body.get("notify_on_depart",
                             existing["notify_on_depart"] if existing else True)
    dwell = body.get("dwell_bucket_seconds",
                     existing["dwell_bucket_seconds"] if existing else 180)

    def _bad(msg):
        raise ApiError(ERR_PLACE_CONFIG_INVALID, 422, msg)

    if not label or not isinstance(label, str):
        if existing is None:
            raise err_invalid_request("label is required")
    if not isinstance(center_lat, (int, float)) or isinstance(center_lat, bool) \
            or not (-90 <= center_lat <= 90):
        _bad("center_lat must be in -90..90")
    if not isinstance(center_lng, (int, float)) or isinstance(center_lng, bool) \
            or not (-180 <= center_lng <= 180):
        _bad("center_lng must be in -180..180")
    if not isinstance(radius_m, int) or isinstance(radius_m, bool) \
            or not (50 <= radius_m <= 5000):
        _bad("radius_m must be an integer in 50..5000")
    if not isinstance(accuracy_floor_m, int) or isinstance(accuracy_floor_m, bool) \
            or not (10 <= accuracy_floor_m <= 500):
        _bad("accuracy_floor_m must be an integer in 10..500")
    if not isinstance(notify_arrive, bool) or not isinstance(notify_depart, bool):
        _bad("notify flags must be boolean")
    if dwell not in DWELL_BUCKETS:
        _bad("dwell_bucket_seconds must be one of 60, 180, 300")
    return {
        "label": label,
        "center_lat": float(center_lat),
        "center_lng": float(center_lng),
        "radius_m": radius_m,
        "accuracy_floor_m": accuracy_floor_m,
        "notify_on_arrive": notify_arrive,
        "notify_on_depart": notify_depart,
        "dwell_bucket_seconds": dwell,
    }


def _check_overlap(circle_id, cand, exclude_id=None):
    """Reject when the candidate intersects any ACTIVE sibling by > 50% of the
    smaller radius area. Circle-circle intersection area approximation."""
    for place in db.places.values():
        if place["circle_id"] != circle_id or place["place_status"] != "ACTIVE":
            continue
        if exclude_id and place["id"] == exclude_id:
            continue
        r1 = cand["radius_m"]
        r2 = place["radius_m"]
        d = calc.haversine_m(cand["center_lat"], cand["center_lng"],
                             place["center_lat"], place["center_lng"])
        if d >= r1 + r2:
            continue
        r_small = min(r1, r2)
        if d + r_small <= max(r1, r2):
            # Containment: intersection area = pi * r_small^2 -> 100% overlap
            overlap_ratio = 1.0
        else:
            # Two-circle intersection area (exact formula)
            d_clamped = max(d, 1e-9)
            part1 = r1 * r1 * math.acos(
                min(1.0, max(-1.0, (d_clamped**2 + r1**2 - r2**2) / (2 * d_clamped * r1))))
            part2 = r2 * r2 * math.acos(
                min(1.0, max(-1.0, (d_clamped**2 + r2**2 - r1**2) / (2 * d_clamped * r2))))
            part3 = 0.5 * math.sqrt(max(0.0,
                (-d_clamped + r1 + r2) * (d_clamped + r1 - r2) *
                (d_clamped - r1 + r2) * (d_clamped + r1 + r2)))
            inter = part1 + part2 - part3
            overlap_ratio = inter / (math.pi * r_small * r_small)
        if overlap_ratio > 0.5:
            raise ApiError(ERR_PLACE_OVERLAP, 409,
                           "Place overlaps an existing ACTIVE place by more than 50%")


@bp.route("/api/circles/<circle_id>/places", methods=["POST"])
def create_place(circle_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin"})
    circle = _get_circle_or_404(circle_id)
    require_circle_admin(actor, circle)
    require_not_frozen(circle)
    body = request.get_json(silent=True) or {}
    fields = _validate_place_fields(body)
    _check_overlap(circle["id"], fields)
    place = new_entity(
        circle_id=circle["id"],
        place_status="ACTIVE",
        **fields,
    )
    db.places[place["id"]] = place
    return created(ser(place))


@bp.route("/api/circles/<circle_id>/places", methods=["GET"])
def list_places(circle_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    circle = _get_circle_or_404(circle_id)
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    items = [p for p in db.places.values() if p["circle_id"] == circle["id"]]
    status = request.args.get("place_status")
    if status:
        items = [p for p in items if p["place_status"] == status]
    items.sort(key=lambda p: p["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


@bp.route("/api/circles/<circle_id>/places/<place_id>", methods=["GET"])
def get_place_nested(circle_id, place_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    circle = _get_circle_or_404(circle_id)
    place = _get_place_or_404(circle, place_id)
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    return success(ser(place))


@bp.route("/api/places/<place_id>", methods=["GET"])
def get_place_top(place_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    place = db.places.get(place_id)
    if place is None:
        raise err_not_found("Place not found")
    if not actor.is_system:
        circle = db.circles.get(place["circle_id"])
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    return success(ser(place))


@bp.route("/api/circles/<circle_id>/places/<place_id>", methods=["PATCH"])
def patch_place(circle_id, place_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin"})
    circle = _get_circle_or_404(circle_id)
    place = _get_place_or_404(circle, place_id)
    require_circle_admin(actor, circle)
    require_not_frozen(circle)
    body = request.get_json(silent=True) or {}
    fields = _validate_place_fields(body, existing=place)
    _check_overlap(circle["id"], fields, exclude_id=place["id"])
    place.update(fields)
    touch(place)
    return success(ser(place))


@bp.route("/api/circles/<circle_id>/places/<place_id>/archive", methods=["POST"])
def archive_place(circle_id, place_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin"})
    circle = _get_circle_or_404(circle_id)
    place = _get_place_or_404(circle, place_id)
    require_circle_admin(actor, circle)
    require_not_frozen(circle)
    if place["place_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Place already archived")
    place["place_status"] = "ARCHIVED"
    touch(place)
    for alert in db.place_alerts.values():
        if alert["place_id"] == place["id"] and alert["alert_status"] == "PENDING_DWELL":
            alert["alert_status"] = "CANCELLED"
            touch(alert)
    return success(ser(place))


# ---------------------------------------------------------------------------
# Place alerts
# ---------------------------------------------------------------------------

@bp.route("/api/circles/<circle_id>/places/<place_id>/alerts", methods=["GET"])
def list_place_alerts(circle_id, place_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    circle = _get_circle_or_404(circle_id)
    place = _get_place_or_404(circle, place_id)
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    items = [a for a in db.place_alerts.values() if a["place_id"] == place["id"]]
    status = request.args.get("alert_status")
    member_id = request.args.get("member_id")
    kind = request.args.get("event_kind")
    if status:
        items = [a for a in items if a["alert_status"] == status]
    if member_id:
        items = [a for a in items if a["member_id"] == member_id]
    if kind:
        items = [a for a in items if a["event_kind"] == kind]
    # Privacy filter: HIDDEN members' alerts excluded for non-self readers
    if not actor.is_system:
        reader_id = actor.user_id
        filtered = []
        for a in items:
            subj = db.members.get(a["member_id"])
            if subj is not None and subj["privacy_mode"] == "HIDDEN" \
                    and a["member_id"] != reader_id:
                continue
            filtered.append(a)
        items = filtered
    items.sort(key=lambda a: a["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


@bp.route("/api/place-alerts/<alert_id>", methods=["GET"])
def get_place_alert(alert_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    alert = db.place_alerts.get(alert_id)
    if alert is None:
        raise err_not_found("Place alert not found")
    if not actor.is_system:
        place = db.places.get(alert["place_id"])
        circle = db.circles.get(place["circle_id"]) if place else None
        if circle is None:
            raise err_not_found("Place alert not found")
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    return success(ser(alert))


@bp.route("/api/place-alerts", methods=["GET"])
def list_place_alerts_top():
    actor = get_actor()
    require_roles(actor, {"System"})
    items = list(db.place_alerts.values())
    for key in ("place_id", "member_id", "window_open_fix_id",
                "window_close_fix_id", "alert_status", "event_kind"):
        v = request.args.get(key)
        if v:
            items = [a for a in items if str(a.get(key)) == v]
    items.sort(key=lambda a: a["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)
