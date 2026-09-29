"""Propagation fork/join, completion ratio bookkeeping and recipient posture
(PRD 3.5, 3.6)."""
import audit
import scoring
import standing
from core import D, add_days, db, make, now, ordered, touch

OPEN_TASK_STATES = ("PENDING", "DISPATCHED", "DEFERRED", "FAILED")
OPEN_REQUEST_STATES = ("RECEIVED", "VERIFICATION_PENDING", "VERIFIED",
                       "VERIFICATION_FAILED", "EXECUTING")
SUPERSEDABLE_REQUEST_STATES = ("RECEIVED", "VERIFICATION_PENDING",
                               "VERIFICATION_FAILED")

# target_kind -> (weight, sla_days); minting order is pinned by this list.
INTERNAL_TARGETS = [
    ("ACTIVE_DATABASE", 40, 5),
    ("BACKUP_ARCHIVE", 20, 45),
    ("DERIVED_DATASET", 20, 15),
]
DOWNSTREAM_WEIGHT = 20
SUPPRESSION_WINDOW_DAYS = 730


def tasks_of(request_rec):
    return ordered([t for t in db.tasks.values()
                    if t["deletion_request_id"] == request_rec["id"]])


def eligible_recipients(broker_id):
    """Recipients ranked by reliability_score descending, created_at ascending
    on ties -- never by id (PRD 3.5)."""
    pool = [r for r in db.recipients.values()
            if r["broker_id"] == broker_id
            and r["status"] == "ACTIVE"
            and r["contract_propagation_required"]]
    return sorted(pool, key=lambda r: (-D(r["reliability_score"]),
                                       r["created_at"], r["_seq"]))


def _new_task(request_rec, target_kind, recipient_id, weight, sla_days):
    task = make(
        "PropagationTask",
        deletion_request_id=request_rec["id"],
        recipient_id=recipient_id,
        target_kind=target_kind,
        status="PENDING",
        weight=weight,
        sla_days=sla_days,
        due_at=add_days(now(), sla_days),
        dispatched_at=None,
        acknowledged_at=None,
        ack_was_late=False,
        dispatch_count=0,
        failure_code=None,
        deferral_reason=None,
        waiver_justification=None,
    )
    db.tasks[task["id"]] = task
    return task


def fork(request_rec, consumer):
    """Mint the propagation plan in the pinned order: ACTIVE_DATABASE,
    BACKUP_ARCHIVE, DERIVED_DATASET, then the ranked recipients."""
    minted = []
    for target_kind, weight, sla_days in INTERNAL_TARGETS:
        if target_kind == "BACKUP_ARCHIVE" and request_rec["requested_scope"] != "DELETE_ALL":
            continue
        if target_kind == "DERIVED_DATASET" and int(consumer["derived_profile_count"]) <= 0:
            continue
        minted.append(_new_task(request_rec, target_kind, None, weight,
                                sla_days))
    downstream = eligible_recipients(request_rec["broker_id"])
    for rec in downstream:
        minted.append(_new_task(request_rec, "DOWNSTREAM_RECIPIENT",
                                rec["id"], DOWNSTREAM_WEIGHT,
                                int(rec["ack_sla_days"])))
    request_rec["propagation_required_count"] = len(minted)
    request_rec["downstream_task_count"] = len(downstream)
    request_rec["acked_task_count"] = 0
    request_rec["waived_task_count"] = 0
    request_rec["abandoned_task_count"] = 0
    request_rec["outstanding_task_count"] = len(minted)
    request_rec["completion_ratio"] = scoring.completion_ratio(minted)
    return minted


def recompute_ratio(request_rec):
    request_rec["completion_ratio"] = scoring.completion_ratio(
        tasks_of(request_rec))
    return request_rec["completion_ratio"]


def rescore_recipient(recipient, broker, actor):
    """Re-score reliability and auto-suspend strictly below 70.00 while ACTIVE."""
    recipient["reliability_score"] = scoring.reliability_score(
        recipient["on_time_ack_count"], recipient["late_ack_count"],
        recipient["fail_count"], recipient["waive_count"])
    touch(recipient)
    if (recipient["status"] == "ACTIVE"
            and recipient["reliability_score"] < scoring.RELIABILITY_SUSPEND_THRESHOLD):
        suspend_recipient(recipient, broker, actor,
                          "recipient suspended automatically after its "
                          "reliability score fell below the threshold")


