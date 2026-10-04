"""Domain recomputation helpers (PRD sections 2.9, 2.10, 3.3).
Recomputations do NOT touch() by themselves: the caller folds the recompute
into the single logical mutation it is part of and touches exactly once.
"""
import db
from constants import CERT_WEIGHT, READINESS_BASE, FATIGUE_PENALTY_PER_HOUR, READINESS_FLOOR


def public(entity):
    """Strip internal bookkeeping keys from a stored entity for serialization."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def public_list(entities):
    return [public(e) for e in entities]


def certs_of(volunteer_id):
    return [c for c in db.store["certifications"].values() if c["volunteer_id"] == volunteer_id]


def verified_kinds(volunteer_id):
    return {c["kind"] for c in certs_of(volunteer_id) if c["status"] == "VERIFIED"}


def has_verified(volunteer_id, kind):
    return kind in verified_kinds(volunteer_id)


def recompute_readiness(vol):
    """Dual-variant readiness (calc volunteer_readiness_score).
    Variant A: 0 with zero VERIFIED certs, else 10 + distinct-kind weights.
    Variant B: max(0, A - fatigue_hours * 2)."""
    kinds = verified_kinds(vol["id"])
    if not kinds:
        operational = 0
    else:
        operational = READINESS_BASE + sum(CERT_WEIGHT[k] for k in kinds)
    vol["operational_readiness_score"] = operational
    vol["readiness_score"] = max(
        READINESS_FLOOR, operational - vol["fatigue_hours"] * FATIGUE_PENALTY_PER_HOUR
    )


def deployments_of_operation(operation_id):
    return [d for d in db.store["deployments"].values() if d["operation_id"] == operation_id]


def recompute_operation(op):
    """rostered_count + capability_gap (calc operation_capability_gap).
    Rostered set is deployments in {ACCEPTED, ON_SITE}; SAFETY_HOLD excluded."""
    rostered = [d for d in deployments_of_operation(op["id"]) if d["status"] in ("ACCEPTED", "ON_SITE")]
    op["rostered_count"] = len(rostered)
    gap = {}
    for cap in op["required_capabilities"]:
        covered = sum(1 for d in rostered if has_verified(d["volunteer_id"], cap))
        shortfall = max(0, 1 - covered)
        if shortfall > 0:
            gap[cap] = shortfall
    op["capability_gap"] = gap
    db.touch(op)


def shifts_of_deployment(deployment_id):
    return [s for s in db.store["duty_shifts"].values() if s["deployment_id"] == deployment_id]


def open_wellness_checks_for_volunteer(volunteer_id):
    out = []
    for w in db.store["wellness_checks"].values():
        if w["status"] != "OPEN":
            continue
        dep = db.get("deployments", w["deployment_id"])
        if dep is not None and dep["volunteer_id"] == volunteer_id:
            out.append(w)
    return out
