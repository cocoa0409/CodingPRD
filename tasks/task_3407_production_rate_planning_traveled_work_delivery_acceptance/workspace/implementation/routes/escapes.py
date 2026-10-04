"""Quality escapes: report, notify, root cause, segregated disposition (PRD 3.6)."""
from flask import Blueprint, g

import calc
import svc
from core import (
    ApiError,
    body,
    db,
    endpoint,
    f_enum,
    f_str,
    f_str_list,
    new_row,
    now,
    paginate,
    q_enum,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("escapes", __name__, url_prefix="/api")

SEVERITIES = ("MAJOR", "CRITICAL")
DISPOSITION_CODES = ("USE_AS_IS", "REWORK", "SCRAP")
ESCAPE_STATUSES = ("OPEN", "ROOT_CAUSE", "DISPOSITIONED", "CLOSED")


@bp.post("/aircraft-units/<aircraft_id>/quality-escapes")
@endpoint("QualityInspector")
def create_escape(aircraft_id):
    aircraft = svc.need_aircraft(aircraft_id)
    payload = body()
    # rung 10 -- body shape
    severity = f_enum(payload, "severity", SEVERITIES)
    description = f_str(payload, "description")
    escape = new_row(
        "QualityEscape",
        aircraft_id=aircraft["id"],
        severity=severity,
        description=description,
        reported_by_id=g.user_id,
        conformance_documented=False,
        conformance_refs=[],
        regulator_notified_at=None,
        dispositioned_by_id=None,
        disposition_code=None,
        status="OPEN",
    )
    db.escapes[escape["id"]] = escape
    # The aircraft moves to quality HOLD immediately (PRD 3.6); open_escape_count
    # and posture recompute live.
    svc.set_quality_hold(aircraft)
    return respond_object(svc.dump_escape(escape), 201)


@bp.get("/quality-escapes/<escape_id>")
@endpoint("ProgramAdmin", "QualityInspector", "DeliveryManager", "ProductionPlanner")
def get_escape(escape_id):
    return respond_object(svc.dump_escape(svc.need_escape(escape_id)))


@bp.get("/aircraft-units/<aircraft_id>/quality-escapes")
@endpoint("ProgramAdmin", "QualityInspector", "DeliveryManager", "ProductionPlanner")
def list_aircraft_escapes(aircraft_id):
    svc.need_aircraft(aircraft_id)
    status = q_enum("status", ESCAPE_STATUSES)
    rows = [e for e in db.escapes.values() if e["aircraft_id"] == aircraft_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    return paginate(sort_created(rows), svc.dump_escape)


@bp.post("/quality-escapes/<escape_id>/notify-regulator")
@endpoint("QualityInspector")
def notify_regulator(escape_id):
    escape = svc.need_escape(escape_id)
    # Stamps the current logical clock (PRD 3.6); is_late_notification is computed.
    escape["regulator_notified_at"] = now()
    touch(escape)
    return respond_object(svc.dump_escape(escape))


@bp.post("/quality-escapes/<escape_id>/begin-root-cause")
@endpoint("QualityInspector")
def begin_root_cause(escape_id):
    escape = svc.need_escape(escape_id)
    # rung 5 -- state gate
    if escape["status"] != "OPEN":
        raise ApiError("ERR_INVALID_TRANSITION")
    # rung 6 -- regulator notification must precede root-cause work
    if escape["regulator_notified_at"] is None:
        raise ApiError("ERR_REGULATOR_NOTIFICATION_REQUIRED")
    # rung 10 -- conformance_refs payload with at least one reference
    refs = f_str_list(body(), "conformance_refs", non_empty=True)
    escape["conformance_refs"] = list(escape["conformance_refs"]) + refs
    escape["conformance_documented"] = True
    escape["status"] = "ROOT_CAUSE"
    touch(escape)
    return respond_object(svc.dump_escape(escape))


@bp.post("/quality-escapes/<escape_id>/disposition")
@endpoint("QualityInspector")
def disposition_escape(escape_id):
    escape = svc.need_escape(escape_id)
    # rung 5 -- state gate
    if escape["status"] != "ROOT_CAUSE":
        raise ApiError("ERR_INVALID_TRANSITION")
    # rung 6 -- segregation of duties: disposition actor != reporter
    if g.user_id == escape["reported_by_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # rung 10 -- body shape
    disposition_code = f_enum(body(), "disposition_code", DISPOSITION_CODES)
    escape["dispositioned_by_id"] = g.user_id
    escape["disposition_code"] = disposition_code
    escape["status"] = "DISPOSITIONED"
    touch(escape)
    return respond_object(svc.dump_escape(escape))


@bp.post("/quality-escapes/<escape_id>/reopen")
@endpoint("QualityInspector")
def reopen_escape(escape_id):
    escape = svc.need_escape(escape_id)
    if escape["status"] != "DISPOSITIONED":
        raise ApiError("ERR_INVALID_TRANSITION")
    escape["dispositioned_by_id"] = None
    escape["disposition_code"] = None
    escape["status"] = "ROOT_CAUSE"
    touch(escape)
    return respond_object(svc.dump_escape(escape))


@bp.post("/quality-escapes/<escape_id>/close")
@endpoint("QualityInspector")
def close_escape(escape_id):
    escape = svc.need_escape(escape_id)
    if escape["status"] != "DISPOSITIONED":
        raise ApiError("ERR_INVALID_TRANSITION")
    # Every rework order spawned from this escape must already be CLOSED/CREDITED.
    for order in db.rework_orders.values():
        if order["escape_id"] == escape["id"] and order["status"] not in (
            "CLOSED",
            "CREDITED",
        ):
            raise ApiError("ERR_INVALID_TRANSITION")
    escape["status"] = "CLOSED"
    touch(escape)
    # open_escape_count / posture recompute live; the aircraft may clear its HOLD.
    svc.maybe_clear_quality_hold(svc.need_aircraft(escape["aircraft_id"]))
    return respond_object(svc.dump_escape(escape))