def suspend_recipient(recipient, broker, actor, summary):
    recipient["status"] = "SUSPENDED"
    touch(recipient)
    audit.append(broker, "RECIPIENT_STATUS_CHANGED", "RECIPIENT",
                 recipient["id"], actor, summary)
    for task in ordered([t for t in db.tasks.values()
                         if t["recipient_id"] == recipient["id"]]):
        if task["status"] in ("PENDING", "DISPATCHED"):
            task["status"] = "DEFERRED"
            task["deferral_reason"] = "RECIPIENT_SUSPENDED"
            touch(task)
            audit.append(broker, "PROPAGATION_DEFERRED", "PROPAGATION_TASK",
                         task["id"], actor,
                         "propagation deferred because the recipient is "
                         "suspended")


def abandon_task(task, actor, summary):
    """Move an open task to ABANDONED and settle the owning request."""
    task["status"] = "ABANDONED"
    touch(task)
    request_rec = db.requests[task["deletion_request_id"]]
    broker = db.brokers[request_rec["broker_id"]]
    request_rec["abandoned_task_count"] += 1
    request_rec["outstanding_task_count"] -= 1
    recompute_ratio(request_rec)
    touch(request_rec)
    audit.append(broker, "PROPAGATION_ABANDONED", "PROPAGATION_TASK",
                 task["id"], actor, summary)
    return evaluate_join(request_rec, actor)


def evaluate_join(request_rec, actor):
    """The join fires only when no task remains PENDING, DISPATCHED, DEFERRED
    or FAILED (PRD 3.6)."""
    if request_rec["status"] != "EXECUTING":
        return False
    tasks = tasks_of(request_rec)
    for task in tasks:
        if task["status"] in OPEN_TASK_STATES:
            return False

    broker = db.brokers[request_rec["broker_id"]]
    ratio = recompute_ratio(request_rec)
    breach = False
    if ratio >= scoring.COMPLETION_FULL:
        request_rec["status"] = "COMPLETED"
    else:
        request_rec["status"] = "PARTIALLY_COMPLETED"
        if ratio < scoring.BREACH_RATIO_THRESHOLD:
            request_rec["compliance_breach"] = True
            breach = True
    touch(request_rec)
    broker["request_completed_count"] += 1
    broker["request_open_count"] -= 1
    touch(broker)
    audit.append(broker, "DELETION_COMPLETED", "DELETION_REQUEST",
                 request_rec["id"], actor,
                 "deletion request joined as %s with completion ratio %s"
                 % (request_rec["status"], request_rec["completion_ratio"]))
    if breach:
        broker["open_breach_count"] += 1
        touch(broker)
        standing.derive_standing(broker, actor)

    consumer = db.consumers[request_rec["consumer_id"]]
    if consumer["collection_status"] == "PURGE_PENDING":
        consumer["collection_status"] = "PURGED"
        consumer["last_purged_at"] = now()
        touch(consumer)

    entry = make(
        "SuppressionEntry",
        broker_id=broker["id"],
        consumer_id=consumer["id"],
        originating_request_id=request_rec["id"],
        window_start=now(),
        window_end=add_days(now(), SUPPRESSION_WINDOW_DAYS),
        source_scope="ALL_SOURCES",
        status="ACTIVE",
        lift_justification=None,
        blocked_recollection_count=0,
    )
    db.suppressions[entry["id"]] = entry
    audit.append(broker, "SUPPRESSION_CREATED", "SUPPRESSION_ENTRY",
                 entry["id"], actor,
                 "suppression entry opened by the completed deletion request")

    for other in ordered([r for r in db.requests.values()
                          if r["consumer_id"] == consumer["id"]
                          and r["id"] != request_rec["id"]]):
        if other["status"] in SUPERSEDABLE_REQUEST_STATES:
            other_broker = db.brokers[other["broker_id"]]
            other["status"] = "SUPERSEDED"
            touch(other)
            other_broker["request_open_count"] -= 1
            other_broker["request_terminated_count"] += 1
            touch(other_broker)
            audit.append(other_broker, "DELETION_REQUEST_SUPERSEDED",
                         "DELETION_REQUEST", other["id"], actor,
                         "deletion request superseded by the suppression entry "
                         "of a completed request")
    return True
