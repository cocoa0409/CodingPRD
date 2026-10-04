"""Derived state and cascade machinery (PRD sections 2.4 and 2.8)."""
import store


def dq_derived_status(dq):
    """Disqualification status is derived at read time from the logical clock:
    OVERTURNED once overturned; else COMPLETED once the current date is
    strictly past end_date; else ACTIVE."""
    if dq["overturned_at"] is not None:
        return "OVERTURNED"
    if store.today() > store.parse_date(dq["end_date"]):
        return "COMPLETED"
    return "ACTIVE"


def closed_intervals_intersect(a_start, a_end, b_start, b_end):
    """Closed-interval semantics (PRD section 2.9): shared boundary days
    collide."""
    return a_start <= b_end and b_start <= a_end


def has_certified_participation(jurisdiction_id, system):
    for p in store.db.participations.values():
        if (p["jurisdiction_id"] == jurisdiction_id
                and p["system"] == system
                and p["status"] == "CERTIFIED"):
            return True
    return False


def recompute_certified_count(jurisdiction):
    count = 0
    for p in store.db.participations.values():
        if (p["jurisdiction_id"] == jurisdiction["id"]
                and p["status"] == "CERTIFIED"):
            count += 1
    jurisdiction["certified_systems_count"] = count


def suspend_active_commercial_licenses(record_id):
    """Cascade link 3 (PRD section 2.8): a created disqualification suspends
    every ACTIVE license of class COMMERCIAL riding on the record; STANDARD
    licenses are untouched."""
    for lic in store.db.licenses.values():
        if (lic["record_id"] == record_id
                and lic["license_class"] == "COMMERCIAL"
                and lic["status"] == "ACTIVE"):
            lic["status"] = "SUSPENDED"
            store.touch(lic)


def jurisdiction_suspend_cascade(jurisdiction):
    """ACTIVE -> SUSPENDED (PRD section 2.8): link 1 drops CERTIFIED
    participations to SUSPENDED; link 2 cancels in-flight incoming transfers
    (INITIATED or CONTESTED)."""
    jid = jurisdiction["id"]
    for p in store.db.participations.values():
        if p["jurisdiction_id"] == jid and p["status"] == "CERTIFIED":
            p["status"] = "SUSPENDED"
            p["suspended_at"] = store.now_iso()
            store.touch(p)
    recompute_certified_count(jurisdiction)
    for t in store.db.license_transfers.values():
        if t["to_jurisdiction_id"] == jid and t["status"] in ("INITIATED", "CONTESTED"):
            t["status"] = "CANCELLED"
            store.touch(t)


def jurisdiction_reactivate_cascade(jurisdiction):
    """SUSPENDED -> ACTIVE (PRD section 2.8): suspended participations with at
    least one PASSED certification return to CERTIFIED with granted_at
    refreshed."""
    jid = jurisdiction["id"]
    for p in store.db.participations.values():
        if p["jurisdiction_id"] == jid and p["status"] == "SUSPENDED":
            has_passed = any(
                c["participation_id"] == p["id"] and c["status"] == "PASSED"
                for c in store.db.certifications.values())
            if has_passed:
                p["status"] = "CERTIFIED"
                p["granted_at"] = store.now_iso()
                store.touch(p)
    recompute_certified_count(jurisdiction)


def active_disqualifications(record_id):
    return [d for d in store.db.disqualifications.values()
            if d["record_id"] == record_id and dq_derived_status(d) == "ACTIVE"]


def active_record_for_driver(driver_id):
    """The one-driver-one-record invariant: at most one ACTIVE record exists
    per driver."""
    for r in store.db.records.values():
        if r["driver_id"] == driver_id and r["status"] == "ACTIVE":
            return r
    return None
