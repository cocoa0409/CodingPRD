"""Clock-driven automatic transitions (PRD section 2.5).

Applied in a single reconciliation pass whenever the logical clock is set:
- ISSUED permit with expiry_date before the current date -> EXPIRED, and its
  station in PERMITTED or CONSTRUCTION cascades to SUSPENDED.
- ACTIVE supply contract with end_date before the current date -> EXPIRED, and
  the owning site cascades ACTIVE -> SUSPENDED when no ACTIVE contract remains.
- ACTIVE service agreement with coverage_end before the current date -> EXPIRED.
- VALID training record with expires_at before the current date -> EXPIRED.

Every automatic transition increments version and refreshes updated_at.
"""

import db
import helpers
import validators as v


def maybe_suspend_site(site_id):
    site = db.sites.get(site_id)
    if site is None or site["status"] != "ACTIVE":
        return
    has_active = any(c["site_id"] == site_id and c["status"] == "ACTIVE"
                     for c in db.contracts.values())
    if not has_active:
        site["status"] = "SUSPENDED"
        helpers.touch(site)


def reconcile():
    today = db.current_date()

    for p in list(db.permits.values()):
        if p["status"] == "ISSUED" and v.parse_date(p["expiry_date"]) < today:
            p["status"] = "EXPIRED"
            helpers.touch(p)
            st = db.stations.get(p["station_id"])
            if st is not None and st["construction_status"] in ("PERMITTED", "CONSTRUCTION"):
                st["construction_status"] = "SUSPENDED"
                helpers.touch(st)

    affected_sites = set()
    for c in list(db.contracts.values()):
        if c["status"] == "ACTIVE" and v.parse_date(c["end_date"]) < today:
            c["status"] = "EXPIRED"
            helpers.touch(c)
            affected_sites.add(c["site_id"])
    for site_id in affected_sites:
        maybe_suspend_site(site_id)

    for a in list(db.agreements.values()):
        if a["status"] == "ACTIVE" and v.parse_date(a["coverage_end"]) < today:
            a["status"] = "EXPIRED"
            helpers.touch(a)

    for t in list(db.training_records.values()):
        if t["status"] == "VALID" and v.parse_date(t["expires_at"]) < today:
            t["status"] = "EXPIRED"
            helpers.touch(t)
