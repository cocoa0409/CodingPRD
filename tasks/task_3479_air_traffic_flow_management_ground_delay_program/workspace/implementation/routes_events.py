"""ConstraintEvent endpoints (PRD 3.2): report, list, confirm, clear, extend."""

from flask import Blueprint

from capacity import cascade_event_confirmed
from constants import (
    CONSTRAINT_EVENT_MAX_EXTENSIONS,
    EVENT_TYPES,
    ROLE_FLOW_MANAGER,
    ROLES,
    SEVERITY_MAX,
    SEVERITY_MIN,
)
from errors import ApiError
from serialize import serialize_constraint_event
from storage import DB, create_entity, touch
from util import (
    body_json,
    opt_int,
    paginate,
    req_dt,
    req_enum,
    req_int,
    success_object,
)
from validation import (
    auth_context,
    check_window,
    get_event,
    get_facility,
    require_roles,
    windows_overlap,
)

bp = Blueprint("constraint_events", __name__)


def _check_event_overlap(facility_id, event_type, window_start, window_end, exclude_id=None):
    """Priority 13: no other non-CLEARED event of the same event_type on the
    same facility may overlap the half-open window; adjacency is allowed."""
    for other in DB["constraint_events"].values():
        if (
            other["facility_id"] == facility_id
            and other["event_type"] == event_type
            and other["status"] != "CLEARED"
            and other["id"] != exclude_id
            and windows_overlap(
                other["window_start"], other["window_end"], window_start, window_end
            )
        ):
            raise ApiError(
                "ERR_CONSTRAINT_EVENT_OVERLAP",
                "a non-CLEARED %s event already overlaps this window on the facility"
                % event_type,
            )


@bp.route("/atfm/facilities/<facility_id>/constraint-events", methods=["POST"])
def report_event(facility_id):
    auth_context()
    require_roles(ROLE_FLOW_MANAGER)
    facility = get_facility(facility_id)
    body = body_json()
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    severity = req_int(body, "severity")
    if not (SEVERITY_MIN <= severity <= SEVERITY_MAX):
        raise ApiError(
            "ERR_INVALID_REQUEST", "severity must be an integer in [1, 5]"
        )
    window_start = req_dt(body, "window_start")
    window_end = req_dt(body, "window_end")
    check_window(window_start, window_end)
    _check_event_overlap(facility["id"], event_type, window_start, window_end)
    rec = create_entity(
        "constraint_events",
        {
            "facility_id": facility["id"],
            "event_type": event_type,
            "severity": severity,
            "window_start": window_start,
            "window_end": window_end,
            "extension_count": 0,
            "status": "REPORTED",
        },
    )
    return success_object(serialize_constraint_event(rec), 201)


@bp.route("/atfm/facilities/<facility_id>/constraint-events", methods=["GET"])
def list_events(facility_id):
    auth_context()
    require_roles(*ROLES)
    facility = get_facility(facility_id)
    status_filter = None
    type_filter = None
    from flask import request

    if "status" in request.args:
        status_filter = request.args.get("status")
    if "event_type" in request.args:
        type_filter = request.args.get("event_type")
    rows = [
        e
        for e in DB["constraint_events"].values()
        if e["facility_id"] == facility["id"]
        and (status_filter is None or e["status"] == status_filter)
        and (type_filter is None or e["event_type"] == type_filter)
    ]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return paginate([serialize_constraint_event(e) for e in rows])


@bp.route("/atfm/constraint-events/<event_id>/confirm", methods=["POST"])
def confirm_event(event_id):
    auth_context()
    require_roles(ROLE_FLOW_MANAGER)
    event = get_event(event_id)
    if event["status"] != "REPORTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "only a REPORTED constraint event can be confirmed",
        )
    event["status"] = "CONFIRMED"
    touch(event)
    cascade_event_confirmed(event)
    return success_object(serialize_constraint_event(event))


@bp.route("/atfm/constraint-events/<event_id>/clear", methods=["POST"])
def clear_event(event_id):
    auth_context()
    require_roles(ROLE_FLOW_MANAGER)
    event = get_event(event_id)
    if event["status"] not in ("REPORTED", "CONFIRMED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "only a REPORTED or CONFIRMED constraint event can be cleared",
        )
    # Clearing does NOT un-STALE forecasts (PRD 3.2).
    event["status"] = "CLEARED"
    touch(event)
    return success_object(serialize_constraint_event(event))


@bp.route("/atfm/constraint-events/<event_id>/extend", methods=["POST"])
def extend_event(event_id):
    auth_context()
    require_roles(ROLE_FLOW_MANAGER)
    event = get_event(event_id)
    body = body_json()
    new_window_end = req_dt(body, "window_end")
    new_severity = opt_int(body, "severity")
    if new_severity is not None and not (SEVERITY_MIN <= new_severity <= SEVERITY_MAX):
        raise ApiError(
            "ERR_INVALID_REQUEST", "severity must be an integer in [1, 5]"
        )
    if event["status"] not in ("REPORTED", "CONFIRMED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "only a REPORTED or CONFIRMED constraint event can be extended",
        )
    # Priority 8: the extension must move window_end forward.
    if not (new_window_end > event["window_end"]):
        raise ApiError(
            "ERR_INVALID_WINDOW",
            "extension window_end must be strictly later than the current window_end",
        )
    # Priority 13: the widened window re-checks same-type overlap.
    _check_event_overlap(
        event["facility_id"],
        event["event_type"],
        event["window_start"],
        new_window_end,
        exclude_id=event["id"],
    )
    # Priority 19: hard cap CONSTRAINT_EVENT_MAX_EXTENSIONS (2).
    if event["extension_count"] >= CONSTRAINT_EVENT_MAX_EXTENSIONS:
        raise ApiError(
            "ERR_EXTENSION_LIMIT_EXCEEDED",
            "constraint event has already been extended %d times"
            % CONSTRAINT_EVENT_MAX_EXTENSIONS,
        )
    event["window_end"] = new_window_end
    if new_severity is not None:
        event["severity"] = new_severity
    event["extension_count"] += 1
    touch(event)
    # A CONFIRMED event with a wider window re-fires the cascades (PRD 3.2).
    if event["status"] == "CONFIRMED":
        cascade_event_confirmed(event)
    return success_object(serialize_constraint_event(event))
