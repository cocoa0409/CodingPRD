"""Distribution batches, job dispatch and retry (PRD 3.10)."""

from flask import Blueprint

import calc
import cascade
import refs
import serialize
import shape
from envelope import ok
from errors import fail
from guards import must, page
from refs import get, rows

bp = Blueprint("dist", __name__)

INTERNAL = shape.INTERNAL_ROLES
BATCH_STATES = ("QUEUED", "DISPATCHING", "APPLIED", "PARTIALLY_APPLIED", "FAILED")
PAYLOAD_KINDS = ("RATE", "RESTRICTION", "PROMOTION")
JOB_STATES = ("QUEUED", "DISPATCHED", "APPLIED", "REJECTED", "ABANDONED")


@bp.post("/distribution/distribution-batches/<bid>/dispatch")
def dispatch_batch(bid):
    shape.auth("ChannelOpsEngineer")
    batch = must("batches", bid, "ERR_BATCH_NOT_FOUND")
    queued = [j for j in refs.jobs_of_batch(batch["id"])
              if j["job_state"] == "QUEUED"]
    if batch["batch_state"] not in ("QUEUED", "PARTIALLY_APPLIED", "FAILED") or \
            batch["total_jobs"] < 1 or not queued:
        fail("ERR_BATCH_NOT_DISPATCHABLE")
    for job in queued:
        mapping = get("mappings", job["channel_mapping_id"])
        if mapping is None:
            continue
        connection = refs.connection_of_channel(mapping["channel_id"])
        if cascade.frozen(connection):
            fail("ERR_CONNECTION_FROZEN")
    cascade.dispatch(batch)
    return ok(serialize.batch_out(batch))


@bp.post("/distribution/distribution-jobs/<jid>/retry")
def retry_job(jid):
    shape.auth("ChannelOpsEngineer")
    job = must("jobs", jid, "ERR_JOB_NOT_FOUND")
    if job["job_state"] != "REJECTED" or \
            job["attempt_count"] >= calc.MAX_JOB_ATTEMPTS:
        fail("ERR_JOB_NOT_RETRYABLE")
    cascade.retry_job(job)
    return ok(serialize.job_out(job))


@bp.get("/distribution/distribution-batches")
def list_batches():
    shape.auth(*INTERNAL)
    property_id = shape.q_id("property_id")
    state = shape.q_enum("batch_state", BATCH_STATES)
    payload_kind = shape.q_enum("payload_kind", PAYLOAD_KINDS)
    records = rows("batches")
    if property_id is not None:
        records = [r for r in records if r["property_id"] == property_id]
    if state is not None:
        records = [r for r in records if r["batch_state"] == state]
    if payload_kind is not None:
        records = [r for r in records if r["payload_kind"] == payload_kind]
    return page(serialize.batch_out, records)


@bp.get("/distribution/distribution-batches/<bid>")
def read_batch(bid):
    shape.auth(*INTERNAL)
    batch = must("batches", bid, "ERR_BATCH_NOT_FOUND")
    return ok(serialize.batch_out(batch))


@bp.get("/distribution/distribution-jobs")
def list_jobs():
    shape.auth(*INTERNAL)
    batch_id = shape.q_id("batch_id")
    mapping_id = shape.q_id("channel_mapping_id")
    state = shape.q_enum("job_state", JOB_STATES)
    records = rows("jobs")
    if batch_id is not None:
        records = [r for r in records if r["batch_id"] == batch_id]
    if mapping_id is not None:
        records = [r for r in records if r["channel_mapping_id"] == mapping_id]
    if state is not None:
        records = [r for r in records if r["job_state"] == state]
    return page(serialize.job_out, records)


@bp.get("/distribution/distribution-jobs/<jid>")
def read_job(jid):
    shape.auth(*INTERNAL)
    job = must("jobs", jid, "ERR_JOB_NOT_FOUND")
    return ok(serialize.job_out(job))
