"""SpectrumLease endpoints."""

from flask import Blueprint

from auth import require_roles
from db import DB
from errors import err, ok_list, ok_object
from helpers import (apply_filters, check_window, get_body, new_resource,
                     opt_enum, paged, parse_iso, req_enum, req_int, req_num,
                     touch, windows_overlap)
from services import effects
from validate import get_enterprise, get_lease

bp = Blueprint("leases", __name__)

READ = ("NetworkArchitect", "RFEngineer", "SpectrumCoordinator", "SpectrumRegulator")
BANDS = ("LICENSED_C_BAND", "SHARED_CBRS", "UNLICENSED_5GHZ", "UNLICENSED_6GHZ")
TIERS = ("PAL", "GAA")
LEASE_TERMINAL = ("EXPIRED", "CANCELLED")


def _pal_overlap(enterprise_id, band, center, start, end, exclude_id=None):
    """Any other PAL SHARED_CBRS lease on the same band within ±10 MHz bucket
    whose window overlaps [start, end)."""
    for l in DB.leases.values():
        if exclude_id is not None and l["id"] == exclude_id:
            continue
        if l["enterprise_id"] != enterprise_id:
            continue
        if l["band_class"] != band:
            continue
        if l.get("priority_access_tier") != "PAL":
            continue
        if l["status"] in LEASE_TERMINAL:
            continue
        if abs(float(l["center_frequency_mhz"]) - float(center)) > 10.0:
            continue
        ls = parse_iso(l["lease_start_utc"], "lease_start_utc")
        le = parse_iso(l["lease_end_utc"], "lease_end_utc")
        if windows_overlap(ls, le, start, end):
            return True
    return False


@bp.post("/enterprises/<eid>/spectrum-leases")
def create_lease(eid):
    require_roles("SpectrumCoordinator")
    get_enterprise(eid)
    body = get_body()
    band = req_enum(body, "band_class", BANDS)
    center = req_num(body, "center_frequency_mhz")
    bw = req_int(body, "bandwidth_mhz", minimum=1)
    tier = opt_enum(body, "priority_access_tier", TIERS, "GAA") if band == "SHARED_CBRS" else body.get("priority_access_tier")
    if band != "SHARED_CBRS":
        tier = None
    start_s = body.get("lease_start_utc")
    end_s = body.get("lease_end_utc")
    if start_s is None or end_s is None:
        raise err("ERR_INVALID_REQUEST", "lease_start_utc and lease_end_utc are required")
    start, end = check_window(start_s, end_s)
    cost = req_int(body, "monthly_cost_cents", minimum=0)
    if band == "SHARED_CBRS" and tier == "PAL":
        if _pal_overlap(eid, band, center, start, end):
            raise err("ERR_SPECTRUM_OVERLAP",
                      "A PAL lease on the same band and frequency bucket has an overlapping window")
    l = new_resource()
    l.update({
        "enterprise_id": eid,
        "band_class": band,
        "center_frequency_mhz": center,
        "bandwidth_mhz": bw,
        "lease_start_utc": start_s,
        "lease_end_utc": end_s,
        "priority_access_tier": tier,
        "monthly_cost_cents": cost,
        "status": "PENDING",
    })
    DB.leases[l["id"]] = l
    return ok_object(l, 201)


@bp.get("/enterprises/<eid>/spectrum-leases")
def list_leases_for_enterprise(eid):
    require_roles(*READ)
    get_enterprise(eid)
    items = [l for l in DB.leases.values() if l["enterprise_id"] == eid]
    items = apply_filters(items, [("status", "status"), ("band_class", "band_class")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/spectrum-leases/<lid>")
def get_one_lease(lid):
    require_roles(*READ)
    return ok_object(get_lease(lid))


@bp.get("/spectrum-leases")
def list_leases_flat():
    require_roles(*READ)
    items = list(DB.leases.values())
    items = apply_filters(items, [("enterprise_id", "enterprise_id"), ("status", "status"), ("band_class", "band_class")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.post("/spectrum-leases/<lid>/activate")
def activate_lease(lid):
    require_roles("SpectrumCoordinator")
    l = get_lease(lid)
    if l["status"] in LEASE_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Lease is in a terminal state")
    if l["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Lease must be PENDING to activate")
    l["status"] = "ACTIVE"
    touch(l)
    return ok_object(l)


@bp.post("/spectrum-leases/<lid>/cancel")
def cancel_lease(lid):
    require_roles("SpectrumCoordinator")
    l = get_lease(lid)
    if l["status"] in LEASE_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Lease is in a terminal state")
    effects.revoke_assignments_on_lease(l)
    l["status"] = "CANCELLED"
    touch(l)
    return ok_object(l)
