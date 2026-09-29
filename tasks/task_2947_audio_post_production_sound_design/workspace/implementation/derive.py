"""Derived project state: posture, ledgers, billing roll-up, pipeline advance and
the R-STALE invalidation cascade (PRD §2.9, §2.10, §3.8)."""

from decimal import Decimal

import calc
import clock
from db import db, oldest_first, touch

LIVE_STEM_STATUSES = ("DRAFT", "CONFORMED", "STALE")
RESERVING_BOOKING_STATUSES = ("RESERVED", "CONFIRMED", "IN_PROGRESS")
OPEN_DELIVERABLE_STATUSES = (
    "PREPARED",
    "QC_SUBMITTED",
    "QC_REJECTED",
    "REMEDIATION",
    "QC_PASSED",
)
ADR_MONEY_STATUSES = ("CONFIRMED", "RECORDED", "NO_SHOW")

# PRD §2.9: RESTRICTED "permits ... but rejects QC submission, QC evaluation,
# delivery and archival".
RESTRICTED_BLOCKED_OPS = ("qc_submit", "qc_evaluate", "deliver", "archive")


# ------------------------------------------------------------------ selectors
def stem_packages_of(project_id):
    return [p for p in db.stem_packages.values() if p["project_id"] == project_id]


def bookings_of(project_id):
    return [b for b in db.mix_bookings.values() if b["project_id"] == project_id]


def sessions_of(project_id):
    return [s for s in db.adr_sessions.values() if s["project_id"] == project_id]


def deliverables_of(project_id):
    return [d for d in db.deliverables.values() if d["project_id"] == project_id]


def cues_of(stem_package_id):
    return [c for c in db.music_cues.values() if c["stem_package_id"] == stem_package_id]


def usages_of_package(stem_package_id):
    return [u for u in db.asset_usages.values() if u["stem_package_id"] == stem_package_id]


def live_usages_of_project(project_id):
    """PRD §2.9/§3.4 input set: usages whose stem package belongs to the project
    with a status of DRAFT, CONFORMED or STALE (RETIRED excluded)."""
    live_ids = {p["id"] for p in stem_packages_of(project_id)
                if p["status"] in LIVE_STEM_STATUSES}
    return [u for u in db.asset_usages.values() if u["stem_package_id"] in live_ids]


def project_of_package(package):
    return db.projects.get(package["project_id"])


# ------------------------------------------------------------------- posture
def posture_of(project):
    """PRD §2.9 precedence: LOCK_BROKEN wins, then any stale/unlicensed count."""
    if project["picture_status"] == "LOCK_BROKEN":
        return "FROZEN"
    if project["unlicensed_usage_count"] >= 1 or project["stale_stem_count"] >= 1:
        return "RESTRICTED"
    return "OPEN"


def recompute_project(project):
    """Recomputes every derived project field except the two licence risk scores,
    which PRD §3.4 recomputes only on asset-usage creation and asset revocation."""
    packages = stem_packages_of(project["id"])
    project["stale_stem_count"] = sum(1 for p in packages if p["status"] == "STALE")
    project["conformed_stem_count"] = sum(1 for p in packages if p["status"] == "CONFORMED")

    usages = live_usages_of_project(project["id"])
    project["unlicensed_usage_count"] = sum(
        1 for u in usages if u["clearance_status"] == "UNLICENSED")
    project["license_fee_accrued_cents"] = sum(
        u["accrued_fee_cents"] for u in usages if u["clearance_status"] == "CLEARED")

    bookings = bookings_of(project["id"])
    reserved = Decimal("0.00")
    consumed = Decimal("0.00")
    stage_cost = 0
    for booking in bookings:
        if booking["status"] in RESERVING_BOOKING_STATUSES:
            reserved = reserved + booking["reserved_hours"]
            stage_cost = stage_cost + booking["provisional_cost_cents"]
        elif booking["status"] == "COMPLETED":
            consumed = consumed + (booking["billable_hours_final"] or Decimal("0.00"))
            stage_cost = stage_cost + (booking["final_cost_cents"] or 0)
    project["stage_hours_reserved"] = calc.q2(reserved)
    project["stage_hours_consumed"] = calc.q2(consumed)
    project["stage_hours_available"] = calc.q2(
        project["stage_hours_authorized"] - reserved - consumed)
    project["stage_cost_subtotal_cents"] = stage_cost

    project["adr_cost_cents"] = sum(
        s["session_cost_cents"] for s in sessions_of(project["id"])
        if s["status"] in ADR_MONEY_STATUSES)

    project["conform_fee_total_cents"] = sum(
        p["conform_fee_cents"] for p in packages if p["status"] in ("CONFORMED", "STALE"))

    rollup = calc.project_billing_total(
        project["stage_cost_subtotal_cents"],
        project["adr_cost_cents"],
        project["conform_fee_total_cents"],
        project["license_fee_accrued_cents"],
        project["turnaround_class"],
    )
    project.update(rollup)

    project["posture"] = posture_of(project)


