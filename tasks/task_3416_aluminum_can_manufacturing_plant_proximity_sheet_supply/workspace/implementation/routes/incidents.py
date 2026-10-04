"""Quality incident endpoints: open, list, get, escalate, resolve."""
from flask import Blueprint, request

from db import store, new_id, now_iso, next_seq, touch
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import actor, require_role
from response import ok_object, ok_list
from routes.runs import get_run_or_404
from services.serialize import incident_public
from validation import body_json, req_str, req_enum, pagination_args

bp = Blueprint("incidents", __name__)

SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
DEFECT_CLASSES = ("SEAM_INTEGRITY", "COATING", "FILLING_LINE_PERFORMANCE")


def get_incident_or_404(iid):
    inc = store["incidents"].get(iid)
    if inc is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Quality incident not found.")
    return inc


def _line_has_escalated(line_id):
    return any(
        i["line_id"] == line_id and i["status"] == "ESCALATED"
        for i in store["incidents"].values()
    )


@bp.post("/production-runs/<rid>/quality-incidents")
def create_incident(rid):
    _, role = actor()
    require_role(role, ["QualityEngineer"])
    data = body_json()
    severity = req_enum(data, "severity", SEVERITIES)
    defect_class = req_enum(data, "defect_class", DEFECT_CLASSES)
    note = req_str(data, "note")
    run = get_run_or_404(rid)
    ts = now_iso()
    inc = {
        "id": new_id(),
        "run_id": run["id"],
        "line_id": run["line_id"],
        "severity": severity,
        "defect_class": defect_class,
        "note": note,
        "status": "OPEN",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_sort": next_seq(),
    }
    store["incidents"][inc["id"]] = inc
    return ok_object(incident_public(inc), code=201)


@bp.get("/quality-incidents")
def list_incidents():
    actor()
    limit, offset = pagination_args()
    run_id = request.args.get("run_id")
    line_id = request.args.get("line_id")
    status = request.args.get("status")
    items = sorted(store["incidents"].values(), key=lambda i: i["_created_sort"])
    if run_id is not None:
        items = [i for i in items if i["run_id"] == run_id]
    if line_id is not None:
        items = [i for i in items if i["line_id"] == line_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([incident_public(i) for i in page], limit, offset, total)


@bp.get("/quality-incidents/<iid>")
def get_incident(iid):
    actor()
    return ok_object(incident_public(get_incident_or_404(iid)))


@bp.post("/quality-incidents/<iid>/escalate")
def escalate_incident(iid):
    _, role = actor()
    require_role(role, ["QualityEngineer"])
    inc = get_incident_or_404(iid)
    if inc["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only an OPEN incident can be escalated.")
    inc["status"] = "ESCALATED"
    touch(inc)
    run = store["runs"][inc["run_id"]]
    if run["status"] == "IN_PROGRESS":
        run["status"] = "HELD"
        touch(run)
    line = store["lines"][inc["line_id"]]
    if line["operational_status"] != "QUALITY_HOLD":
        line["operational_status"] = "QUALITY_HOLD"
        touch(line)
    return ok_object(incident_public(inc))


@bp.post("/quality-incidents/<iid>/resolve")
def resolve_incident(iid):
    _, role = actor()
    require_role(role, ["QualityEngineer"])
    inc = get_incident_or_404(iid)
    if inc["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only an OPEN or ESCALATED incident can be resolved.")
    was_escalated = inc["status"] == "ESCALATED"
    inc["status"] = "RESOLVED"
    touch(inc)
    if was_escalated:
        # Direct resolution from OPEN leaves run and line untouched; from
        # ESCALATED the hold releases only when no other escalation remains
        # on any run of the line.
        run = store["runs"][inc["run_id"]]
        line = store["lines"][inc["line_id"]]
        if not _line_has_escalated(line["id"]):
            if run["status"] == "HELD":
                run["status"] = "IN_PROGRESS"
                touch(run)
            if line["operational_status"] != "RUNNING":
                line["operational_status"] = "RUNNING"
                touch(line)
    return ok_object(incident_public(inc))
