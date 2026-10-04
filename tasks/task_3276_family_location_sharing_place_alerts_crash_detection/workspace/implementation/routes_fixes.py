"""Location fix and trip routes."""
from datetime import timedelta
from flask import Blueprint, request
from db import db, now, parse_dt
from errors import (ApiError, err_not_found, err_invalid_request, err_forbidden,
                    ERR_FIX_CLOCK_SKEW)
from middleware import (get_actor, require_roles, require_circle_member,
                        require_not_frozen, check_frozen_read)
from response import success, created, list_response, pagination_params
from serializers import ser, ser_many
from fix_service import ingest_fix, check_trip_timeouts
from routes_circles import _get_circle_or_404, _get_member_or_404

bp = Blueprint("fixes", __name__)

MOTION_CONTEXTS = {"STILL", "WALKING", "DRIVING", "UNKNOWN"}
FIX_STATUSES = {"ACCEPTED", "REJECTED_ACCURACY", "REJECTED_STALE",
                "REJECTED_CONSENT", "RETIRED"}
TRIP_STATUSES = {"OPEN", "CLOSED", "ABANDONED"}


def _validate_fix_payload(body):
    def _bad(msg):
        raise ApiError(ERR_FIX_CLOCK_SKEW, 422, msg)

    recorded_at = parse_dt(body.get("recorded_at"))
    if recorded_at is None:
        raise err_invalid_request("recorded_at must be an ISO-8601 datetime")
    skew = abs((recorded_at - now()).total_seconds())
    if skew > 300:
        _bad("recorded_at skew exceeds 300 seconds")
    lat = body.get("lat")
    lng = body.get("lng")
    accuracy_m = body.get("accuracy_m")
    speed_mps = body.get("speed_mps")
    battery_pct = body.get("battery_pct")
    motion = body.get("motion_context")
    if not isinstance(lat, (int, float)) or isinstance(lat, bool) or not (-90 <= lat <= 90):
        _bad("lat must be in -90..90")
    if not isinstance(lng, (int, float)) or isinstance(lng, bool) or not (-180 <= lng <= 180):
        _bad("lng must be in -180..180")
    if not isinstance(accuracy_m, (int, float)) or isinstance(accuracy_m, bool) or accuracy_m <= 0:
        _bad("accuracy_m must be > 0")
    if not isinstance(speed_mps, (int, float)) or isinstance(speed_mps, bool) or speed_mps < 0:
        _bad("speed_mps must be >= 0")
    if not isinstance(battery_pct, int) or isinstance(battery_pct, bool) \
            or not (0 <= battery_pct <= 100):
        _bad("battery_pct must be in 0..100")
    if motion not in MOTION_CONTEXTS:
        _bad("motion_context must be one of STILL, WALKING, DRIVING, UNKNOWN")
    return {
        "lat": float(lat),
        "lng": float(lng),
        "accuracy_m": float(accuracy_m),
        "speed_mps": float(speed_mps),
        "battery_pct": battery_pct,
        "phone_in_use": body.get("phone_in_use", False),
        "motion_context": motion,
    }, recorded_at


def _posture_gate_for_fix(actor, circle, member):
    """FROZEN blocks mutations; also fixes posted by anyone other than the
    subject member or a circle admin are forbidden."""
    require_not_frozen(circle)
    if actor.is_system:
        raise err_forbidden()
    actor_m = actor.member
    if actor_m is None or actor_m["circle_id"] != circle["id"]:
        raise err_forbidden()
    if actor_m["id"] != member["id"] and actor_m["role"] not in ("OWNER", "ADMIN"):
        raise err_forbidden()


@bp.route("/api/circles/<circle_id>/members/<member_id>/fixes", methods=["POST"])
def post_fix(circle_id, member_id):
    actor = get_actor()
    require_roles(actor, {"Member", "Minor", "Owner", "Admin"})
    circle = _get_circle_or_404(circle_id)
    member = _get_member_or_404(circle, member_id)
    require_circle_member(actor, circle, {"Member", "Minor", "Owner", "Admin"})
    _posture_gate_for_fix(actor, circle, member)
    body = request.get_json(silent=True) or {}
    payload, recorded_at = _validate_fix_payload(body)
    check_trip_timeouts()
    fix = ingest_fix(member, circle, payload, recorded_at)
    return created(ser(fix))


