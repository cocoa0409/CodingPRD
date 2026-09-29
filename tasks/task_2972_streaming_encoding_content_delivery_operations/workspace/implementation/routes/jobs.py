"""Catalog reprocessing jobs and the encode budget (PRD 3.9)."""

from flask import Blueprint

from db import db, dec, new_row, q2, rows, sort_rows, touch
from errors import ApiError
from middleware import endpoint
from response import created, ok, read_page_params
from routes.common import (
    CODEC_FAMILIES, JOB_STATES, TRIGGER_REASONS, apply_filters, get_job,
    get_ladder, get_title, send_list,
)
from services import calc
from services.domain import recompute_budget
from validation import S, parse_body, parse_query

bp = Blueprint("jobs", __name__)

JOB_CREATE = [
    S("title_id", "string"),
    S("source_ladder_id", "string"),
    S("trigger_reason", "enum", values=TRIGGER_REASONS),
    S("target_codec_family", "enum", values=CODEC_FAMILIES),
    S("expected_title_version", "integer", minimum=1),
]


def _has_eligible_master(title_id):
    return any(a["qc_state"] != "QC_REJECTED" for a in calc.title_assets(title_id))


@bp.post("/reprocess-jobs")
@endpoint(["EncodingEngineer"])
def create_job():
    payload = parse_body(JOB_CREATE)
    title = get_title(payload["title_id"])
    source = get_ladder(payload["source_ladder_id"])
    # Rung 11 is cascading here: the LOCKED requirement is only evaluated when
    # the title already owns an eligible source master.
    if _has_eligible_master(title["id"]) and source["state"] != "LOCKED":
        raise ApiError("ERR_LADDER_NOT_LOCKED")
    if payload["expected_title_version"] != title["version"]:
        raise ApiError("ERR_STALE_TITLE_VERSION")
    if source["title_id"] != title["id"]:
        raise ApiError("ERR_LADDER_TITLE_MISMATCH")
    if payload["target_codec_family"] == source["codec_family"]:
        raise ApiError("ERR_REPROCESS_CODEC_UNCHANGED")
    for other in calc.title_jobs(title["id"]):
        if other["state"] in ("QUEUED", "RUNNING"):
            raise ApiError("ERR_REPROCESS_JOB_IN_FLIGHT")
    if not _has_eligible_master(title["id"]):
        raise ApiError("ERR_REPROCESS_NO_SOURCE_ASSET")

    per_rung, estimate = calc.reprocess_cost(
        title["id"], source["rungs"], payload["target_codec_family"]
    )
    job = new_row()
    job["title_id"] = title["id"]
    job["source_ladder_id"] = source["id"]
    job["trigger_reason"] = payload["trigger_reason"]
    job["target_codec_family"] = payload["target_codec_family"]
    job["state"] = "QUEUED"
    job["result_ladder_id"] = None
    job["per_rung_cost_usd"] = per_rung
    job["cost_estimate_usd"] = estimate
    job["priority_rank"] = calc.priority_rank(payload["trigger_reason"], estimate)
    job["committed_usd"] = q2(0)
    job["abort_reason"] = "NONE"
    db.jobs[job["id"]] = job
    touch(title)
    return created(job)


@bp.get("/reprocess-jobs/<job_id>")
@endpoint(["EncodingEngineer", "ContentOps", "PlatformAdmin"])
def read_job(job_id):
    parse_query([], allow_paging=False)
    return ok(get_job(job_id))


@bp.get("/reprocess-jobs")
@endpoint(["EncodingEngineer", "ContentOps", "PlatformAdmin"])
def list_jobs():
    filters = parse_query([
        S("title_id", "string"),
        S("source_ladder_id", "string"),
        S("result_ladder_id", "string"),
        S("state", "enum", values=JOB_STATES),
    ])
    page, page_size = read_page_params()
    items = apply_filters(rows(db.jobs), filters, {})
    ordered = sort_rows(items, [
        (lambda r: r["priority_rank"], True),
        (lambda r: r["created_at"], False),
    ])
    return send_list(ordered, page, page_size)


@bp.post("/reprocess-jobs/<job_id>/run")
@endpoint(["EncodingEngineer"])
def run_job(job_id):
    parse_body([])
    job = get_job(job_id)
    if job["state"] != "QUEUED":
        raise ApiError("ERR_JOB_STATE_INVALID")
    title = db.titles[job["title_id"]]
    for other in calc.title_jobs(title["id"]):
        if other["id"] != job["id"] and other["state"] == "RUNNING":
            raise ApiError("ERR_JOB_STATE_INVALID")
    source = db.ladders.get(job["source_ladder_id"])
    if source is None or source["state"] != "LOCKED":
        raise ApiError("ERR_LADDER_NOT_LOCKED")
    if dec(job["cost_estimate_usd"]) > dec(title["encode_budget_remaining_usd"]):
        raise ApiError("ERR_ENCODE_BUDGET_EXCEEDED")
    job["state"] = "RUNNING"
    job["committed_usd"] = q2(job["cost_estimate_usd"])
    touch(job)
    recompute_budget(title)
    touch(title)
    return ok(job)


@bp.post("/reprocess-jobs/<job_id>/abort")
@endpoint(["EncodingEngineer"])
def abort_job(job_id):
    # Only OPERATOR_ABORT may be asserted by a caller.
    payload = parse_body([S("abort_reason", "enum", values=("OPERATOR_ABORT",))])
    job = get_job(job_id)
    if job["state"] not in ("QUEUED", "RUNNING"):
        raise ApiError("ERR_JOB_STATE_INVALID")
    title = db.titles[job["title_id"]]
    was_running = job["state"] == "RUNNING"
    job["state"] = "ABORTED"
    job["abort_reason"] = payload["abort_reason"]
    job["committed_usd"] = q2(0)
    touch(job)
    if was_running:
        # The compensating action for the run debit.
        recompute_budget(title)
        touch(title)
    return ok(job)
