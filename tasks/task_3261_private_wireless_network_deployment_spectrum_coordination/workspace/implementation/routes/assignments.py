"""SpectrumAssignment endpoints."""

from flask import Blueprint

from auth import require_roles
from db import DB
from errors import err, ok_list, ok_object
from helpers import (apply_filters, check_window, get_body, new_resource,
                     paged, parse_iso, req_int, req_str, touch, windows_overlap)
from services import calc
from validate import get_assignment, get_cell

bp = Blueprint("assignments", __name__)

ALL = ("NetworkArchitect", "RFEngineer", "SpectrumCoordinator", "SpectrumRegulator", "FieldTechnician")
READ = ALL


@bp.post("/cells/<cid>/spectrum-assignments")
def create_assignment(cid):
    require_roles("SpectrumCoordinator")
    cell = get_cell(cid)
    site = DB.sites.get(cell["site_id"])
    body = get_body()
    cr_id = req_str(body, "coordination_request_id")
    lease_id = req_str(body, "spectrum_lease_id")
    bw = req_int(body, "assigned_bandwidth_mhz", minimum=1)
    start_s = body.get("assignment_start_utc")
    end_s = body.get("assignment_end_utc")
    if start_s is None or end_s is None:
        raise err("ERR_INVALID_REQUEST", "assignment_start_utc and assignment_end_utc are required")
    cr = DB.crs.get(cr_id)
    if cr is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "coordination_request_id does not reference an existing request")
    lease = DB.leases.get(lease_id)
    if lease is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "spectrum_lease_id does not reference an existing lease")
    start, end = check_window(start_s, end_s)
    if cr["status"] != "REGISTERED":
        raise err("ERR_INVALID_STATE", "coordination_request_id must reference a REGISTERED request")
    if lease["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "spectrum_lease_id must reference an ACTIVE lease")
    for a in DB.assignments.values():
        if a["cell_sector_id"] != cid or a["status"] != "ACTIVE":
            continue
        as_ = parse_iso(a["assignment_start_utc"], "assignment_start_utc")
        ae = parse_iso(a["assignment_end_utc"], "assignment_end_utc")
        if windows_overlap(as_, ae, start, end):
            raise err("ERR_ASSIGNMENT_OVERLAP", "Assignment window overlaps an ACTIVE assignment on this cell")
    used = sum(a["assigned_bandwidth_mhz"] for a in DB.assignments.values()
               if a["spectrum_lease_id"] == lease_id and a["status"] == "ACTIVE")
    if used + bw > lease["bandwidth_mhz"]:
        raise err("ERR_LEASE_BANDWIDTH_EXCEEDED", "Assigned bandwidth exceeds the lease's total bandwidth")
    a = new_resource()
    a.update({
        "cell_sector_id": cid,
        "coordination_request_id": cr_id,
        "spectrum_lease_id": lease_id,
        "assigned_bandwidth_mhz": bw,
        "assignment_start_utc": start_s,
        "assignment_end_utc": end_s,
        "status": "ACTIVE",
    })
    DB.assignments[a["id"]] = a
    if site is not None:
        calc.recompute_site_utilization(site)
    return ok_object(a, 201)


@bp.get("/cells/<cid>/spectrum-assignments")
def list_assignments_for_cell(cid):
    require_roles(*READ)
    get_cell(cid)
    items = [a for a in DB.assignments.values() if a["cell_sector_id"] == cid]
    items = apply_filters(items, [("status", "status")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.post("/cells/<cid>/spectrum-assignments/<aid>/release")
def release_assignment(cid, aid):
    require_roles("FieldTechnician")
    cell = get_cell(cid)
    a = get_assignment(aid, cid)
    if a["status"] in ("RELEASED", "REVOKED"):
        raise err("ERR_ALREADY_TERMINAL", "Assignment is in a terminal state")
    if cell["status"] not in ("OFF_AIR", "PLANNED"):
        raise err("ERR_INVALID_STATE", "Assignments may only be released while the cell is OFF_AIR or PLANNED")
    a["status"] = "RELEASED"
    touch(a)
    site = DB.sites.get(cell["site_id"])
    if site is not None:
        calc.recompute_site_utilization(site)
    return ok_object(a)


@bp.get("/spectrum-assignments/<aid>")
def get_assignment_flat(aid):
    require_roles(*READ)
    return ok_object(get_assignment(aid))


@bp.get("/spectrum-assignments")
def list_assignments_flat():
    require_roles(*READ)
    items = list(DB.assignments.values())
    items = apply_filters(items, [("cell_sector_id", "cell_sector_id"),
                                  ("coordination_request_id", "coordination_request_id"),
                                  ("spectrum_lease_id", "spectrum_lease_id"),
                                  ("status", "status")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)
