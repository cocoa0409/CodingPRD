"""Cascades and system-driven transitions: lazy certification expiry,
contractor suspension/revocation cascades, auto-reinstatement on clock
advance, claim auto-advance on inspection completion."""
from services.helpers import parse_clock, clock_date, touch
from services.calculations import complaint_weighted_score


def lazy_expire_certifications(db):
    """ACTIVE certifications whose valid_until < current clock date -> EXPIRED."""
    today = clock_date(db)
    for cert in db.certifications.values():
        if cert["status"] == "ACTIVE" and cert.get("valid_until"):
            from datetime import date
            vu = date.fromisoformat(cert["valid_until"])
            if vu < today:
                cert["status"] = "EXPIRED"
                touch(cert)


def _return_leads(db, contractor_id):
    for la in db.lead_assignments.values():
        if la["contractor_id"] == contractor_id and la["status"] == "ASSIGNED":
            la["status"] = "RETURNED"
            touch(la)
            _recompute_pool(db, la["distributor_id"])


def _recompute_pool(db, distributor_id):
    d = db.distributors.get(distributor_id)
    if d is None:
        return
    used = sum(
        1 for la in db.lead_assignments.values()
        if la["distributor_id"] == distributor_id and la["status"] == "ASSIGNED"
    )
    d["lead_pool_available"] = d["lead_pool_total"] - used


def suspend_contractor_cascade(db, contractor):
    """Contractor ACTIVE -> SUSPENDED: suspend ACTIVE certifications,
    return ASSIGNED leads."""
    contractor["status"] = "SUSPENDED"
    touch(contractor)
    for cert in db.certifications.values():
        if cert["contractor_id"] == contractor["id"] and cert["status"] == "ACTIVE":
            cert["status"] = "SUSPENDED"
            touch(cert)
    _return_leads(db, contractor["id"])


def revoke_contractor_cascade(db, contractor):
    """Contractor -> REVOKED: revoke ACTIVE/SUSPENDED certifications, void
    their ACTIVE registrations, return ASSIGNED leads."""
    contractor["status"] = "REVOKED"
    touch(contractor)
    affected_certs = []
    for cert in db.certifications.values():
        if cert["contractor_id"] == contractor["id"] and cert["status"] in ("ACTIVE", "SUSPENDED"):
            cert["status"] = "REVOKED"
            touch(cert)
            affected_certs.append(cert["id"])
    for reg in db.registrations.values():
        if reg["certification_id"] in affected_certs and reg["status"] == "ACTIVE":
            reg["status"] = "VOID"
            touch(reg)
    _return_leads(db, contractor["id"])


def maybe_suspend_or_revoke(db, contractor):
    """After complaint substantiation: lifetime revocation first, then
    weighted suspension (only when currently ACTIVE)."""
    if contractor["lifetime_substantiated_count"] >= 8:
        if contractor["status"] != "REVOKED":
            revoke_contractor_cascade(db, contractor)
        return
    if contractor["complaint_score_24mo"] >= 5 and contractor["status"] == "ACTIVE":
        suspend_contractor_cascade(db, contractor)


def reinstate_suspended_contractors(db):
    """On clock advance: SUSPENDED contractors with lifetime < 8 and
    recomputed weighted score < 5 return to ACTIVE."""
    clock_dt = parse_clock(db.clock)
    for contractor in db.contractors.values():
        if contractor["status"] != "SUSPENDED":
            continue
        if contractor["lifetime_substantiated_count"] >= 8:
            continue
        score = complaint_weighted_score(db, contractor["id"], clock_dt)
        contractor["complaint_score_24mo"] = score
        if score < 5:
            contractor["status"] = "ACTIVE"
            touch(contractor)
