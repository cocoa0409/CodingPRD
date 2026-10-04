"""SpectrumCoordinationRequest endpoints."""

from flask import Blueprint

from auth import require_roles
from db import DB
from errors import err, ok_list, ok_object
from helpers import (apply_filters, check_window, get_body, new_resource,
                     paged, parse_iso, req_enum, req_field, req_int, req_str,
                     touch, windows_overlap)
from services import calc
from validate import get_cr, get_site, get_site_mutable
from routes.leases import BANDS

bp = Blueprint("coordination", __name__)

READ = ("NetworkArchitect", "RFEngineer", "SpectrumCoordinator", "SpectrumRegulator")
CR_TERMINAL = ("REGISTERED", "REJECTED", "WITHDRAWN")


@bp.post("/sites/<sid>/coordination-requests")
def create_cr(sid):
    require_roles("SpectrumCoordinator")
    get_site_mutable(sid)
    body = get_body()
    coord = req_str(body, "requesting_coordinator_id")
    band = req_enum(body, "band_class", BANDS)
    bw = req_int(body, "requested_bandwidth_mhz", minimum=1)
    start_s = body.get("requested_start_utc")
    end_s = body.get("requested_end_utc")
    if start_s is None or end_s is None:
        raise err("ERR_INVALID_REQUEST", "requested_start_utc and requested_end_utc are required")
    check_window(start_s, end_s)
    r = new_resource()
    r.update({
        "site_id": sid,
        "requesting_coordinator_id": coord,
        "band_class": band,
        "requested_bandwidth_mhz": bw,
        "requested_start_utc": start_s,
        "requested_end_utc": end_s,
        "sas_registration_id": None,
        "interference_report": None,
        "status": "DRAFT",
    })
    DB.crs[r["id"]] = r
    return ok_object(r, 201)


