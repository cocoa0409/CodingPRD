"""Crash event, wellness check, and emergency dispatch routes."""
from flask import Blueprint, request
from db import db
from errors import (ApiError, err_not_found, err_invalid_request, err_forbidden,
                    ERR_TRIP_NOT_OPEN, ERR_CRASH_BELOW_THRESHOLD,
                    ERR_CONSENT_NOT_GRANTED, ERR_INVALID_STATE)
from middleware import (get_actor, require_roles, require_circle_member,
                        require_circle_owner, require_not_frozen)
from response import success, created, list_response, pagination_params
from serializers import ser, ser_many
import calculations as calc
import crash_service
from routes_circles import _get_circle_or_404, _get_member_or_404

bp = Blueprint("crashes", __name__)


def _get_crash_or_404(crash_id):
    crash = db.crashes.get(crash_id)
    if crash is None:
        raise err_not_found("Crash event not found")
    return crash


def _crash_circle(crash):
    member = db.members.get(crash["member_id"])
    return db.circles.get(member["circle_id"]) if member else None


@bp.route("/api/circles/<circle_id>/members/<member_id>/crash-events", methods=["POST"])
def report_crash(circle_id, member_id):
    actor = get_actor()
    require_roles(actor, {"Member", "Minor", "Owner", "Admin", "System"})
    circle = _get_circle_or_404(circle_id)
    member = _get_member_or_404(circle, member_id)
    if not actor.is_system:
        require_circle_member(actor, circle, {"Member", "Minor", "Owner", "Admin"})
    require_not_frozen(circle)
    if member["consent_state"] != "GRANTED":
        raise ApiError(ERR_CONSENT_NOT_GRANTED, 409, "Member consent not GRANTED")
    body = request.get_json(silent=True) or {}
    trip_id = body.get("trip_report_id")
    delta_v = body.get("delta_v")
    note = body.get("note")
    if not trip_id:
        raise err_invalid_request("trip_report_id is required")
    if not isinstance(delta_v, (int, float)) or isinstance(delta_v, bool):
        raise err_invalid_request("delta_v is required and must be numeric")
    trip = db.trips.get(trip_id)
    if trip is None or trip["member_id"] != member["id"] \
            or trip["trip_status"] != "OPEN":
        raise ApiError(ERR_TRIP_NOT_OPEN, 409, "TripReport not OPEN")
    severity = calc.crash_severity(delta_v)
    if severity is None:
        raise ApiError(ERR_CRASH_BELOW_THRESHOLD, 422,
                       "delta_v below crash threshold")
    crash = crash_service.create_crash_event(member, trip, severity, note=note)
    return created(ser(crash))


