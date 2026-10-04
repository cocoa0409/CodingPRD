"""Path-parameter validation: parent-child chain checks."""

from db import DB
from errors import err


def get_enterprise(eid):
    e = DB.enterprises.get(eid)
    if e is None:
        raise err("ERR_NOT_FOUND", "Enterprise not found")
    return e


def get_site(sid):
    s = DB.sites.get(sid)
    if s is None:
        raise err("ERR_NOT_FOUND", "Site not found")
    return s


def get_site_mutable(sid):
    """Site lookup for write endpoints under a site: a DECOMMISSIONED site is
    terminal (PRD §2.9) and rejects further mutation with ERR_ALREADY_TERMINAL."""
    s = get_site(sid)
    if s["status"] == "DECOMMISSIONED":
        raise err("ERR_ALREADY_TERMINAL", "Site is decommissioned")
    return s


def get_site_under(sid, eid=None):
    s = get_site(sid)
    if eid is not None and s["enterprise_id"] != eid:
        raise err("ERR_NOT_FOUND", "Site not found under enterprise")
    return s


def get_cell(cid):
    c = DB.cells.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "CellSector not found")
    return c


def get_cell_under(cid, sid=None):
    c = get_cell(cid)
    if sid is not None and c["site_id"] != sid:
        raise err("ERR_NOT_FOUND", "CellSector not found under site")
    return c


def get_survey(svid, sid=None):
    r = DB.surveys.get(svid)
    if r is None or (sid is not None and r["site_id"] != sid):
        raise err("ERR_NOT_FOUND", "SiteSurvey not found")
    return r


def get_design(did, sid=None):
    r = DB.designs.get(did)
    if r is None or (sid is not None and r["site_id"] != sid):
        raise err("ERR_NOT_FOUND", "CoverageDesign not found")
    return r


def get_lease(lid, eid=None):
    r = DB.leases.get(lid)
    if r is None or (eid is not None and r["enterprise_id"] != eid):
        raise err("ERR_NOT_FOUND", "SpectrumLease not found")
    return r


def get_cr(rid, sid=None):
    r = DB.crs.get(rid)
    if r is None or (sid is not None and r["site_id"] != sid):
        raise err("ERR_NOT_FOUND", "SpectrumCoordinationRequest not found")
    return r


def get_assignment(aid, cid=None):
    r = DB.assignments.get(aid)
    if r is None or (cid is not None and r["cell_sector_id"] != cid):
        raise err("ERR_NOT_FOUND", "SpectrumAssignment not found")
    return r


def get_device(did, cid=None):
    r = DB.devices.get(did)
    if r is None or (cid is not None and r["cell_sector_id"] != cid):
        raise err("ERR_NOT_FOUND", "Device not found")
    return r


def get_sim(smid, eid=None):
    r = DB.sims.get(smid)
    if r is None or (eid is not None and r["enterprise_id"] != eid):
        raise err("ERR_NOT_FOUND", "SIMProfile not found")
    return r


def get_slice(slid, sid=None):
    r = DB.slices.get(slid)
    if r is None or (sid is not None and r["site_id"] != sid):
        raise err("ERR_NOT_FOUND", "NetworkSlice not found")
    return r


def get_binding(bid, slice_id=None):
    r = DB.bindings.get(bid)
    if r is None or (slice_id is not None and r["slice_id"] != slice_id):
        raise err("ERR_NOT_FOUND", "SliceBinding not found")
    return r


def get_contract(coid, eid=None):
    r = DB.contracts.get(coid)
    if r is None or (eid is not None and r["enterprise_id"] != eid):
        raise err("ERR_NOT_FOUND", "ServiceContract not found")
    return r


def get_alert(aid, sid=None):
    r = DB.alerts.get(aid)
    if r is None or (sid is not None and r["site_id"] != sid):
        raise err("ERR_NOT_FOUND", "MonitoringAlert not found")
    return r


def get_remediation(rid, sid=None):
    r = DB.remediations.get(rid)
    if r is None or (sid is not None and r["site_id"] != sid):
        raise err("ERR_NOT_FOUND", "CoverageRemediation not found")
    return r
