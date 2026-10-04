"""Crawl jobs, captures, playback, exclusion directives."""
from datetime import datetime

from flask import Blueprint, request

import db
from errors import (
    ERR_CRAWL_EXCLUDED, ERR_INVALID_STATE, ERR_SCHEDULE_NOT_DUE, not_found,
    raise_err, validation,
)
from middleware import require_roles
from models import (
    serialize_capture, serialize_crawl_job, serialize_directive, stamp_new,
    touch,
)
from response import paginate, parse_pagination, success_list, success_object
from services import (
    capture_is_suppressed_by_directive, capture_is_suppressed_by_rights,
    compute_storage_cost_cents, refresh_job_metrics,
    restore_captures_after_retract,
)

bp = Blueprint("crawl", __name__)


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _crawl_excluded(seed_url):
    return any(
        d["status"] == "ACTIVE"
        and d["scope"] in ("CRAWL_ONLY", "BOTH")
        and seed_url.startswith(d["url_prefix"])
        for d in db.directives.values()
    )


@bp.post("/archive/crawl-jobs")
def create_crawl_job():
    require_roles("CrawlOperator")
    body = request.get_json(silent=True) or {}
    seed_url = body.get("seed_url")
    scheduled_at = body.get("scheduled_at")
    rpm = body.get("requests_per_minute")
    at_risk = body.get("at_risk", False)
    # Priority 6: schema validity.
    if not isinstance(seed_url, str) or not seed_url:
        validation("seed_url is required")
    if not isinstance(scheduled_at, str):
        validation("scheduled_at is required")
    try:
        sched_dt = _ts(scheduled_at)
    except Exception:
        validation("scheduled_at must be a valid ISO 8601 timestamp")
    if not (sched_dt > db.now()):
        validation("scheduled_at must be strictly in the future")
    if isinstance(rpm, bool) or not isinstance(rpm, int) or not (1 <= rpm <= 120):
        validation("requests_per_minute must be an integer in 1..120")
    if not isinstance(at_risk, bool):
        validation("at_risk must be a boolean")
    # Priority 15: crawl exclusion gate at creation.
    if _crawl_excluded(seed_url):
        raise_err(ERR_CRAWL_EXCLUDED, "Seed URL is covered by an active exclusion directive")
    j = stamp_new()
    j.update({
        "seed_url": seed_url,
        "at_risk": at_risk,
        "scheduled_at": scheduled_at if scheduled_at.endswith("Z") else scheduled_at,
        "requests_per_minute": rpm,
        "status": "SCHEDULED",
        "captures_produced": 0,
        "duplicates_skipped": 0,
        "storage_cost_cents": 0,
    })
    db.crawl_jobs[j["id"]] = j
    return success_object(serialize_crawl_job(j), status=201)


@bp.get("/archive/crawl-jobs/<jid>")
def get_crawl_job(jid):
    require_roles("Admin", "CrawlOperator")
    j = db.crawl_jobs.get(jid)
    if j is None:
        not_found("Crawl job not found")
    return success_object(serialize_crawl_job(j))


@bp.post("/archive/crawl-jobs/<jid>/start")
def start_crawl_job(jid):
    require_roles("CrawlOperator")
    j = db.crawl_jobs.get(jid)
    if j is None:
        not_found("Crawl job not found")
    if j["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Job is not SCHEDULED")
    # Priority 14: schedule due.
    if not (db.now() >= _ts(j["scheduled_at"])):
        raise_err(ERR_SCHEDULE_NOT_DUE, "The crawl schedule is not yet due")
    # Priority 15: exclusion re-check at start.
    if _crawl_excluded(j["seed_url"]):
        raise_err(ERR_CRAWL_EXCLUDED, "Seed URL is covered by an active exclusion directive")
    j["status"] = "RUNNING"
    touch(j)
    return success_object(serialize_crawl_job(j))


@bp.post("/archive/crawl-jobs/<jid>/complete")
def complete_crawl_job(jid):
    require_roles("CrawlOperator")
    j = db.crawl_jobs.get(jid)
    if j is None:
        not_found("Crawl job not found")
    if j["status"] != "RUNNING":
        raise_err(ERR_INVALID_STATE, "Job is not RUNNING")
    refresh_job_metrics(j)
    j["status"] = "COMPLETED"
    touch(j)
    return success_object(serialize_crawl_job(j))


@bp.post("/archive/captures")
def record_capture():
    require_roles("CrawlOperator")
    body = request.get_json(silent=True) or {}
    job_id = body.get("crawl_job_id")
    url = body.get("url")
    content_hash = body.get("content_hash")
    has_dynamic = body.get("has_dynamic_content")
    # Priority 3: job existence.
    if job_id is not None and job_id not in db.crawl_jobs:
        not_found("Crawl job not found")
    # Priority 4: job must be RUNNING.
    if job_id is not None and db.crawl_jobs[job_id]["status"] != "RUNNING":
        raise_err(ERR_INVALID_STATE, "Crawl job is not RUNNING")
    # Priority 6: schema.
    if not isinstance(job_id, str) or not job_id:
        validation("crawl_job_id is required")
    if not isinstance(url, str) or not url:
        validation("url is required")
    if not isinstance(content_hash, str) or not content_hash:
        validation("content_hash is required")
    if not isinstance(has_dynamic, bool):
        validation("has_dynamic_content must be a boolean")
    job = db.crawl_jobs[job_id]
    # Dedupe on (url, content_hash) across all captures.
    for c in db.captures.values():
        if c["url"] == url and c["content_hash"] == content_hash:
            job["duplicates_skipped"] += 1
            touch(job)
            return success_object(serialize_capture(c), status=200)
    c = stamp_new(common=False)
    c.update({
        "crawl_job_id": job_id,
        "url": url,
        "content_hash": content_hash,
        "captured_at": db.now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "has_dynamic_content": has_dynamic,
        "playback_status": "PLAYABLE",
    })
    db.captures[c["id"]] = c
    job["captures_produced"] += 1
    job["storage_cost_cents"] = compute_storage_cost_cents(job)
    touch(job)
    return success_object(serialize_capture(c), status=201)


