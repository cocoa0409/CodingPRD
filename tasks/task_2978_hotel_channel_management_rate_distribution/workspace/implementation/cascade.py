"""Eager cascades: pool recomputation, guards, batches, dispatch, health."""

from datetime import timedelta

import calc
import refs
import store
from refs import get, put, rows, where

DAY_DERIVED = (
    "physical_capacity_units",
    "overbooking_ceiling_units",
    "allocated_units",
    "committed_units",
    "shared_pool_units",
    "pooled_state",
)


# --- batches and jobs ----------------------------------------------------

def new_batch(property_id, payload_kind, source_ref_kind, source_ref_id, mappings):
    batch = store.base_record()
    batch.update({
        "property_id": property_id,
        "payload_kind": payload_kind,
        "source_ref_kind": source_ref_kind,
        "source_ref_id": source_ref_id,
        "batch_state": "QUEUED",
        "total_jobs": 0,
        "applied_jobs": 0,
        "rejected_jobs": 0,
        "abandoned_jobs": 0,
        "dispatched_at": None,
    })
    put("batches", batch)
    ordered = sorted(mappings, key=lambda m: (m["created_at"], m["_seq"]))
    for index, mapping in enumerate(ordered, start=1):
        job = store.base_record()
        payload_rate = None
        if payload_kind in ("RATE", "PROMOTION"):
            plan = get("rate_plans", mapping["rate_plan_id"])
            channel = get("channels", mapping["channel_id"])
            payload_rate = calc.distributed_rate(plan, channel)
        job.update({
            "batch_id": batch["id"],
            "channel_mapping_id": mapping["id"],
            "sequence_index": index,
            "payload_kind": payload_kind,
            "payload_rate_cents": payload_rate,
            "job_state": "QUEUED",
            "attempt_count": 0,
            "failure_reason": None,
            "applied_at": None,
        })
        put("jobs", job)
    batch["total_jobs"] = len(ordered)
    return batch


def restriction_batch(restriction):
    room_type = get("room_types", restriction["room_type_id"])
    prop = refs.prop_of_room_type(room_type)
    mappings = refs.verified_mappings_of_room_type(room_type["id"])
    return new_batch(prop["id"], "RESTRICTION", "RESTRICTION", restriction["id"], mappings)


def rate_batch(plan):
    prop = refs.prop_of_plan(plan)
    family_ids = [member["id"] for member in refs.plan_family(plan)]
    mappings = [m for m in rows("mappings")
                if m["rate_plan_id"] in family_ids and m["mapping_state"] == "VERIFIED"]
    return new_batch(prop["id"], "RATE", "RATE_PLAN", plan["id"], mappings)


def promotion_batch(promotion):
    plan = get("rate_plans", promotion["rate_plan_id"])
    prop = refs.prop_of_plan(plan)
    mappings = refs.verified_mappings_of_plan(plan["id"])
    return new_batch(prop["id"], "PROMOTION", "PROMOTION", promotion["id"], mappings)


def rollup(batch, dispatching=False):
    """Recompute counters and re-derive batch_state (PRD 3.10)."""
    children = refs.jobs_of_batch(batch["id"])
    open_jobs = len([j for j in children if j["job_state"] in ("QUEUED", "DISPATCHED")])
    batch["applied_jobs"] = len([j for j in children if j["job_state"] == "APPLIED"])
    batch["rejected_jobs"] = len([j for j in children if j["job_state"] == "REJECTED"])
    batch["abandoned_jobs"] = len([j for j in children if j["job_state"] == "ABANDONED"])
    previous = batch["batch_state"]
    total = batch["total_jobs"]
    if batch["dispatched_at"] is None:
        state = "QUEUED"
    elif open_jobs >= 1 and dispatching:
        state = "DISPATCHING"
    elif open_jobs == 0 and batch["applied_jobs"] == total:
        state = "APPLIED"
    elif open_jobs == 0 and batch["applied_jobs"] == 0:
        state = "FAILED"
    elif open_jobs == 0 and 0 < batch["applied_jobs"] < total:
        state = "PARTIALLY_APPLIED"
    else:
        state = previous
    batch["batch_state"] = state
    return state != previous


# --- inventory pool ------------------------------------------------------

def refresh_allocations(room_type_id):
    for alloc in where("allocations", room_type_id=room_type_id):
        if alloc["allocation_state"] not in ("OPEN", "EXHAUSTED"):
            continue
        consumed = calc.consumed_units_for(alloc)
        state = alloc["allocation_state"]
        if consumed >= alloc["allocated_units"]:
            state = "EXHAUSTED"
        else:
            state = "OPEN"
        if consumed != alloc["consumed_units"] or state != alloc["allocation_state"]:
            alloc["consumed_units"] = consumed
            alloc["allocation_state"] = state
            store.bump(alloc)