@bp.get("/sites/<sid>/coordination-requests")
def list_crs_for_site(sid):
    require_roles(*READ)
    get_site(sid)
    items = [r for r in DB.crs.values() if r["site_id"] == sid]
    items = apply_filters(items, [("status", "status"), ("band_class", "band_class")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/sites/<sid>/coordination-requests/<rid>")
def get_one_cr(sid, rid):
    require_roles(*READ)
    get_site(sid)
    return ok_object(get_cr(rid, sid))


@bp.post("/sites/<sid>/coordination-requests/<rid>/submit")
def submit_cr(sid, rid):
    uid, _ = require_roles("SpectrumCoordinator")
    site = get_site_mutable(sid)
    r = get_cr(rid, sid)
    if r["status"] in CR_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Request is in a terminal state")
    if r["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Request must be DRAFT to submit")
    if r["requesting_coordinator_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Only the filing coordinator may submit the request")
    if site["status"] != "DESIGNED":
        raise err("ERR_INVALID_STATE", "Site must be DESIGNED to submit a coordination request")
    r["status"] = "SUBMITTED"
    touch(r)
    return ok_object(r)


@bp.post("/sites/<sid>/coordination-requests/<rid>/begin-coordination")
def begin_coordination(sid, rid):
    require_roles("SpectrumCoordinator")
    site = get_site_mutable(sid)
    r = get_cr(rid, sid)
    if r["status"] in CR_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Request is in a terminal state")
    if r["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Request must be SUBMITTED to begin coordination")
    freq = _center_frequency_for(r)
    r["interference_report"] = calc.interference_report(sid, freq)
    r["status"] = "COORDINATING"
    touch(r)
    return ok_object(r)


def _center_frequency_for(cr):
    """Center frequency for FSPL: the covering ACTIVE lease for this band on the
    site's enterprise, else a band default."""
    site = DB.sites.get(cr["site_id"])
    if site is not None:
        for l in DB.leases.values():
            if l["enterprise_id"] == site["enterprise_id"] and l["band_class"] == cr["band_class"] \
                    and l["status"] in ("ACTIVE", "PENDING", "SUSPENDED"):
                return float(l["center_frequency_mhz"])
    defaults = {"LICENSED_C_BAND": 3750.0, "SHARED_CBRS": 3550.0,
                "UNLICENSED_5GHZ": 5500.0, "UNLICENSED_6GHZ": 6500.0}
    return defaults[cr["band_class"]]


def _pal_overlap_for_request(cr):
    """PAL overlap: another PAL lease on the same band whose center frequency is
    within ±10 MHz, with window overlapping the requested window."""
    start = parse_iso(cr["requested_start_utc"], "requested_start_utc")
    end = parse_iso(cr["requested_end_utc"], "requested_end_utc")
    center = _center_frequency_for(cr)
    for l in DB.leases.values():
        if l["band_class"] != cr["band_class"]:
            continue
        if l.get("priority_access_tier") != "PAL":
            continue
        if l["status"] in ("CANCELLED", "EXPIRED"):
            continue
        if abs(float(l["center_frequency_mhz"]) - center) > 10.0:
            continue
        ls = parse_iso(l["lease_start_utc"], "lease_start_utc")
        le = parse_iso(l["lease_end_utc"], "lease_end_utc")
        if windows_overlap(ls, le, start, end):
            return True
    return False


def _request_tier(cr):
    """PAL if an ACTIVE/PENDING PAL lease covers this band for the enterprise."""
    site = DB.sites.get(cr["site_id"])
    if site is None:
        return None
    for l in DB.leases.values():
        if l["enterprise_id"] == site["enterprise_id"] and l["band_class"] == cr["band_class"] \
                and l.get("priority_access_tier") == "PAL" and l["status"] in ("ACTIVE", "PENDING", "SUSPENDED"):
            return "PAL"
    return None


@bp.post("/sites/<sid>/coordination-requests/<rid>/approve")
def approve_cr(sid, rid):
    uid, _ = require_roles("SpectrumRegulator")
    get_site_mutable(sid)
    r = get_cr(rid, sid)
    body = get_body()
    expected = req_field(body, "expected_request_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_request_version must be an integer")
    if r["status"] in CR_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Request is in a terminal state")
    if r["status"] != "COORDINATING":
        raise err("ERR_INVALID_STATE", "Request must be COORDINATING to approve")
    if r["requesting_coordinator_id"] == uid:
        raise err("ERR_SEGREGATION_OF_DUTY", "The filing coordinator may not approve their own request")
    report = r.get("interference_report") or {}
    if report.get("worst_case_margin_db", 99.0) < 0:
        raise err("ERR_INTERFERENCE_MARGIN_EXCEEDED", "Worst-case interference margin is below 0 dB")
    if cr_is_pal(r) and _pal_overlap_for_request(r):
        raise err("ERR_SPECTRUM_OVERLAP",
                  "A PAL lease on the same band and frequency bucket has an overlapping window")
    if expected != r["version"]:
        raise err("ERR_STALE_REQUEST_VERSION", "expected_request_version does not match the request's current version")
    r["sas_registration_id"] = calc.mint_sas_id()
    r["status"] = "APPROVED"
    touch(r)
    return ok_object(r)


def cr_is_pal(cr):
    return cr["band_class"] == "SHARED_CBRS" and _request_tier(cr) == "PAL"


@bp.post("/sites/<sid>/coordination-requests/<rid>/reject")
def reject_cr(sid, rid):
    require_roles("SpectrumRegulator")
    get_site_mutable(sid)
    r = get_cr(rid, sid)
    if r["status"] in CR_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Request is in a terminal state")
    if r["status"] != "COORDINATING":
        raise err("ERR_INVALID_STATE", "Request must be COORDINATING to reject")
    r["status"] = "REJECTED"
    touch(r)
    return ok_object(r)


@bp.post("/sites/<sid>/coordination-requests/<rid>/register")
def register_cr(sid, rid):
    require_roles("SpectrumCoordinator")
    site = get_site_mutable(sid)
    r = get_cr(rid, sid)
    if r["status"] in CR_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Request is in a terminal state")
    if r["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Request must be APPROVED to register")
    if not r.get("sas_registration_id"):
        raise err("ERR_INVALID_STATE", "Request has no SAS registration id")
    start = parse_iso(r["requested_start_utc"], "requested_start_utc")
    end = parse_iso(r["requested_end_utc"], "requested_end_utc")
    covering = False
    for l in DB.leases.values():
        if l["enterprise_id"] != site["enterprise_id"]:
            continue
        if l["band_class"] != r["band_class"]:
            continue
        if l["status"] != "ACTIVE":
            continue
        ls = parse_iso(l["lease_start_utc"], "lease_start_utc")
        le = parse_iso(l["lease_end_utc"], "lease_end_utc")
        if ls <= start and end <= le:
            covering = True
            break
    if not covering:
        raise err("ERR_NO_ACTIVE_LEASE",
                  "No ACTIVE SpectrumLease covers the requested band and window")
    first = not any(o["site_id"] == sid and o["status"] == "REGISTERED" for o in DB.crs.values())
    r["status"] = "REGISTERED"
    touch(r)
    if first and site["status"] == "DESIGNED":
        site["status"] = "COORDINATED"
        site["posture"] = "DEPLOYING"
        touch(site)
    return ok_object(r)


@bp.post("/sites/<sid>/coordination-requests/<rid>/withdraw")
def withdraw_cr(sid, rid):
    uid, _ = require_roles("SpectrumCoordinator")
    get_site_mutable(sid)
    r = get_cr(rid, sid)
    if r["status"] in CR_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL", "Request is in a terminal state")
    if r["requesting_coordinator_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Only the filing coordinator may withdraw the request")
    r["status"] = "WITHDRAWN"
    touch(r)
    return ok_object(r)


@bp.get("/coordination-requests/<rid>")
def get_cr_flat(rid):
    require_roles(*READ)
    return ok_object(get_cr(rid))


@bp.get("/coordination-requests")
def list_crs_flat():
    require_roles(*READ)
    items = list(DB.crs.values())
    items = apply_filters(items, [("site_id", "site_id"),
                                  ("requesting_coordinator_id", "requesting_coordinator_id"),
                                  ("band_class", "band_class"), ("status", "status")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)
