"""Cross-cutting domain behaviour: derived counters, integrity re-derivation,
the fraud queue sweeps, downstream fan-out and merge completion.
"""

from datetime import timedelta

from core import (
    PROPAGATION_DEADLINE_HOURS_BATCH, PROPAGATION_DEADLINE_HOURS_SYNCHRONOUS,
    base_entity, iso, now, parse_datetime, store, touch,
)
import scoring

# --------------------------------------------------------------------------
# Derived counters (PRD §2.10) -- computed on demand so they can never drift.
# --------------------------------------------------------------------------
def active_record_count(site_id):
    return sum(
        1 for r in store.records.values()
        if r["site_id"] == site_id and r["identity_state"] == "ACTIVE"
    )


def flagged_record_count(site_id):
    return scoring.flagged_record_count(site_id)


def subsumed_member_count(record_id):
    return sum(
        1 for r in store.records.values()
        if r.get("survivor_record_id") == record_id
        and r["identity_state"] == "MERGED_SUBSUMED"
    )


def unacked_task_count(system_id):
    return sum(
        1 for t in store.tasks.values()
        if t["downstream_system_id"] == system_id and t["state"] in ("QUEUED", "SENT")
    )


# --------------------------------------------------------------------------
# integrity_state derivation (PRD §2.9)
# --------------------------------------------------------------------------
def derive_integrity(record_id):
    investigations = [i for i in store.investigations.values() if i["record_id"] == record_id]
    if any(i["state"] in ("SUBSTANTIATED", "REFERRED_LAW_ENFORCEMENT") for i in investigations):
        return "FRAUD_CONFIRMED"
    if any(i["state"] == "OPEN" for i in investigations):
        return "FRAUD_SUSPECTED"
    remediations = [r for r in store.remediations.values() if r["record_id"] == record_id]
    if any(r["state"] in ("OPEN", "QUARANTINED", "REASSIGNED") for r in remediations):
        return "REMEDIATION_PENDING"
    overlays = [o for o in store.overlays.values() if o["record_id"] == record_id]
    if any(o["state"] in ("DETECTED", "UNDER_CORRECTION") for o in overlays):
        return "REMEDIATION_PENDING"
    return "CLEAR"


def reconcile_integrity(record):
    """Re-derive; every re-derivation that CHANGES the value bumps version by 1."""
    value = derive_integrity(record["id"])
    if record.get("integrity_state") != value:
        record["integrity_state"] = value
        touch(record)
        return True
    return False


def under_fraud_hold(record):
    return record["integrity_state"] in ("FRAUD_SUSPECTED", "FRAUD_CONFIRMED")


# --------------------------------------------------------------------------
# Fraud queue sweeps (PRD §3.9)
# --------------------------------------------------------------------------
ESCALATABLE_QUEUE_STATES = (
    "NEW", "TRIAGED", "UNDER_REVIEW", "RECOMMENDED_MERGE", "RECOMMENDED_DISTINCT",
)


def _pairs_of_record(record_id):
    rows = [
        p for p in store.pairs.values()
        if p["record_a_id"] == record_id or p["record_b_id"] == record_id
    ]
    rows.sort(key=lambda p: p["_seq"])
    return rows


def escalate_pairs_for_record(record_id):
    for pair in _pairs_of_record(record_id):
        if pair["queue_state"] in ESCALATABLE_QUEUE_STATES:
            if pair["queue_state"] in ("RECOMMENDED_MERGE", "RECOMMENDED_DISTINCT"):
                pair["recommended_by_user_id"] = None
                pair["recommendation"] = None
            pair["queue_state"] = "ESCALATED_FRAUD"
            touch(pair)


def deescalate_pairs_for_record(record_id):
    for pair in _pairs_of_record(record_id):
        if pair["queue_state"] == "ESCALATED_FRAUD":
            pair["queue_state"] = "UNDER_REVIEW"
            touch(pair)


# --------------------------------------------------------------------------
# Downstream fan-out (PRD §3.5 / §3.6 / §3.8)
# --------------------------------------------------------------------------
def active_systems_in_code_order():
    rows = [s for s in store.systems.values() if s["status"] == "ACTIVE"]
    rows.sort(key=lambda s: (s["system_code"], s["_seq"]))
    return rows


def fan_out(operation_kind, merge_operation_id=None, overlay_correction_id=None):
    created = []
    for system in active_systems_in_code_order():
        task = base_entity()
        hours = (
            PROPAGATION_DEADLINE_HOURS_SYNCHRONOUS
            if system["propagation_mode"] == "SYNCHRONOUS"
            else PROPAGATION_DEADLINE_HOURS_BATCH
        )
        task.update({
            "merge_operation_id": merge_operation_id,
            "overlay_correction_id": overlay_correction_id,
            "downstream_system_id": system["id"],
            "operation_kind": operation_kind,
            "state": "QUEUED" if system["ack_required"] else "ACKED",
            "attempt_count": 0,
            "dispatch_window_start_at": None,
            "dispatch_window_end_at": None,
            "propagation_deadline_at": iso(parse_datetime(task["created_at"]) + timedelta(hours=hours)),
            "last_error_code": None,
        })
        store.tasks[task["id"]] = task
        created.append(task)
    return created


# --------------------------------------------------------------------------
# Merge completion (PRD §3.5 / §3.6)
# --------------------------------------------------------------------------
def complete_merge(merge):
    merge["state"] = "COMPLETED"
    merge["completed_at"] = iso(now())
    merge["reversal_deadline_at"] = iso(now() + timedelta(days=90))
    touch(merge)


def merge_tasks(merge_id):
    rows = [t for t in store.tasks.values() if t.get("merge_operation_id") == merge_id]
    rows.sort(key=lambda t: (t["created_at"], t["id"]))
    return rows


def merge_is_complete(merge_id):
    """No task belonging to the merge remains QUEUED, SENT or FAILED."""
    return not any(
        t["state"] in ("QUEUED", "SENT", "FAILED") for t in merge_tasks(merge_id)
    )


# --------------------------------------------------------------------------
# Opening a fraud investigation (PRD §3.9) -- shared by the manual endpoint and
# the automatic create-time branch of pair scoring.
# --------------------------------------------------------------------------
def open_investigation(record, pair_id, trigger_kind, opened_by, opened_by_user_id, note):
    row = base_entity()
    row.update({
        "record_id": record["id"],
        "pair_id": pair_id,
        "trigger_kind": trigger_kind,
        "opened_by": opened_by,
        "opened_by_user_id": opened_by_user_id,
        "risk_score": None,
        "state": "OPEN",
        "note": note,
        "finding_note": None,
        "referral_reference": None,
    })
    store.investigations[row["id"]] = row
    # The subject record is flagged BEFORE risk_score is evaluated, so its own
    # flag is counted in its site's flagged_record_count.
    reconcile_integrity(record)
    row["risk_score"] = scoring.compute_risk_score(row)
    escalate_pairs_for_record(record["id"])
    return row
