"""Cross-entity side effects: cascades, revocations, clock re-evaluation."""

from db import DB
from helpers import new_resource, stamp, touch, parse_iso
from services import calc


def revoke_assignment(a):
    """System revocation when backing lease expires or is cancelled."""
    if a["status"] != "ACTIVE":
        return
    a["status"] = "REVOKED"
    touch(a)
    cell = DB.cells.get(a["cell_sector_id"])
    if cell is not None:
        # The affected cell drops to DEGRADED (PRD §3.4/§3.5).
        if cell["status"] in ("ON_AIR", "CONFIGURED"):
            cell["status"] = "DEGRADED"
            touch(cell)
        site = DB.sites.get(cell["site_id"])
        if site is not None:
            calc.recompute_site_utilization(site)
            touch(site)
            alert = new_resource(common=False)
            alert.update({
                "site_id": site["id"],
                "alert_class": "OUTAGE",
                "severity": "MAJOR",
                "raised_at_utc": stamp(),
                "resolved_at_utc": None,
                "sla_credit_applied_cents": 0,
                "status": "OPEN",
            })
            DB.alerts[alert["id"]] = alert


def revoke_assignments_on_lease(lease):
    for a in DB.assignments.values():
        if a["spectrum_lease_id"] == lease["id"]:
            revoke_assignment(a)


def supersede_survey(old_survey):
    """Move old approved survey to SUPERSEDED; reject designs based on it."""
    old_survey["status"] = "SUPERSEDED"
    touch(old_survey)
    for d in DB.designs.values():
        if d["based_on_survey_id"] == old_survey["id"] and d["status"] == "APPROVED":
            supersede_design(d)


def supersede_design(design):
    design["status"] = "SUPERSEDED"
    touch(design)
    for c in DB.cells.values():
        if c["site_id"] == design["site_id"] and c["status"] == "PLANNED":
            decommission_cell(c)


def decommission_cell(cell):
    if cell["status"] == "DECOMMISSIONED":
        return
    for a in DB.assignments.values():
        if a["cell_sector_id"] == cell["id"] and a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            touch(a)
    cell["status"] = "DECOMMISSIONED"
    touch(cell)
    site = DB.sites.get(cell["site_id"])
    if site is not None:
        calc.recompute_site_utilization(site)


def teardown_device_bindings(device):
    now = stamp()
    for b in DB.bindings.values():
        if b["device_id"] == device["id"] and b.get("unbound_at_utc") is None:
            b["unbound_at_utc"] = now
            sl = DB.slices.get(b["slice_id"])
            if sl is not None and sl.get("bound_device_count", 0) > 0:
                sl["bound_device_count"] -= 1
                touch(sl)


def sites_without_active_contract(enterprise_id):
    """After contract termination: OPERATIONAL sites of the enterprise with no
    other ACTIVE contract on the enterprise drop to REMEDIATION_REQUIRED."""
    has_active = any(
        c["enterprise_id"] == enterprise_id and c["status"] == "ACTIVE"
        for c in DB.contracts.values()
    )
    if has_active:
        return
    for s in DB.sites.values():
        if s["enterprise_id"] == enterprise_id and s["status"] == "OPERATIONAL":
            s["status"] = "REMEDIATION_REQUIRED"
            s["posture"] = "REMEDIATING"
            touch(s)


def reevaluate_clock():
    """Re-evaluate time-derived rules after a logical clock change."""
    now = DB.clock
    for lease in list(DB.leases.values()):
        if lease["status"] == "ACTIVE":
            end = parse_iso(lease["lease_end_utc"], "lease_end_utc")
            if end <= now:
                lease["status"] = "EXPIRED"
                touch(lease)
                revoke_assignments_on_lease(lease)