def refresh_days(room_type_id):
    """Recompute every inventory day of a room type, with guard side effects."""
    for day in refs.days_of_room_type(room_type_id):
        numbers = calc.day_numbers(day)
        was_oversold = day["pooled_state"] == "OVERSOLD"
        changed = any(day.get(field) != numbers[field] for field in DAY_DERIVED)
        if changed:
            day.update(numbers)
            store.bump(day)
        now_oversold = day["pooled_state"] == "OVERSOLD"
        if now_oversold and not was_oversold:
            place_guards(day)
        elif was_oversold and not now_oversold:
            lift_guards(day)


def refresh_room_type(room_type_id):
    refresh_allocations(room_type_id)
    refresh_days(room_type_id)


def place_guards(day):
    """One AUTO_OVERBOOK_GUARD STOP_SELL per ACTIVE plan of the property."""
    room_type = refs.room_type_of_day(day)
    prop = refs.prop_of_room_type(room_type)
    plans = [p for p in where("rate_plans", property_id=prop["id"])
             if p["plan_state"] == "ACTIVE"]
    for plan in plans:
        restriction = store.base_record()
        restriction.update({
            "room_type_id": room_type["id"],
            "rate_plan_id": plan["id"],
            "restriction_type": "STOP_SELL",
            "start_date": day["stay_date"],
            "end_date": day["stay_date"],
            "value_nights": None,
            "origin": "AUTO_OVERBOOK_GUARD",
            "restriction_state": "ACTIVE",
            "lifted_at": None,
            "lift_reason": None,
        })
        put("restrictions", restriction)
        restriction_batch(restriction)


def lift_guards(day):
    for restriction in where("restrictions", room_type_id=day["room_type_id"]):
        if restriction["origin"] != "AUTO_OVERBOOK_GUARD":
            continue
        if restriction["restriction_state"] != "ACTIVE":
            continue
        if not refs.covers(restriction, day["stay_date"]):
            continue
        restriction["restriction_state"] = "LIFTED"
        restriction["lifted_at"] = store.now_iso()
        restriction["lift_reason"] = "AUTO_GUARD_CLEARED"
        store.bump(restriction)
        restriction_batch(restriction)


# --- freeze windows ------------------------------------------------------

def frozen(connection):
    """True while a buffered freeze window of this connection covers the clock."""
    if connection is None:
        return False
    moment = store.now_iso()
    for window in where("freeze_windows", connection_id=connection["id"]):
        if window["effective_starts_at"] <= moment < window["ends_at"]:
            return True
    return False


def buffered_start(starts_at_dt):
    return starts_at_dt - timedelta(minutes=calc.FREEZE_PRE_BUFFER_MINUTES)


# --- mapping parity, mismatch and pushes --------------------------------

def refresh_parity(mapping):
    mapping["parity_state"] = calc.parity_verdict(mapping)


def refresh_mismatch(mapping):
    state, delta = calc.mismatch_verdict(mapping)
    mapping["mismatch_state"] = state
    mapping["mismatch_delta_cents"] = delta


def refresh_alert_count(channel):
    count = 0
    for mapping in where("mappings", channel_id=channel["id"]):
        if mapping["mismatch_state"] == "MISMATCHED":
            count += 1
    if count != channel["mismatch_alert_count"]:
        channel["mismatch_alert_count"] = count
        store.bump(channel)


def reparity_room_type(room_type_id):
    for mapping in where("mappings", room_type_id=room_type_id):
        verdict = calc.parity_verdict(mapping)
        if verdict != mapping["parity_state"]:
            mapping["parity_state"] = verdict
            store.bump(mapping)


# --- connection health ---------------------------------------------------

def record_failure(connection, failure_code):
    """A failure event: ERROR heartbeat or rejected job (PRD 3.3)."""
    connection["consecutive_failures"] += 1
    connection["last_failure_code"] = failure_code
    state = connection["connection_state"]
    streak = connection["consecutive_failures"]
    if state == "HEALTHY":
        if streak >= calc.CONNECTION_FAILURE_SUSPEND_THRESHOLD:
            suspend(connection)
        else:
            connection["connection_state"] = "DEGRADED"
    elif state == "DEGRADED":
        if streak >= calc.CONNECTION_FAILURE_SUSPEND_THRESHOLD:
            suspend(connection)
    store.bump(connection)


def suspend(connection):
    connection["connection_state"] = "SUSPENDED"
    connection["suspended_at"] = store.now_iso()
    recall_allotments(connection["channel_id"])