def recompute_license_scores(project):
    """PRD §3.4: both scores are recomputed on asset-usage creation and on asset
    revocation, over the project's live usages."""
    intake, audit = calc.license_risk_scores(
        live_usages_of_project(project["id"]), db.library_assets, clock.now())
    project["license_risk_score_intake"] = intake
    project["license_risk_score_audit"] = audit


def touch_project(project):
    touch(project)


def advance_pipeline(project, from_stage, to_stage):
    """Each advance fires only when the project currently sits at `from_stage`
    (PRD §3.2)."""
    if project["pipeline_stage"] == from_stage:
        project["pipeline_stage"] = to_stage
        return True
    return False


# ------------------------------------------------------- R-STALE cascade
def mark_stem_package_stale(package, stale_reason, affected_project_ids):
    """The full three-hop invalidation cascade of PRD §2.10.

    Hop A stales the package itself.  Hop B invalidates every deliverable of that
    package sitting in an open status.  Hop C releases each such deliverable's
    RESERVED or CONFIRMED booking.  Every touched entity refreshes updated_at and
    bumps its own version by 1.
    """
    package["status"] = "STALE"
    package["stale_reason"] = stale_reason
    touch(package)
    affected_project_ids.add(package["project_id"])
    cascade_from_stale_package(package, affected_project_ids)


def cascade_from_stale_package(package, affected_project_ids):
    """Hops B and C of PRD §2.10, without re-touching the package itself.  Cue
    creation uses this form because PRD §3.3 pins that request to exactly one
    stem-package version bump."""
    affected_project_ids.add(package["project_id"])

    for deliverable in oldest_first(
            [d for d in db.deliverables.values()
             if d["stem_package_id"] == package["id"]]):
        if deliverable["status"] not in OPEN_DELIVERABLE_STATUSES:
            continue
        deliverable["status"] = "INVALIDATED"
        deliverable["invalidation_reason"] = "STEM_STALE"
        touch(deliverable)
        affected_project_ids.add(deliverable["project_id"])

        booking = db.mix_bookings.get(deliverable["mix_booking_id"])
        if booking is not None and booking["status"] in ("RESERVED", "CONFIRMED"):
            booking["status"] = "RELEASED"
            booking["release_reason"] = "DELIVERABLE_INVALIDATED"
            touch(booking)
            affected_project_ids.add(booking["project_id"])


def stale_conformed_packages(project, stale_reason, affected_project_ids):
    """Used by break-picture-lock: every CONFORMED package of the project goes
    STALE and drags the rest of the cascade with it (PRD §3.2)."""
    for package in oldest_first(
            [p for p in stem_packages_of(project["id"]) if p["status"] == "CONFORMED"]):
        mark_stem_package_stale(package, stale_reason, affected_project_ids)