@bp.get("/archive/crawl-jobs/<jid>/captures")
def list_job_captures(jid):
    require_roles("Admin", "CrawlOperator")
    if jid not in db.crawl_jobs:
        not_found("Crawl job not found")
    limit, offset = parse_pagination(request.args)
    url = request.args.get("url")
    pbs = request.args.get("playback_status")
    rows = [c for c in db.captures.values() if c["crawl_job_id"] == jid]
    if url is not None:
        rows = [c for c in rows if c["url"] == url]
    if pbs is not None:
        rows = [c for c in rows if c["playback_status"] == pbs]
    rows.sort(key=lambda c: c["created_at"])
    page, total = paginate([serialize_capture(c) for c in rows], limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/archive/captures/<cid>")
def get_capture(cid):
    require_roles("Admin", "CrawlOperator")
    c = db.captures.get(cid)
    if c is None:
        not_found("Capture not found")
    return success_object(serialize_capture(c))


@bp.get("/archive/playback")
def playback():
    require_roles("Admin", "CrawlOperator", "Patron", "LibraryAdmin")
    url = request.args.get("url")
    requested_at = request.args.get("requested_at")
    if not isinstance(url, str) or not url:
        validation("url is required")
    # Live suppression override.
    if capture_is_suppressed_by_directive(url) or capture_is_suppressed_by_rights(url):
        return success_object({
            "mode": "SUPPRESSED",
            "capture_id": None,
            "captured_at": None,
            "has_dynamic_content": None,
        })
    candidates = [
        c for c in db.captures.values()
        if c["url"] == url and c["playback_status"] == "PLAYABLE"
    ]
    if requested_at:
        try:
            target = _ts(requested_at)
        except Exception:
            validation("requested_at must be a valid ISO 8601 timestamp")
        def key(c):
            diff_ms = abs((_ts(c["captured_at"]) - target).total_seconds() * 1000)
            # Exact tie between an earlier and a later capture: earlier wins.
            # Prefer the earlier captured_at at equal distance, then created_at.
            earlier_first = 0 if _ts(c["captured_at"]) <= target else 1
            return (diff_ms, earlier_first, c["created_at"])
        candidates.sort(key=key)
    else:
        candidates.sort(key=lambda c: c["captured_at"], reverse=True)
    if not candidates:
        return success_object({
            "mode": "NOT_FOUND",
            "capture_id": None,
            "captured_at": None,
            "has_dynamic_content": None,
        })
    pick = candidates[0]
    mode = "DEGRADED" if pick["has_dynamic_content"] else "FULL"
    return success_object({
        "mode": mode,
        "capture_id": pick["id"],
        "captured_at": pick["captured_at"],
        "has_dynamic_content": pick["has_dynamic_content"],
    })


@bp.post("/archive/exclusion-directives")
def create_directive():
    require_roles("CrawlOperator")
    body = request.get_json(silent=True) or {}
    url_prefix = body.get("url_prefix")
    scope = body.get("scope")
    reason = body.get("reason")
    if not isinstance(url_prefix, str) or not url_prefix:
        validation("url_prefix is required")
    if scope not in ("CRAWL_ONLY", "PLAYBACK_ONLY", "BOTH"):
        validation("scope must be CRAWL_ONLY, PLAYBACK_ONLY, or BOTH")
    if not isinstance(reason, str) or not reason:
        validation("reason is required")
    d = stamp_new()
    d.update({
        "url_prefix": url_prefix,
        "scope": scope,
        "status": "ACTIVE",
        "reason": reason,
    })
    db.directives[d["id"]] = d
    blocked_job_ids = []
    if scope in ("CRAWL_ONLY", "BOTH"):
        for j in db.crawl_jobs.values():
            if j["status"] == "SCHEDULED" and j["seed_url"].startswith(url_prefix):
                j["status"] = "BLOCKED"
                touch(j)
                blocked_job_ids.append(j["id"])
    suppressed = 0
    if scope in ("PLAYBACK_ONLY", "BOTH"):
        for c in db.captures.values():
            if c["url"].startswith(url_prefix) and c["playback_status"] == "PLAYABLE":
                c["playback_status"] = "SUPPRESSED"
                suppressed += 1
    return success_object({
        "directive_id": d["id"],
        "blocked_job_ids": blocked_job_ids,
        "suppressed_capture_count": suppressed,
    }, status=201)


@bp.post("/archive/exclusion-directives/<did>/retract")
def retract_directive(did):
    require_roles("CrawlOperator")
    d = db.directives.get(did)
    if d is None:
        not_found("Exclusion directive not found")
    if d["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Directive is not ACTIVE")
    d["status"] = "RETRACTED"
    touch(d)
    restore_captures_after_retract(d["url_prefix"])
    return success_object(serialize_directive(d))