def recall_allotments(channel_id):
    touched = []
    for alloc in where("allocations", channel_id=channel_id):
        if alloc["allocation_state"] not in ("OPEN", "EXHAUSTED"):
            continue
        alloc["allocation_state"] = "RECALLED"
        alloc["recalled_at"] = store.now_iso()
        store.bump(alloc)
        if alloc["room_type_id"] not in touched:
            touched.append(alloc["room_type_id"])
    for room_type_id in touched:
        refresh_days(room_type_id)


def retire(connection):
    connection["connection_state"] = "RETIRED"
    for mapping in where("mappings", channel_id=connection["channel_id"]):
        if mapping["mapping_state"] in ("DRAFT", "VERIFIED", "ERRORED"):
            disable_mapping(mapping)
    recall_allotments(connection["channel_id"])
    store.bump(connection)


# --- mapping disable and job abandonment --------------------------------

def disable_mapping(mapping):
    mapping["mapping_state"] = "DISABLED"
    for job in refs.jobs_of_mapping(mapping["id"]):
        if job["job_state"] not in ("QUEUED", "REJECTED"):
            continue
        job["job_state"] = "ABANDONED"
        job["failure_reason"] = "MAPPING_DISABLED"
        store.bump(job)
        batch = get("batches", job["batch_id"])
        if batch is not None:
            rollup(batch)
            store.bump(batch)
    store.bump(mapping)


# --- dispatch ------------------------------------------------------------

def dispatch(batch):
    batch["dispatched_at"] = store.now_iso()
    batch["batch_state"] = "DISPATCHING"
    store.bump(batch)
    queued = [j for j in refs.jobs_of_batch(batch["id"]) if j["job_state"] == "QUEUED"]
    queued.sort(key=lambda job: job["sequence_index"])
    for job in queued:
        job["job_state"] = "DISPATCHED"
        job["attempt_count"] += 1
        store.bump(job)
        mapping = get("mappings", job["channel_mapping_id"])
        connection = refs.connection_of_channel(mapping["channel_id"])
        if connection is None or connection["connection_state"] in (
                "PENDING", "SUSPENDED", "RETIRED"):
            reject_job(job, mapping, connection, "CONNECTION_UNAVAILABLE")
        elif mapping["mapping_state"] != "VERIFIED":
            reject_job(job, mapping, connection, "MAPPING_NOT_VERIFIED")
        elif mapping["parity_state"] == "OUT_OF_PARITY":
            reject_job(job, mapping, connection, "PARITY_BLOCKED")
        else:
            apply_job(job, mapping)
        rollup(batch, dispatching=True)
    rollup(batch, dispatching=False)
    if batch["batch_state"] != "DISPATCHING":
        store.bump(batch)
        settle_promotion(batch)


def apply_job(job, mapping):
    job["job_state"] = "APPLIED"
    job["applied_at"] = store.now_iso()
    job["failure_reason"] = None
    store.bump(job)
    plan = get("rate_plans", mapping["rate_plan_id"])
    channel = get("channels", mapping["channel_id"])
    mapping["last_pushed_rate_cents"] = calc.distributed_rate(plan, channel)
    mapping["last_push_at"] = store.now_iso()
    refresh_mismatch(mapping)
    store.bump(mapping)
    refresh_alert_count(channel)


def reject_job(job, mapping, connection, reason):
    job["job_state"] = "REJECTED"
    job["applied_at"] = None
    job["failure_reason"] = reason
    store.bump(job)
    if reason in ("MAPPING_NOT_VERIFIED", "PARITY_BLOCKED") and \
            mapping["mapping_state"] == "VERIFIED":
        mapping["mapping_state"] = "ERRORED"
        store.bump(mapping)
    if connection is not None:
        record_failure(connection, "MAPPING_REJECTED")


def settle_promotion(batch):
    if batch["source_ref_kind"] != "PROMOTION":
        return
    promotion = get("promotions", batch["source_ref_id"])
    if promotion is None or promotion["distribution_status"] != "LOADING":
        return
    if batch["batch_state"] == "APPLIED":
        promotion["distribution_status"] = "LOADED"
        store.bump(promotion)
    elif batch["batch_state"] in ("FAILED", "PARTIALLY_APPLIED"):
        promotion["distribution_status"] = "LOAD_FAILED"
        store.bump(promotion)


def retry_job(job):
    job["job_state"] = "QUEUED"
    job["applied_at"] = None
    job["failure_reason"] = None
    store.bump(job)
    batch = get("batches", job["batch_id"])
    if batch is None:
        return
    rollup(batch, dispatching=False)
    store.bump(batch)
    if batch["source_ref_kind"] == "PROMOTION":
        promotion = get("promotions", batch["source_ref_id"])
        if promotion is not None and promotion["distribution_status"] == "LOAD_FAILED":
            promotion["distribution_status"] = "LOADING"
            store.bump(promotion)
