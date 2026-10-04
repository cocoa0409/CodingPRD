"""Animal-welfare incidents (PRD 3.4).

POST /farm-network/farms/{id}/incidents   (NM, Auditor, QM, 201)
GET  /farm-network/farms/{id}/incidents   (NM, Auditor, QM, 200)
POST /farm-network/incidents/{id}/resolve (NetworkManager, 200)
"""
from flask import Blueprint, request

import constants as C
import domain
import store
from auth import authenticate, authorize
from clock import now
from errors import ApiError
from responses import ok, ok_list
from serialize import incident_out
from validation import get_body, f_enum, f_str, MISSING, pagination

bp = Blueprint("incidents", __name__, url_prefix="/farm-network")

_REPORT_ROLES = ("NetworkManager", "Auditor", "QualityManager")


@bp.route("/farms/<fid>/incidents", methods=["POST"])
def report_incident(fid):
    uid, role = authenticate()
    authorize(role, _REPORT_ROLES)
    farm = domain.get_farm_or_404(fid)
    data = get_body()
    severity = f_enum(data, "severity", C.INCIDENT_SEVERITIES)
    incident_type = f_str(data, "incident_type")
    description = f_str(data, "description")
    if farm["status"] == "REMOVED":
        raise ApiError("ERR_FARM_TERMINAL", 409, "farm is REMOVED")
    ts = now()
    incident = {
        "id": domain.new_id(),
        "farm_id": farm["id"],
        "severity": severity,
        "incident_type": incident_type,
        "description": description,
        "status": "REPORTED",
        "disposition": None,
        "resolved_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.incidents[incident["id"]] = incident
    # A CRITICAL report suspends an ACTIVE or PROBATION farm immediately,
    # with the stop-skip cascade (PRD 3.4 report_time_note).
    if severity == "CRITICAL":
        domain.suspend_farm_if_active_or_probation(farm)
    return ok(incident_out(incident), 201)


@bp.route("/farms/<fid>/incidents", methods=["GET"])
def list_incidents(fid):
    uid, role = authenticate()
    authorize(role, _REPORT_ROLES)
    farm = domain.get_farm_or_404(fid)
    limit, offset = pagination()
    status = request.args.get("status")
    severity = request.args.get("severity")
    rows = [i for i in store.incidents.values() if i["farm_id"] == farm["id"]]
    if status is not None:
        rows = [i for i in rows if i["status"] == status]
    if severity is not None:
        rows = [i for i in rows if i["severity"] == severity]
    page, total = domain.sorted_page(rows, limit, offset)
    return ok_list([incident_out(i) for i in page], limit, offset, total)


@bp.route("/incidents/<iid>/resolve", methods=["POST"])
def resolve_incident(iid):
    uid, role = authenticate()
    authorize(role, ("NetworkManager",))
    incident = domain.get_incident_or_404(iid)
    data = get_body()
    disposition = f_enum(data, "disposition", C.INCIDENT_DISPOSITIONS)
    notes = f_str(data, "resolution_notes", required=False)
    if incident["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409, "only a REPORTED incident can be resolved")
    ts = now()
    incident["status"] = "RESOLVED"
    incident["disposition"] = disposition
    incident["resolved_at"] = ts
    incident["version"] += 1
    incident["updated_at"] = ts
    farm = store.farms.get(incident["farm_id"])
    if farm is not None:
        if disposition == "PROBATION":
            domain.probate_farm_if_active(farm)
        elif disposition == "SUSPENSION":
            domain.suspend_farm_if_active_or_probation(farm)
        elif disposition == "REMOVAL":
            if farm["status"] != "REMOVED":
                reason = notes if notes is not MISSING else "WELFARE_INCIDENT_REMOVAL"
                domain.run_removal_cascade(farm, reason)
        # NONE: farm untouched
    return ok(incident_out(incident))
