"""Merge approval, reversal, and downstream propagation tasks."""

from flask import Blueprint, g

from core import (
    ALL_ROLES, CONTAMINATION_REVIEW_ELEMENT_THRESHOLD, authenticate, bad_request,
    base_entity, created, err, field_datetime, field_id, field_string, get_body,
    iso, now, ok, ok_list, paginate, pagination, parse_datetime, query_filter,
    store, touch,
)
import domain
import serializers

bp = Blueprint("merge", __name__)


def _record_or_404(record_id):
    row = store.records.get(record_id)
    if row is None:
        raise err("ERR_RECORD_NOT_FOUND", "No patient record with id %s" % record_id)
    return row


# --------------------------------------------------------------------------
# Merge approval
# --------------------------------------------------------------------------
@bp.post("/mpi/merge-operations")
def create_merge():
    authenticate(["IdentityStewardApprover"])
    body = get_body()
    pair_id = field_id(body, "pair_id", required=True)
    survivor_id = field_id(body, "survivor_record_id", required=True)
    subsumed_id = field_id(body, "subsumed_record_id", required=True)
    rationale = field_string(body, "rationale", required=True)

    survivor = _record_or_404(survivor_id)                               # rank 8
    subsumed = _record_or_404(subsumed_id)
    pair = store.pairs.get(pair_id)                                      # rank 9
    if pair is None:
        raise err("ERR_PAIR_NOT_FOUND", "No candidate pair with id %s" % pair_id)

    for record in (survivor, subsumed):                                  # rank 21
        if domain.under_fraud_hold(record):
            raise err("ERR_RECORD_UNDER_FRAUD_HOLD",
                      "Patient record %s is under a fraud hold" % record["id"])
    for record in (survivor, subsumed):                                  # rank 22
        if record["integrity_state"] == "REMEDIATION_PENDING":
            raise err("ERR_RECORD_REMEDIATION_PENDING",
                      "Patient record %s has a remediation pending" % record["id"])
    for record in (survivor, subsumed):                                  # rank 25
        if record["identity_state"] != "ACTIVE":
            raise err("ERR_RECORD_NOT_ACTIVE",
                      "Patient record %s is not ACTIVE" % record["id"])
    if pair["queue_state"] != "RECOMMENDED_MERGE":                       # rank 26
        raise err("ERR_PAIR_INVALID_STATE",
                  "Candidate pair %s is in queue_state %s" % (pair_id, pair["queue_state"]))
    if pair["recommended_by_user_id"] is not None \
            and g.user_id == pair["recommended_by_user_id"]:             # rank 34
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "The operator who recommended a pair may not approve its merge")
    if survivor_id == subsumed_id:                                       # rank 36
        raise err("ERR_MERGE_SELF_REFERENCE",
                  "survivor_record_id must differ from subsumed_record_id")
    if {survivor_id, subsumed_id} != {pair["record_a_id"], pair["record_b_id"]}:  # rank 37
        raise err("ERR_PAIR_RECORD_MISMATCH",
                  "The named records are not the members of candidate pair %s" % pair_id)

    merge = base_entity()
    merge.update({
        "pair_id": pair_id,
        "survivor_record_id": survivor_id,
        "subsumed_record_id": subsumed_id,
        "rationale": rationale,
        "state": "PENDING_PROPAGATION",
        "approved_by_user_id": g.user_id,
        "moved_clinical_element_count": subsumed["clinical_element_count"],
        "subsumed_prior_enterprise_id": subsumed["enterprise_id"],
        "recompressed_record_mrns": [],
        "propagation_task_count": 0,
        "completed_at": None,
        "reversal_deadline_at": None,
        "unmerge_reason": None,
        "unmerged_at": None,
    })
    moved = merge["moved_clinical_element_count"]

    # Path compression set, captured before the subsumed record is re-pointed.
    compressed = [
        r for r in store.records.values()
        if r.get("survivor_record_id") == subsumed_id
        and r["identity_state"] == "MERGED_SUBSUMED"
    ]
    compressed.sort(key=lambda r: (r["created_at"], r["mrn"], r["_seq"]))

    subsumed["identity_state"] = "MERGED_SUBSUMED"
    subsumed["survivor_record_id"] = survivor_id
    subsumed["clinical_element_count"] = 0
    subsumed["enterprise_id"] = survivor["enterprise_id"]
    touch(subsumed)

    survivor["clinical_element_count"] = survivor["clinical_element_count"] + moved
    touch(survivor)

    for record in compressed:
        record["survivor_record_id"] = survivor_id
        record["enterprise_id"] = survivor["enterprise_id"]
        touch(record)
    merge["recompressed_record_mrns"] = [r["mrn"] for r in compressed]

    pair["queue_state"] = "RESOLVED_MERGED"
    pair["approved_by_user_id"] = g.user_id
    touch(pair)

    store.merges[merge["id"]] = merge
    tasks = domain.fan_out("MERGE", merge_operation_id=merge["id"])
    merge["propagation_task_count"] = len(tasks)

    if moved > CONTAMINATION_REVIEW_ELEMENT_THRESHOLD:
        remediation = base_entity()
        remediation.update({
            "source_type": "MERGE",
            "merge_operation_id": merge["id"],
            "overlay_correction_id": None,
            "record_id": survivor_id,
            "element_count_subject": moved,
            "element_count_quarantined": 0,
            "element_count_reassigned": 0,
            "reassigned_to_record_mrn": None,
            "state": "OPEN",
            "closure_note": None,
        })
        store.remediations[remediation["id"]] = remediation
        domain.reconcile_integrity(survivor)

    ack_pending = any(
        store.systems[t["downstream_system_id"]]["ack_required"] for t in tasks
    )
    if merge["propagation_task_count"] == 0 or not ack_pending:
        domain.complete_merge(merge)

    return created(serializers.merge(merge))


