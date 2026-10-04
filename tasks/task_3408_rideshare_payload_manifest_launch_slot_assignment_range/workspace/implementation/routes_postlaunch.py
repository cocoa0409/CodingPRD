"""Post-launch routes: separation events (list/read/report-outcome) and
anomaly investigation transitions."""
from flask import Blueprint, request

from cascade import execute_separation
from envelope import success, success_list
from errors import (
    ERR_ANOMALIES_UNRESOLVED,
    ERR_ANOMALY_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_SEPARATION_EVENT_NOT_FOUND,
    bad_request,
    conflict,
    not_found,
)
from middleware import require_roles
from serialize import ser_anomaly, ser_separation_event
from store import bump, db, new_entity, touch
from validate import (
    as_enum,
    as_str,
    body_json,
    opt_enum_filter,
    opt_field,
    paginate,
    parse_pagination,
    req_field,
)

bp = Blueprint("postlaunch", __name__)

EVENT_OUTCOMES = {"EXECUTED", "ANOMALOUS"}
EVENT_STATUSES = {"PLANNED", "EXECUTED", "ANOMALOUS"}
ANOMALY_CATEGORIES = {"SEPARATION", "PAYLOAD_TELEMETRY"}
ANOMALY_SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
ANOMALY_TARGETS = {"UNDER_INVESTIGATION", "ESCALATED", "RESOLVED"}
DISPOSITIONS = {"NOMINAL", "LOSS"}

ALLOWED_ANOMALY_TRANSITIONS = {
    ("OPEN", "UNDER_INVESTIGATION"),
    ("UNDER_INVESTIGATION", "ESCALATED"),
    ("ESCALATED", "UNDER_INVESTIGATION"),
    ("UNDER_INVESTIGATION", "RESOLVED"),
    ("ESCALATED", "RESOLVED"),
}


@bp.get("/rideshare/separation-events")
@require_roles("MissionOps", "IntegrationEngineer", "SafetyOfficer")
def list_separation_events():
    status = opt_enum_filter(request.args, "status", EVENT_STATUSES)
    mission_id = request.args.get("mission_id")
    assignment_id = request.args.get("assignment_id")
    limit, offset = parse_pagination(request.args)
    rows = list(db["separation_events"].values())
    if mission_id is not None:
        rows = [e for e in rows if e["mission_id"] == mission_id]
    if assignment_id is not None:
        rows = [e for e in rows if e["assignment_id"] == assignment_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    # declared ordering: sequence_index ascending
    rows.sort(key=lambda e: (e["sequence_index"], e["created_at"], e["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([ser_separation_event(e) for e in page], limit, offset, total)


@bp.get("/rideshare/separation-events/<eid>")
@require_roles("MissionOps", "IntegrationEngineer", "SafetyOfficer")
def get_separation_event(eid):
    ev = db["separation_events"].get(eid)
    if ev is None:
        raise not_found(
            ERR_SEPARATION_EVENT_NOT_FOUND, f"separation event {eid} not found"
        )
    return success(ser_separation_event(ev))


@bp.post("/rideshare/separation-events/<eid>/report-outcome")
@require_roles("MissionOps")
def report_outcome(eid):
    body = body_json()
    outcome = as_enum(req_field(body, "outcome"), "outcome", EVENT_OUTCOMES)
    category = opt_field(body, "anomaly_category", None)
    severity = opt_field(body, "anomaly_severity", None)
    if outcome == "ANOMALOUS":
        if category is None or severity is None:
            raise bad_request(
                "anomaly_category and anomaly_severity are required for ANOMALOUS"
            )
        category = as_enum(category, "anomaly_category", ANOMALY_CATEGORIES)
        severity = as_enum(severity, "anomaly_severity", ANOMALY_SEVERITIES)

    ev = db["separation_events"].get(eid)
    if ev is None:
        raise not_found(
            ERR_SEPARATION_EVENT_NOT_FOUND, f"separation event {eid} not found"
        )

    if outcome == "EXECUTED":
        if ev["status"] == "PLANNED":
            execute_separation(ev)
        elif ev["status"] == "ANOMALOUS":
            unresolved = any(
                a["mission_id"] == ev["mission_id"] and a["status"] != "RESOLVED"
                for a in db["anomalies"].values()
            )
            if unresolved:
                raise conflict(
                    ERR_ANOMALIES_UNRESOLVED,
                    "all mission anomalies must be RESOLVED first",
                )
            execute_separation(ev)
        else:
            raise conflict(
                ERR_INVALID_STATE, f"event is {ev['status']}, cannot report EXECUTED"
            )
    else:  # ANOMALOUS
        if ev["status"] != "PLANNED":
            raise conflict(
                ERR_INVALID_STATE, f"event is {ev['status']}, cannot report ANOMALOUS"
            )
        ev["status"] = "ANOMALOUS"
        touch(ev)  # no version bump on separation-event transitions
        anomaly = new_entity()
        anomaly.update(
            {
                "mission_id": ev["mission_id"],
                "category": category,
                "severity": severity,
                "status": "OPEN",
                "disposition": None,
                "resolution_notes": None,
            }
        )
        db["anomalies"][anomaly["id"]] = anomaly
    return success(ser_separation_event(ev))


@bp.post("/rideshare/anomalies/<aid>/transition")
@require_roles("MissionOps", "SafetyOfficer")
def transition_anomaly(aid):
    body = body_json()
    to_state = as_enum(req_field(body, "to_state"), "to_state", ANOMALY_TARGETS)
    disposition = opt_field(body, "disposition", None)
    resolution_notes = opt_field(body, "resolution_notes", None)
    if to_state == "RESOLVED":
        if disposition is None:
            raise bad_request("disposition is required when resolving an anomaly")
        disposition = as_enum(disposition, "disposition", DISPOSITIONS)
    if resolution_notes is not None:
        resolution_notes = as_str(resolution_notes, "resolution_notes")

    a = db["anomalies"].get(aid)
    if a is None:
        raise not_found(ERR_ANOMALY_NOT_FOUND, f"anomaly {aid} not found")
    if (a["status"], to_state) not in ALLOWED_ANOMALY_TRANSITIONS:
        raise conflict(
            ERR_INVALID_STATE,
            f"cannot move anomaly from {a['status']} to {to_state}",
        )
    a["status"] = to_state
    if to_state == "RESOLVED":
        a["disposition"] = disposition
        a["resolution_notes"] = resolution_notes
    bump(a)
    return success(ser_anomaly(a))
