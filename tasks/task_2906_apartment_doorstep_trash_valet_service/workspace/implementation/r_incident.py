"""CompactorIncident endpoints (PRD s3.7)."""

from datetime import timedelta

from flask import Blueprint

import shape
from authz import admit, get_incident, get_property, require_property_owner
from envelope import array_response, object_response
from errors import ApiError
from rollups import apply_escalation_rollup
from serializers import incident_out
from shape import pagination, paginate, q
from store import (
    ACK_WINDOW_HOURS,
    clock,
    db,
    iso,
    now_iso,
    parse_instant,
    sort_rows,
    stamp_new,
    touch,
)

bp = Blueprint("incident", __name__)

INCIDENT_TYPES = ("JAM", "OVERFLOW")
OPEN_INCIDENT_STATUSES = ("REPORTED", "ACKNOWLEDGED", "ESCALATED")


@bp.route("/valet/properties/<property_id>/compactor-incidents", methods=["POST"])
def report_incident(property_id):
    actor = admit(("PlatformAdmin", "ValetOpsManager", "PropertyManager", "Valet"))
    prop = get_property(property_id)
    require_property_owner(actor, prop["id"])
    body = shape.body()
    incident_type = shape.req_enum(body, "incident_type", INCIDENT_TYPES)
    description = shape.opt_str(body, "description", max_len=1000)

    reported_at = clock.now()
    deadline = reported_at + timedelta(hours=ACK_WINDOW_HOURS[incident_type])
    row = {
        "property_id": prop["id"],
        "incident_type": incident_type,
        "description": description,
        "reported_by_role": actor.role,
        "reported_by_user_id": actor.user_id,
        "reported_at": iso(reported_at),
        "ack_deadline_at": iso(deadline),
        "status": "REPORTED",
        "acknowledged_at": None,
        "escalated_at": None,
        "resolved_at": None,
        "resolution_note": None,
    }
    stamp_new(row)
    db.incidents[row["id"]] = row
    return object_response(incident_out(row), 201)


@bp.route("/valet/compactor-incidents/<incident_id>", methods=["GET"])
def read_incident(incident_id):
    admit((
        "PlatformAdmin",
        "ValetOpsManager",
        "PropertyManager",
        "ComplianceOfficer",
        "Valet",
    ))
    row = get_incident(incident_id)
    return object_response(incident_out(row))


@bp.route("/valet/compactor-incidents", methods=["GET"])
def list_incidents():
    admit(("PlatformAdmin", "ValetOpsManager", "PropertyManager", "ComplianceOfficer"))
    limit, offset = pagination()
    f_property = q("property_id")
    f_type = q("incident_type")
    f_status = q("status")
    rows = sort_rows(list(db.incidents.values()))
    if f_property is not None:
        rows = [r for r in rows if r["property_id"] == f_property]
    if f_type is not None:
        rows = [r for r in rows if r["incident_type"] == f_type]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    page, total, has_more = paginate(rows, limit, offset)
    return array_response([incident_out(r) for r in page], limit, offset, total, has_more)


@bp.route("/valet/compactor-incidents/<incident_id>/acknowledge", methods=["POST"])
def acknowledge_incident(incident_id):
    actor = admit(("PropertyManager", "PlatformAdmin"))
    incident = get_incident(incident_id)
    require_property_owner(actor, incident["property_id"])
    shape.body()

    # rung 8
    if incident["status"] == "RESOLVED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if incident["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE")
    # the window is strictly before the deadline
    if clock.now() >= parse_instant(incident["ack_deadline_at"]):
        raise ApiError("ERR_INVALID_STATE")

    incident["status"] = "ACKNOWLEDGED"
    incident["acknowledged_at"] = now_iso()
    touch(incident)
    return object_response(incident_out(incident))


@bp.route("/valet/compactor-incidents/<incident_id>/escalate", methods=["POST"])
def escalate_incident(incident_id):
    admit(("ValetOpsManager", "PlatformAdmin"))
    incident = get_incident(incident_id)
    shape.body()

    # rung 8
    if incident["status"] == "RESOLVED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if incident["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE")

    # rung 18 -- the deadline instant itself is permitted
    if clock.now() < parse_instant(incident["ack_deadline_at"]):
        raise ApiError("ERR_ESCALATION_WINDOW_NOT_ELAPSED")

    incident["status"] = "ESCALATED"
    incident["escalated_at"] = now_iso()
    touch(incident)

    prop = db.properties.get(incident["property_id"])
    if prop is not None:
        apply_escalation_rollup(prop)
        touch(prop)
    return object_response(incident_out(incident))


@bp.route("/valet/compactor-incidents/<incident_id>/resolve", methods=["POST"])
def resolve_incident(incident_id):
    actor = admit(("PropertyManager", "ValetOpsManager", "PlatformAdmin"))
    incident = get_incident(incident_id)
    require_property_owner(actor, incident["property_id"])
    body = shape.body()
    note = shape.req_str(body, "resolution_note", min_len=1, max_len=1000, non_blank=True)

    # rung 8
    if incident["status"] == "RESOLVED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if incident["status"] not in OPEN_INCIDENT_STATUSES:
        raise ApiError("ERR_INVALID_STATE")

    was_escalated = incident["status"] == "ESCALATED"
    incident["status"] = "RESOLVED"
    incident["resolved_at"] = now_iso()
    incident["resolution_note"] = note
    touch(incident)

    if was_escalated:
        prop = db.properties.get(incident["property_id"])
        if prop is not None:
            apply_escalation_rollup(prop)
            touch(prop)
    return object_response(incident_out(incident))