@bp.get("/mpi/merge-operations/<merge_id>")
def get_merge(merge_id):
    authenticate(ALL_ROLES)
    row = store.merges.get(merge_id)
    if row is None:
        raise err("ERR_MERGE_NOT_FOUND", "No merge operation with id %s" % merge_id)
    return ok(serializers.merge(row))


@bp.get("/mpi/merge-operations")
def list_merges():
    authenticate(ALL_ROLES)
    rows = sorted(store.merges.values(), key=lambda m: (m["created_at"], m["_seq"]))
    for key in ("pair_id", "survivor_record_id", "subsumed_record_id", "state"):
        rows = query_filter(rows, key)
    window, page = paginate(rows)
    return ok_list([serializers.merge(m) for m in window], page)


# --------------------------------------------------------------------------
# Reversal
# --------------------------------------------------------------------------
@bp.post("/mpi/merge-operations/<merge_id>/unmerge")
def unmerge(merge_id):
    authenticate(["IdentityStewardApprover", "MpiAdmin"])
    body = get_body()
    reason = field_string(body, "unmerge_reason", required=True)

    merge = store.merges.get(merge_id)                                   # rank 10
    if merge is None:
        raise err("ERR_MERGE_NOT_FOUND", "No merge operation with id %s" % merge_id)
    if merge["state"] not in ("PENDING_PROPAGATION", "COMPLETED"):       # rank 27
        raise err("ERR_MERGE_INVALID_STATE",
                  "Merge operation %s is in state %s" % (merge_id, merge["state"]))
    tasks = domain.merge_tasks(merge_id)
    if any(t["state"] == "SENT" for t in tasks):                         # rank 33
        raise err("ERR_PROPAGATION_IN_FLIGHT",
                  "A propagation task for this merge has already been dispatched")
    if merge["state"] == "COMPLETED":                                    # rank 42
        deadline = parse_datetime(merge["reversal_deadline_at"])
        if deadline is not None and now() > deadline:
            raise err("ERR_REVERSAL_WINDOW_EXPIRED",
                      "The 90-day reversal window for this merge has expired")

    survivor = store.records.get(merge["survivor_record_id"])
    subsumed = store.records.get(merge["subsumed_record_id"])
    moved = merge["moved_clinical_element_count"]

    merge["state"] = "UNMERGED"
    merge["unmerged_at"] = iso(now())
    merge["unmerge_reason"] = reason
    touch(merge)

    restored_key = merge["subsumed_prior_enterprise_id"]
    if subsumed is not None:
        subsumed["identity_state"] = "ACTIVE"
        subsumed["survivor_record_id"] = None
        subsumed["enterprise_id"] = restored_key
        subsumed["clinical_element_count"] = subsumed["clinical_element_count"] + moved
        touch(subsumed)
    if survivor is not None:
        survivor["clinical_element_count"] = survivor["clinical_element_count"] - moved
        touch(survivor)

    for mrn in merge["recompressed_record_mrns"]:
        for record in sorted(store.records.values(), key=lambda r: r["_seq"]):
            if record["mrn"] != mrn:
                continue
            if record.get("survivor_record_id") != merge["survivor_record_id"]:
                continue
            if record["identity_state"] != "MERGED_SUBSUMED":
                continue
            record["survivor_record_id"] = merge["subsumed_record_id"]
            record["enterprise_id"] = restored_key
            touch(record)
            break

    pair = store.pairs.get(merge["pair_id"])
    if pair is not None and pair["queue_state"] == "RESOLVED_MERGED":
        pair["queue_state"] = "UNDER_REVIEW"
        pair["recommended_by_user_id"] = None
        pair["recommendation"] = None
        pair["approved_by_user_id"] = None
        touch(pair)

    closed_any = False
    for remediation in sorted(store.remediations.values(), key=lambda r: r["_seq"]):
        if remediation.get("merge_operation_id") != merge_id:
            continue
        if remediation["state"] not in ("OPEN", "QUARANTINED", "REASSIGNED"):
            continue
        remediation["state"] = "CLOSED"
        remediation["closure_note"] = "CLOSED_BY_UNMERGE"
        touch(remediation)
        closed_any = True
    if closed_any and survivor is not None:
        domain.reconcile_integrity(survivor)

    for task in tasks:
        if task["state"] in ("QUEUED", "FAILED"):
            task["state"] = "CANCELLED"
            touch(task)

    domain.fan_out("UNMERGE", merge_operation_id=merge_id)

    return ok(serializers.merge(merge))