def _retention_visible(circle, recorded_at):
    cutoff = now() - timedelta(days=circle["history_retention_days"])
    return recorded_at >= cutoff


@bp.route("/api/circles/<circle_id>/members/<member_id>/fixes", methods=["GET"])
def list_fixes(circle_id, member_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    circle = _get_circle_or_404(circle_id)
    member = _get_member_or_404(circle, member_id)
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
        check_frozen_read(actor, circle)
    items = [f for f in db.fixes.values() if f["member_id"] == member["id"]]
    items = [f for f in items if _retention_visible(circle, f["recorded_at"])]
    status = request.args.get("fix_status")
    if status:
        items = [f for f in items if f["fix_status"] == status]
    since = request.args.get("since")
    if since:
        since_dt = parse_dt(since)
        if since_dt is not None:
            items = [f for f in items if f["recorded_at"] >= since_dt]
    items.sort(key=lambda f: (f["recorded_at"], f["created_at"]))
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


@bp.route("/api/circles/<circle_id>/members/<member_id>/fixes/<fix_id>", methods=["GET"])
def get_fix_nested(circle_id, member_id, fix_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    circle = _get_circle_or_404(circle_id)
    member = _get_member_or_404(circle, member_id)
    fix = db.fixes.get(fix_id)
    if fix is None or fix["member_id"] != member["id"]:
        raise err_not_found("Fix not found")
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
        check_frozen_read(actor, circle)
    return success(ser(fix))


@bp.route("/api/location-fixes/<fix_id>", methods=["GET"])
def get_fix_top(fix_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    fix = db.fixes.get(fix_id)
    if fix is None:
        raise err_not_found("Fix not found")
    if not actor.is_system:
        member = db.members.get(fix["member_id"])
        circle = db.circles.get(member["circle_id"]) if member else None
        if circle is None:
            raise err_not_found("Fix not found")
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
        check_frozen_read(actor, circle)
    return success(ser(fix))


@bp.route("/api/location-fixes", methods=["GET"])
def list_fixes_top():
    actor = get_actor()
    require_roles(actor, {"System"})
    items = list(db.fixes.values())
    member_id = request.args.get("member_id")
    if member_id:
        items = [f for f in items if f["member_id"] == member_id]
    items.sort(key=lambda f: (f["recorded_at"], f["created_at"]))
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


# ---------------------------------------------------------------------------
# Trips
# ---------------------------------------------------------------------------

@bp.route("/api/circles/<circle_id>/members/<member_id>/trips", methods=["GET"])
def list_trips(circle_id, member_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    circle = _get_circle_or_404(circle_id)
    member = _get_member_or_404(circle, member_id)
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
        check_frozen_read(actor, circle)
    items = [t for t in db.trips.values() if t["member_id"] == member["id"]]
    items = [t for t in items if _retention_visible(circle, t["started_at"])]
    status = request.args.get("trip_status")
    if status:
        items = [t for t in items if t["trip_status"] == status]
    items.sort(key=lambda t: t["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


@bp.route("/api/circles/<circle_id>/members/<member_id>/trips/<trip_id>", methods=["GET"])
def get_trip_nested(circle_id, member_id, trip_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    circle = _get_circle_or_404(circle_id)
    member = _get_member_or_404(circle, member_id)
    trip = db.trips.get(trip_id)
    if trip is None or trip["member_id"] != member["id"]:
        raise err_not_found("Trip not found")
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
        check_frozen_read(actor, circle)
    return success(ser(trip))


@bp.route("/api/trip-reports/<trip_id>", methods=["GET"])
def get_trip_top(trip_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    trip = db.trips.get(trip_id)
    if trip is None:
        raise err_not_found("Trip not found")
    if not actor.is_system:
        member = db.members.get(trip["member_id"])
        circle = db.circles.get(member["circle_id"]) if member else None
        if circle is None:
            raise err_not_found("Trip not found")
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    return success(ser(trip))


@bp.route("/api/trip-reports", methods=["GET"])
def list_trips_top():
    actor = get_actor()
    require_roles(actor, {"System"})
    items = list(db.trips.values())
    member_id = request.args.get("member_id")
    if member_id:
        items = [t for t in items if t["member_id"] == member_id]
    items.sort(key=lambda t: t["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)
