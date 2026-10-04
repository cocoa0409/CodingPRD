"""Shared serializers, audit chain, and lazy system-transition evaluation."""
import hashlib

import db
from util import get_clock_date, now_ts, touch


def strip_internal(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


# ---------- audit chain ----------

def append_audit(contract_id, actor_role, actor_id, action, entity_kind, entity_id, detail):
    entries = [e for e in db.filter_items("audit_log", contract_id=contract_id)]
    prev_hash = entries[-1]["entry_hash"] if entries else ""
    entry_hash = hashlib.sha256((prev_hash + str(detail)).encode("utf-8")).hexdigest()
    entry = {
        "id": __import__("util").new_id(),
        "contract_id": contract_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "entity_kind": entity_kind,
        "entity_id": entity_id,
        "detail": str(detail),
        "entry_hash": entry_hash,
        "created_at": now_ts(),
    }
    db.put("audit_log", entry)
    return entry


# ---------- lazy maintenance lapsing ----------

def maybe_lapse_agreement(agreement):
    if agreement.get("status") == "SUSPENDED":
        from datetime import date as _date, timedelta
        cov = _date.fromisoformat(agreement["coverage_start_on"])
        if get_clock_date() > cov + timedelta(days=365):
            agreement["status"] = "LAPSED"
            touch(agreement)
    return agreement


def lapse_all_agreements():
    for ag in db.all_items("maintenance_agreements"):
        maybe_lapse_agreement(ag)


# ---------- ticket counters ----------

def recompute_transition_counters(transition):
    tickets = db.filter_items("support_tickets", support_transition_id=transition["id"])
    transition["total_tickets"] = len(tickets)
    transition["open_sev1_count"] = sum(
        1 for t in tickets if t["severity"] == "SEV1" and t.get("resolution") is None
    )
    transition["sla_breach_count"] = sum(1 for t in tickets if t.get("breached_sla"))
    transition["updated_at"] = now_ts()


# ---------- readiness score ----------

def compute_readiness_score(contract_id):
    milestones = [m for m in db.filter_items("milestones", contract_id=contract_id)]
    if milestones:
        done = sum(1 for m in milestones if m["status"] in ("ACCEPTED", "INVOICED", "PAID"))
        c_m = 100 * done / len(milestones)
    else:
        c_m = 0
    batches = db.filter_items("migration_batches", contract_id=contract_id)
    c_g = (100 * sum(1 for b in batches if b["status"] == "ACCEPTED") / len(batches)) if batches else 0
    ifaces = db.filter_items("interfaces", contract_id=contract_id)
    c_i = (100 * sum(1 for i in ifaces if i["status"] == "CERTIFIED") / len(ifaces)) if ifaces else 0
    cycles = db.filter_items("uat_cycles", contract_id=contract_id)
    c_u = (100 * sum(1 for c in cycles if c["status"] == "PASSED") / len(cycles)) if cycles else 0
    procs = db.filter_items("workflow_processes", contract_id=contract_id)
    c_p = (100 * sum(1 for p in procs if p["status"] == "APPROVED") / len(procs)) if procs else 0
    # training: enrollments of sessions belonging to this contract
    enrollments = []
    for sess in db.filter_items("training_sessions", contract_id=contract_id):
        enrollments.extend(db.filter_items("training_enrollments", training_session_id=sess["id"]))
    denom = sum(e["seat_weight"] for e in enrollments if e["outcome"] in ("ENROLLED", "COMPLETED"))
    numer = sum(e["seat_weight"] for e in enrollments if e["outcome"] == "COMPLETED")
    if denom:
        c_t = min(100, 100 * numer / denom)
    else:
        c_t = 0
    weighted = 25 * c_m + 25 * c_g + 20 * c_i + 15 * c_u + 10 * c_p + 5 * c_t
    import math
    return int(math.floor(weighted / 100))


def recompute_readiness(contract_id):
    """Recompute and persist readiness_score on the contract's non-terminal GoLiveEvent."""
    for ev in db.filter_items("go_live_events", contract_id=contract_id):
        if ev["status"] not in ("EXECUTED", "CANCELLED"):
            ev["readiness_score"] = compute_readiness_score(contract_id)
            touch(ev)
