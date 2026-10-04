"""CoverageRemediation endpoints."""

from flask import Blueprint

from auth import require_roles
from db import DB
from errors import err, ok_list, ok_object
from helpers import (apply_filters, get_body, new_resource, opt_int, paged,
                     parse_iso, req_int, req_str, stamp, touch)
from validate import get_remediation, get_site, get_site_mutable

bp = Blueprint("remediations", __name__)

READ = ("NetworkArchitect", "RFEngineer", "FieldTechnician")


@bp.post("/sites/<sid>/remediations")
def create_remediation(sid):
    require_roles("RFEngineer")
    get_site_mutable(sid)
    body = get_body()
    alert_id = req_str(body, "triggered_by_alert_id")
    supersedes = body.get("supersedes_remediation_id")
    plan = req_str(body, "remediation_plan")
    cells = req_int(body, "additional_cells_planned", minimum=0)
    spectrum = opt_int(body, "additional_spectrum_mhz", 0, minimum=0)
    alert = DB.alerts.get(alert_id)
    if alert is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "triggered_by_alert_id does not reference an existing alert")
    if supersedes is not None:
        if not isinstance(supersedes, str) or supersedes not in DB.remediations:
            raise err("ERR_REFERENCE_NOT_FOUND", "supersedes_remediation_id does not reference an existing remediation")
    r = new_resource()
    r.update({
        "site_id": sid,
        "triggered_by_alert_id": alert_id,
        "supersedes_remediation_id": supersedes,
        "remediation_plan": plan,
        "additional_cells_planned": cells,
        "additional_spectrum_mhz": spectrum,
        "in_progress_started_at_utc": None,
        "status": "PROPOSED",
    })
    DB.remediations[r["id"]] = r
    return ok_object(r, 201)


@bp.get("/sites/<sid>/remediations")
def list_remediations_for_site(sid):
    require_roles(*READ)
    get_site(sid)
    items = [r for r in DB.remediations.values() if r["site_id"] == sid]
    items = apply_filters(items, [("status", "status")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/sites/<sid>/remediations/<rid>")
def get_one_remediation(sid, rid):
    require_roles(*READ)
    get_site(sid)
    return ok_object(get_remediation(rid, sid))


def _terminal(r):
    if r["status"] == "COMPLETED":
        raise err("ERR_ALREADY_TERMINAL", "Remediation is completed")


@bp.post("/sites/<sid>/remediations/<rid>/approve")
def approve_remediation(sid, rid):
    require_roles("NetworkArchitect")
    get_site_mutable(sid)
    r = get_remediation(rid, sid)
    _terminal(r)
    if r["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Remediation must be PROPOSED to approve")
    r["status"] = "APPROVED"
    touch(r)
    return ok_object(r)


@bp.post("/sites/<sid>/remediations/<rid>/start")
def start_remediation(sid, rid):
    require_roles("RFEngineer")
    get_site_mutable(sid)
    r = get_remediation(rid, sid)
    _terminal(r)
    if r["status"] not in ("APPROVED", "REOPENED"):
        raise err("ERR_INVALID_STATE", "Remediation must be APPROVED or REOPENED to start")
    r["in_progress_started_at_utc"] = stamp()
    r["status"] = "IN_PROGRESS"
    touch(r)
    return ok_object(r)


@bp.post("/sites/<sid>/remediations/<rid>/verify")
def verify_remediation(sid, rid):
    require_roles("FieldTechnician")
    get_site_mutable(sid)
    r = get_remediation(rid, sid)
    _terminal(r)
    if r["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Remediation must be IN_PROGRESS to verify")
    started = parse_iso(r["in_progress_started_at_utc"], "in_progress_started_at_utc")
    new_on_air = 0
    for c in DB.cells.values():
        if c["site_id"] != sid or c["status"] != "ON_AIR":
            continue
        created = parse_iso(c["created_at"], "created_at")
        if created >= started:
            new_on_air += 1
    if new_on_air != r["additional_cells_planned"]:
        raise err("ERR_REMEDIATION_CELLS_MISSING",
                  "Newly added ON_AIR cells since remediation start do not match additional_cells_planned")
    r["status"] = "VERIFYING"
    touch(r)
    return ok_object(r)


@bp.post("/sites/<sid>/remediations/<rid>/complete")
def complete_remediation(sid, rid):
    require_roles("NetworkArchitect")
    site = get_site_mutable(sid)
    r = get_remediation(rid, sid)
    _terminal(r)
    if r["status"] != "VERIFYING":
        raise err("ERR_INVALID_STATE", "Remediation must be VERIFYING to complete")
    r["status"] = "COMPLETED"
    touch(r)
    if site["status"] == "REMEDIATION_REQUIRED":
        site["status"] = "OPERATIONAL"
        site["posture"] = "OPERATIONAL"
        touch(site)
    return ok_object(r)


@bp.post("/sites/<sid>/remediations/<rid>/reopen")
def reopen_remediation(sid, rid):
    require_roles("NetworkArchitect")
    get_site_mutable(sid)
    r = get_remediation(rid, sid)
    _terminal(r)
    if r["status"] != "VERIFYING":
        raise err("ERR_INVALID_STATE", "Remediation must be VERIFYING to reopen")
    r["status"] = "REOPENED"
    touch(r)
    return ok_object(r)


@bp.get("/remediations/<rid>")
def get_remediation_flat(rid):
    require_roles(*READ)
    return ok_object(get_remediation(rid))


@bp.get("/remediations")
def list_remediations_flat():
    require_roles(*READ)
    items = list(DB.remediations.values())
    items = apply_filters(items, [("site_id", "site_id"),
                                  ("triggered_by_alert_id", "triggered_by_alert_id"),
                                  ("supersedes_remediation_id", "supersedes_remediation_id"),
                                  ("status", "status")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)