# --------------------------------------------------------------------------
# Propagation tasks
# --------------------------------------------------------------------------
def _task_or_404(task_id):
    row = store.tasks.get(task_id)
    if row is None:
        raise err("ERR_TASK_NOT_FOUND", "No propagation task with id %s" % task_id)
    return row


@bp.get("/mpi/propagation-tasks/<task_id>")
def get_task(task_id):
    authenticate(ALL_ROLES)
    return ok(serializers.task(_task_or_404(task_id)))


@bp.get("/mpi/propagation-tasks")
def list_tasks():
    authenticate(ALL_ROLES)
    rows = sorted(store.tasks.values(), key=lambda t: (t["created_at"], t["id"]))
    for key in ("merge_operation_id", "overlay_correction_id", "downstream_system_id",
                "state", "operation_kind"):
        rows = query_filter(rows, key)
    window, page = paginate(rows)
    return ok_list([serializers.task(t) for t in window], page)


@bp.post("/mpi/propagation-tasks/<task_id>/send")
def send_task(task_id):
    authenticate(["MpiAdmin", "IdentityAnalyst"])
    body = get_body()
    start = field_datetime(body, "dispatch_window_start_at", required=True)
    end = field_datetime(body, "dispatch_window_end_at", required=True)
    if not end > start:
        raise bad_request("dispatch_window_end_at must be strictly later than dispatch_window_start_at")

    task = _task_or_404(task_id)                                         # rank 13
    if task["state"] not in ("QUEUED", "FAILED"):                        # rank 30
        raise err("ERR_TASK_INVALID_STATE",
                  "Propagation task %s is in state %s" % (task_id, task["state"]))
    system = store.systems.get(task["downstream_system_id"])
    if system is None or system["status"] != "ACTIVE":                    # rank 32
        raise err("ERR_DOWNSTREAM_SYSTEM_PAUSED",
                  "The downstream system for this task is not ACTIVE")
    deadline = parse_datetime(task["propagation_deadline_at"])
    if deadline is not None and now() > deadline:                        # rank 43
        raise err("ERR_PROPAGATION_WINDOW_EXPIRED",
                  "The propagation deadline for this task has passed")

    occupancy = 0                                                        # rank 45
    for other in store.tasks.values():
        if other["id"] == task_id:
            continue
        if other["downstream_system_id"] != task["downstream_system_id"]:
            continue
        if other["state"] != "SENT":
            continue
        other_start = parse_datetime(other["dispatch_window_start_at"])
        other_end = parse_datetime(other["dispatch_window_end_at"])
        if other_start is None or other_end is None:
            continue
        # HALF-OPEN [start, end): touching endpoints do not overlap.
        if other_start < end and start < other_end:
            occupancy += 1
    if occupancy >= system["max_concurrent_dispatch"]:
        raise err("ERR_DISPATCH_CAPACITY_EXCEEDED",
                  "Dispatch capacity for this downstream system is exhausted")

    task["dispatch_window_start_at"] = iso(start)
    task["dispatch_window_end_at"] = iso(end)
    task["state"] = "SENT"
    task["attempt_count"] = task["attempt_count"] + 1
    touch(task)
    return ok(serializers.task(task))


@bp.post("/mpi/propagation-tasks/<task_id>/ack")
def ack_task(task_id):
    authenticate(["MpiAdmin"])
    get_body()
    task = _task_or_404(task_id)
    if task["state"] != "SENT":
        raise err("ERR_TASK_INVALID_STATE",
                  "Propagation task %s is in state %s" % (task_id, task["state"]))
    task["state"] = "ACKED"
    touch(task)
    merge_id = task.get("merge_operation_id")
    if merge_id:
        merge = store.merges.get(merge_id)
        if merge is not None and merge["state"] == "PENDING_PROPAGATION" \
                and domain.merge_is_complete(merge_id):
            domain.complete_merge(merge)
    return ok(serializers.task(task))


@bp.post("/mpi/propagation-tasks/<task_id>/fail")
def fail_task(task_id):
    authenticate(["MpiAdmin"])
    body = get_body()
    error_code = field_string(body, "last_error_code", required=True)
    task = _task_or_404(task_id)
    if task["state"] != "SENT":
        raise err("ERR_TASK_INVALID_STATE",
                  "Propagation task %s is in state %s" % (task_id, task["state"]))
    task["state"] = "FAILED"
    task["last_error_code"] = error_code
    task["dispatch_window_start_at"] = None
    task["dispatch_window_end_at"] = None
    touch(task)
    return ok(serializers.task(task))
