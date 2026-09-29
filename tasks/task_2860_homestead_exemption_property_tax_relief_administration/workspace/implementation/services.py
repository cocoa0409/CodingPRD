"""Cross-entity services: notices, the conserved relief ledger, grant status
changes with their parcel cascades, and the shared lookup helpers.
"""

import calc
import db


# --------------------------------------------------------------------------
# Notices (PRD §3.9) — never created by a direct request
# --------------------------------------------------------------------------
def mail_notice(taxpayer_id, subject_type, subject_id, notice_type, body_summary,
                appealable=True):
    mailed_at = db.now()
    notice = {
        "taxpayer_id": taxpayer_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "notice_type": notice_type,
        "mailed_at": db.iso(mailed_at),
        "appeal_deadline": db.iso(db.plus_days(mailed_at, db.APPEAL_WINDOW_DAYS)),
        "appealable": appealable,
        "body_summary": body_summary,
    }
    return db.insert("notices", notice)


# --------------------------------------------------------------------------
# The conserved relief ledger (PRD §2.11)
# --------------------------------------------------------------------------
def rederive_net_relief(taxpayer):
    taxpayer["net_relief_cents"] = (
        taxpayer["lifetime_refund_cents"] - taxpayer["lifetime_recovery_collected_cents"]
    )


def add_refund(taxpayer, delta_cents):
    taxpayer["lifetime_refund_cents"] += delta_cents
    rederive_net_relief(taxpayer)


def add_recovery_collected(taxpayer, delta_cents):
    taxpayer["lifetime_recovery_collected_cents"] += delta_cents
    rederive_net_relief(taxpayer)


def refresh_taxpayer_status(taxpayer):
    """FLAGGED while an investigation is open; BARRED once a case is substantiated."""
    cases = db.find("fraud_cases", taxpayer_id=taxpayer["id"])
    if any(c["investigation_status"] == "OPEN" for c in cases):
        taxpayer["status"] = "FLAGGED"
    elif any(c["investigation_status"] == "SUBSTANTIATED" for c in cases):
        taxpayer["status"] = "BARRED"
    else:
        taxpayer["status"] = "GOOD_STANDING"


def has_open_fraud_case(taxpayer_id):
    return any(
        c["investigation_status"] == "OPEN"
        for c in db.find("fraud_cases", taxpayer_id=taxpayer_id)
    )


# --------------------------------------------------------------------------
# Grant status changes and their parcel cascade
# --------------------------------------------------------------------------
def redecompose_parcel(parcel_id):
    parcel = db.get("parcels", parcel_id)
    if parcel is not None:
        calc.decompose(parcel)
    return parcel


def set_grant_status(grant, status, suspension_reason=None):
    grant["benefit_status"] = status
    grant["suspension_reason"] = suspension_reason
    db.touch(grant)
    redecompose_parcel(grant["parcel_id"])
    return grant


def suspend_grant(grant, reason, notice=True, summary=None):
    set_grant_status(grant, "SUSPENDED", reason)
    if notice:
        mail_notice(
            grant["taxpayer_id"],
            "EXEMPTION_GRANT",
            grant["id"],
            "SUSPENSION",
            summary or ("Exemption grant suspended: %s." % reason),
        )
    return grant


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
def certified_certification(taxpayer_id, year):
    """The CERTIFIED certification for a taxpayer and year, greatest created_at."""
    candidates = [
        c
        for c in db.rows("income_certifications")
        if c["taxpayer_id"] == taxpayer_id
        and c["certification_year"] == year
        and c["status"] == "CERTIFIED"
    ]
    return db.latest(candidates)


def has_certified_from_year(taxpayer_id, year):
    return any(
        c["taxpayer_id"] == taxpayer_id
        and c["status"] == "CERTIFIED"
        and c["certification_year"] >= year
        for c in db.rows("income_certifications")
    )


def income_dor_certification(taxpayer_id, year):
    """Selector of PRD §3.3: greatest created_at, tie-break greatest version."""
    candidates = [
        c
        for c in db.rows("income_certifications")
        if c["taxpayer_id"] == taxpayer_id
        and c["certification_year"] == year
        and c["status"] in ("PENDING", "CERTIFIED")
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda c: (c["created_at"], c.get("version", 1), c["_seq"]),
    )[-1]


def latest_registry_record(taxpayer_id, source):
    candidates = [
        r
        for r in db.rows("registry_records")
        if r["taxpayer_id"] == taxpayer_id and r["source"] == source
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda r: (r["record_effective_date"], r["_seq"]))[-1]


def covers(record, iso_date, new_end=None):
    """Half-open [occupancy_start_date, occupancy_end_date) coverage test."""
    start = record["occupancy_start_date"]
    end = new_end if new_end is not None else record["occupancy_end_date"]
    if iso_date < start:
        return False
    if end is None:
        return True
    return iso_date < end


def verified_ownership(parcel_id, taxpayer_id, occupancy_type, iso_date):
    """The VERIFIED record of the demanded occupancy covering a calendar date."""
    candidates = [
        r
        for r in db.rows("ownership_records")
        if r["parcel_id"] == parcel_id
        and r["taxpayer_id"] == taxpayer_id
        and r["status"] == "VERIFIED"
        and r["occupancy_type"] == occupancy_type
        and covers(r, iso_date)
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda r: (r["occupancy_start_date"], r["created_at"], r["_seq"]),
    )[-1]


def latest_check_per_source(application_id, source):
    candidates = [
        c
        for c in db.rows("verification_checks")
        if c["application_id"] == application_id and c["source"] == source
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda c: (c["checked_at"], c["created_at"], c["_seq"]))[-1]


def docket_slot_count(docket_id):
    return len(
        [
            a
            for a in db.rows("appeals")
            if a["docket_id"] == docket_id
            and a["status"] in ("SCHEDULED", "GRANTED", "DENIED", "DISMISSED")
        ]
    )


def rederive_docket_count(docket):
    docket["scheduled_appeal_count"] = docket_slot_count(docket["id"])
    db.touch(docket)
    return docket


def outstanding_recovery(taxpayer_id):
    total = 0
    for case in db.find("fraud_cases", taxpayer_id=taxpayer_id):
        if case["recovery_status"] in ("ASSESSED", "PARTIALLY_PAID"):
            total += case["total_assessed_cents"] - case["recovery_paid_cents"]
    return total
