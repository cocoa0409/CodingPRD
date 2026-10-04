"""Cascading transitions (PRD sections 3.1, 3.4, 3.8). Every entity a cascade
touches gets its own version increment and updated_at refresh.
"""
import db
import domain
import calculations
import timeutil
from constants import (
    WELLNESS_FATIGUE_THRESHOLD_HOURS, WELLNESS_LONG_DEPLOYMENT_DAYS,
    HAZARD_TO_CAPABILITY,
)


def demobe_deployment(dep):
    """Full demobe bundle (PRD 3.4): stamps demobed_at, returns duty_status to
    RESTING, releases the bunk and finalizes lodging, computes final stipend,
    cancels remaining SCHEDULED shifts, runs the wellness screen, and
    recomputes the operation's counters last."""
    now = db.now()
    dep["status"] = "DEMOBED"
    dep["demobed_at"] = timeutil.fmt(now)
    dep["duty_status"] = "RESTING"
    op = db.get("operations", dep["operation_id"])

    if dep.get("fob_site_id"):
        fob = db.get("fob_sites", dep["fob_site_id"])
        if fob is not None:
            fob["bunks_occupied"] = max(0, fob["bunks_occupied"] - 1)
            fob["lodging_cost_cents"] += calculations.lodging_stay_cost(
                fob["nightly_rate_cents"], dep["checked_in_at"], dep["demobed_at"]
            )
            db.touch(fob)

    days = calculations.final_stipend_days(dep["checked_in_at"], dep["demobed_at"])
    dep["stipend_final_cents"] = calculations.stipend_for_days(days)
    db.touch(dep)

    for shift in domain.shifts_of_deployment(dep["id"]):
        if shift["status"] == "SCHEDULED":
            shift["status"] = "CANCELLED"
            db.touch(shift)

    vol = db.get("volunteers", dep["volunteer_id"])
    if vol is not None:
        reason = None
        if vol["fatigue_hours"] >= WELLNESS_FATIGUE_THRESHOLD_HOURS:
            reason = "FATIGUE_THRESHOLD"
        elif days >= WELLNESS_LONG_DEPLOYMENT_DAYS:
            reason = "LONG_DEPLOYMENT"
        if reason is not None:
            db.mint("wellness_checks", {
                "deployment_id": dep["id"],
                "reason": reason,
                "status": "OPEN",
                "resolved_notes": None,
            })

    if op is not None:
        domain.recompute_operation(op)


def revoke_cascade(cert):
    """Certification VERIFIED -> REVOKED blast radius (PRD 3.1), in hops."""
    owner_id = cert["volunteer_id"]
    kind = cert["kind"]
    other_same_kind = any(
        c["id"] != cert["id"] and c["kind"] == kind and c["status"] == "VERIFIED"
        for c in domain.certs_of(owner_id)
    )
    touched_ops = {}
    if not other_same_kind:
        # Hop 1: ON_SITE deployments of the owner whose operation requires the kind.
        for dep in db.all_of("deployments"):
            if dep["volunteer_id"] != owner_id or dep["status"] != "ON_SITE":
                continue
            op = db.get("operations", dep["operation_id"])
            if op is not None and kind in op["required_capabilities"]:
                dep["status"] = "SAFETY_HOLD"
                db.touch(dep)
                touched_ops[op["id"]] = op
        # Hop 2: gap recompute per touched op; block affected IN_PROGRESS work orders.
        for op in touched_ops.values():
            domain.recompute_operation(op)
            if op["capability_gap"].get(kind, 0) > 0:
                for wo in db.all_of("work_orders"):
                    if (wo["operation_id"] == op["id"] and wo["status"] == "IN_PROGRESS"
                            and HAZARD_TO_CAPABILITY.get(wo["hazard_kind"]) == kind):
                        wo["status"] = "BLOCKED"
                        wo["blocked_reason"] = "CAPABILITY_LOST"
                        db.touch(wo)


def cancel_operation(op):
    """Operation -> CANCELLED: OFFERED/ACCEPTED deployments expire with it."""
    op["status"] = "CANCELLED"
    db.touch(op)
    for dep in domain.deployments_of_operation(op["id"]):
        if dep["status"] in ("OFFERED", "ACCEPTED"):
            dep["status"] = "EXPIRED"
            db.touch(dep)


def stand_down_incident(incident):
    """Incident TYPED -> STANDING_DOWN cascade (PRD 3.8), hop by hop."""
    ops = [o for o in db.all_of("operations") if o["incident_id"] == incident["id"]]
    demobilizing = []
    # Hop 1: MUSTERED/ACTIVE operations -> DEMOBILIZING.
    for op in ops:
        if op["status"] in ("MUSTERED", "ACTIVE"):
            op["status"] = "DEMOBILIZING"
            db.touch(op)
            demobilizing.append(op)
    # Hop 2: from each demobilizing operation, demobe ON_SITE/SAFETY_HOLD
    # deployments with the full bundle; OFFERED/ACCEPTED deployments expire.
    for op in demobilizing:
        for dep in domain.deployments_of_operation(op["id"]):
            if dep["status"] in ("ON_SITE", "SAFETY_HOLD"):
                demobe_deployment(dep)
        for dep in domain.deployments_of_operation(op["id"]):
            if dep["status"] in ("OFFERED", "ACCEPTED"):
                dep["status"] = "EXPIRED"
                db.touch(dep)
    # Separately: DRAFT/OPEN operations are cancelled (their offers expire).
    for op in ops:
        if op["status"] in ("DRAFT", "OPEN"):
            cancel_operation(op)
