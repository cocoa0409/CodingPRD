"""Routes: agencies."""
from flask import Blueprint, request
from db import DB, stamp_new, touch
from errors import (
    err_not_found, err_invalid_request, err_duplicate, err_invalid_state,
    err_validation,
)
from middleware import require_roles, get_body
from response import success_obj, success_list, public, parse_pagination, paginate

bp = Blueprint("agencies", __name__)


@bp.post("/api/agencies")
def create_agency():
    uid, role = require_roles("PlatformAdmin")
    body = get_body()
    name = body.get("name")
    agency_code = body.get("agency_code")
    if name is None:
        raise err_invalid_request("Missing required field: name")
    if agency_code is None:
        raise err_invalid_request("Missing required field: agency_code")
    for a in DB.agencies.values():
        if a["agency_code"] == agency_code:
            raise err_duplicate("agency_code already in use")
    federally_funded = body.get("federally_funded", True)
    ftp = body.get("fleet_transition_target_pct", 0)
    tty = body.get("transition_target_year")
    rec = {
        "name": name,
        "agency_code": agency_code,
        "federally_funded": bool(federally_funded),
        "fleet_transition_target_pct": ftp,
        "transition_target_year": tty,
        "zev_ratio": 0,
        "projected_zev_ratio": 0,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    DB.agencies[rec["id"]] = rec
    return success_obj(public(rec), 201)


@bp.get("/api/agencies")
def list_agencies():
    require_roles(
        "PlatformAdmin", "ProcurementOfficer", "AgencyAdmin", "Auditor",
        "WarrantyAdmin", "AgencyInspector",
    )
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = sorted(DB.agencies.values(), key=lambda r: r["_seq"])
    if status is not None:
        items = [a for a in items if a["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([public(a) for a in window], limit, offset, total)


def get_agency_or_404(agency_id):
    a = DB.agencies.get(agency_id)
    if a is None:
        raise err_not_found("Agency not found")
    return a


@bp.get("/api/agencies/<agencyId>")
def get_agency(agencyId):
    require_roles(
        "PlatformAdmin", "ProcurementOfficer", "AgencyAdmin", "Auditor",
        "WarrantyAdmin", "AgencyInspector",
    )
    a = get_agency_or_404(agencyId)
    return success_obj(public(a))


@bp.patch("/api/agencies/<agencyId>")
def patch_agency(agencyId):
    uid, role = require_roles("AgencyAdmin", "PlatformAdmin")
    a = get_agency_or_404(agencyId)
    body = get_body()
    changed = False
    for f in ("name", "federally_funded", "fleet_transition_target_pct", "transition_target_year"):
        if f in body:
            a[f] = body[f]
            changed = True
    if "status" in body:
        target = body["status"]
        if target not in ("ACTIVE", "SUSPENDED"):
            raise err_invalid_request("Unknown status value")
        if target != a["status"]:
            if a["status"] == "ACTIVE" and target == "SUSPENDED":
                for c in DB.contracts.values():
                    if c["agency_id"] == a["id"] and c["status"] in ("AWARDED", "ACTIVE"):
                        raise err_invalid_state("Agency has AWARDED or ACTIVE contracts")
                a["status"] = "SUSPENDED"
            elif a["status"] == "SUSPENDED" and target == "ACTIVE":
                a["status"] = "ACTIVE"
            else:
                raise err_invalid_state("Illegal agency status transition")
            changed = True
    if changed:
        touch(a)
    return success_obj(public(a))


@bp.get("/api/agencies/<agencyId>/contracts")
def agency_contracts(agencyId):
    require_roles("PlatformAdmin", "ProcurementOfficer", "AgencyAdmin", "Auditor")
    get_agency_or_404(agencyId)
    limit, offset = parse_pagination(request.args)
    items = [c for c in DB.contracts.values() if c["agency_id"] == agencyId]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(c) for c in window], limit, offset, total)


@bp.get("/api/agencies/<agencyId>/training-sessions")
def agency_trainings(agencyId):
    require_roles("PlatformAdmin", "WarrantyAdmin", "AgencyAdmin")
    get_agency_or_404(agencyId)
    limit, offset = parse_pagination(request.args)
    items = [t for t in DB.trainings.values() if t["agency_id"] == agencyId]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(t) for t in window], limit, offset, total)


@bp.get("/api/agencies/<agencyId>/parts-stocks")
def agency_stocks(agencyId):
    require_roles("PlatformAdmin", "WarrantyAdmin", "AgencyAdmin")
    get_agency_or_404(agencyId)
    limit, offset = parse_pagination(request.args)
    component_id = request.args.get("component_id")
    items = [s for s in DB.stocks.values() if s["agency_id"] == agencyId]
    if component_id is not None:
        items = [s for s in items if s["component_id"] == component_id]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(s) for s in window], limit, offset, total)