@bp.route("/api/circles/<circle_id>/members/<member_id>/crash-events", methods=["GET"])
def list_crashes(circle_id, member_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    circle = _get_circle_or_404(circle_id)
    member = _get_member_or_404(circle, member_id)
    if not actor.is_system:
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    items = [c for c in db.crashes.values() if c["member_id"] == member["id"]]
    status = request.args.get("crash_status")
    if status:
        items = [c for c in items if c["crash_status"] == status]
    items.sort(key=lambda c: c["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


@bp.route("/api/crash-events/<crash_id>", methods=["GET"])
def get_crash(crash_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    crash = _get_crash_or_404(crash_id)
    if not actor.is_system:
        circle = _crash_circle(crash)
        if circle is None:
            raise err_not_found("Crash event not found")
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    return success(ser(crash))


@bp.route("/api/crash-events", methods=["GET"])
def list_crashes_top():
    actor = get_actor()
    require_roles(actor, {"System"})
    items = list(db.crashes.values())
    for key in ("member_id", "trip_report_id", "wellness_check_id", "dispatch_id"):
        v = request.args.get(key)
        if v:
            items = [c for c in items if str(c.get(key)) == v]
    items.sort(key=lambda c: c["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


@bp.route("/api/crash-events/<crash_id>/wellness-checks/<check_id>/acknowledge",
          methods=["POST"])
def acknowledge_wellness(crash_id, check_id):
    actor = get_actor()
    require_roles(actor, {"Member", "Minor", "Owner", "Admin"})
    crash = _get_crash_or_404(crash_id)
    check = db.wellness_checks.get(check_id)
    if check is None or check["crash_event_id"] != crash["id"]:
        raise err_not_found("Wellness check not found")
    # Only the crash-subject member may acknowledge.
    if actor.user_id != crash["member_id"]:
        raise err_forbidden("Only the crash-subject member may acknowledge")
    circle = _crash_circle(crash)
    if circle is not None:
        require_not_frozen(circle)
    check = crash_service.acknowledge_wellness(crash, check, actor.user_id)
    return success(ser(check))


@bp.route("/api/crash-events/<crash_id>/mark-false-alarm", methods=["POST"])
def mark_false_alarm(crash_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor"})
    crash = _get_crash_or_404(crash_id)
    circle = _crash_circle(crash)
    if circle is None:
        raise err_not_found("Crash event not found")
    require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    actor_m = actor.member
    is_subject = actor_m["id"] == crash["member_id"]
    is_admin = actor_m["role"] in ("OWNER", "ADMIN")
    if not (is_subject or is_admin):
        raise err_forbidden("Only OWNER/ADMIN or the crash subject may retract")
    require_not_frozen(circle)
    body = request.get_json(silent=True) or {}
    reason = body.get("false_alarm_reason")
    if not isinstance(reason, str) or len(reason) < 5:
        raise err_invalid_request("false_alarm_reason required (length >= 5)")
    crash = crash_service.mark_false_alarm(crash, reason)
    return success(ser(crash))


# ---------------------------------------------------------------------------
# Wellness checks
# ---------------------------------------------------------------------------

@bp.route("/api/wellness-checks/<check_id>", methods=["GET"])
def get_wellness(check_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "Member", "Minor", "System"})
    check = db.wellness_checks.get(check_id)
    if check is None:
        raise err_not_found("Wellness check not found")
    if not actor.is_system:
        crash = db.crashes.get(check["crash_event_id"])
        circle = _crash_circle(crash) if crash else None
        if circle is None:
            raise err_not_found("Wellness check not found")
        require_circle_member(actor, circle, {"Owner", "Admin", "Member", "Minor"})
    return success(ser(check))


@bp.route("/api/wellness-checks", methods=["GET"])
def list_wellness_top():
    actor = get_actor()
    require_roles(actor, {"System"})
    items = list(db.wellness_checks.values())
    crash_id = request.args.get("crash_event_id")
    ack_by = request.args.get("acknowledged_by_member_id")
    if crash_id:
        items = [w for w in items if w["crash_event_id"] == crash_id]
    if ack_by:
        items = [w for w in items if w.get("acknowledged_by_member_id") == ack_by]
    items.sort(key=lambda w: w["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


# ---------------------------------------------------------------------------
# Dispatches
# ---------------------------------------------------------------------------

def _get_dispatch_or_404(dispatch_id):
    disp = db.dispatches.get(dispatch_id)
    if disp is None:
        raise err_not_found("Dispatch not found")
    return disp


@bp.route("/api/emergency-dispatches/<dispatch_id>", methods=["GET"])
def get_dispatch(dispatch_id):
    actor = get_actor()
    require_roles(actor, {"Owner", "Admin", "System"})
    disp = _get_dispatch_or_404(dispatch_id)
    if not actor.is_system:
        crash = db.crashes.get(disp["crash_event_id"])
        circle = _crash_circle(crash) if crash else None
        if circle is None:
            raise err_not_found("Dispatch not found")
        require_circle_member(actor, circle, {"Owner", "Admin"})
    return success(ser(disp))


@bp.route("/api/emergency-dispatches", methods=["GET"])
def list_dispatches_top():
    actor = get_actor()
    require_roles(actor, {"System"})
    items = list(db.dispatches.values())
    crash_id = request.args.get("crash_event_id")
    if crash_id:
        items = [d for d in items if d["crash_event_id"] == crash_id]
    items.sort(key=lambda d: d["created_at"])
    limit, offset = pagination_params()
    total = len(items)
    return list_response(ser_many(items[offset:offset + limit]), limit, offset, total)


@bp.route("/api/emergency-dispatches/<dispatch_id>/verify", methods=["POST"])
def verify_dispatch(dispatch_id):
    actor = get_actor()
    require_roles(actor, {"Owner"})
    disp = _get_dispatch_or_404(dispatch_id)
    crash = db.crashes.get(disp["crash_event_id"])
    circle = _crash_circle(crash) if crash else None
    if circle is None:
        raise err_not_found("Dispatch not found")
    require_circle_owner(actor, circle)
    body = request.get_json(silent=True) or {}
    note = body.get("verification_note")
    if not isinstance(note, str) or len(note) < 10:
        raise err_invalid_request("verification_note must be at least 10 characters")
    disp = crash_service.verify_dispatch(disp, crash, note)
    return success(ser(disp))


@bp.route("/api/emergency-dispatches/<dispatch_id>/complete", methods=["POST"])
def complete_dispatch(dispatch_id):
    actor = get_actor()
    require_roles(actor, {"Owner"})
    disp = _get_dispatch_or_404(dispatch_id)
    crash = db.crashes.get(disp["crash_event_id"])
    circle = _crash_circle(crash) if crash else None
    if circle is None:
        raise err_not_found("Dispatch not found")
    require_circle_owner(actor, circle)
    disp = crash_service.complete_dispatch(disp, crash)
    return success(ser(disp))


@bp.route("/api/emergency-dispatches/<dispatch_id>/cancel", methods=["POST"])
def cancel_dispatch(dispatch_id):
    actor = get_actor()
    require_roles(actor, {"Owner"})
    disp = _get_dispatch_or_404(dispatch_id)
    crash = db.crashes.get(disp["crash_event_id"])
    circle = _crash_circle(crash) if crash else None
    if circle is None:
        raise err_not_found("Dispatch not found")
    require_circle_owner(actor, circle)
    disp = crash_service.cancel_dispatch(disp, crash)
    return success(ser(disp))
