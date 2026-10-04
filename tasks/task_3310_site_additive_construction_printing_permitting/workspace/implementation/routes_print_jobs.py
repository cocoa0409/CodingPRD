"""Print job scheduling and state-transition routes."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, now, fmt_dt, stamp_created, touch, parse_dt
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_POSTURE_BLOCKED,
    ERR_PERMIT_NOT_APPROVED,
    ERR_PERMIT_REVISION_SUPERSEDED,
    ERR_PLAN_REVISION_NOT_APPROVED,
    ERR_PRINTER_NOT_QUALIFIED,
    ERR_BATCH_NOT_PUMPABLE,
    ERR_WEATHER_NOT_PERMISSIBLE,
    ERR_PRINT_SCHEDULE_OVERLAP,
    ERR_INTERRUPTION_CURE_EXCEEDED,
    ERR_PRINT_INCOMPLETE,
)
from middleware import require_roles, parse_pagination
from validate import body_dict, req_str, req_int, req_dt, req_enum
from response import success_object, success_list
import services

bp = Blueprint("print_jobs", __name__)

CAUSES = {"WEATHER", "MATERIAL", "MECHANICAL", "OPERATOR", "INSPECTOR_HOLD"}
NON_TERMINAL = ("SCHEDULED", "READY_TO_PRINT", "PRINTING", "PAUSED")


def _site_or_404(site_id):
    site = store.sites.get(site_id)
    if site is None:
        raise_err(ERR_NOT_FOUND, "site not found")
    services.lazy_eval_site(site)
    return site


def _job_or_404(site_id, job_id):
    job = store.print_jobs.get(job_id)
    if job is None or job["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "print job not found")
    return job


def _check_site_version(site, body):
    expected = body.get("expected_site_version")
    if expected is None:
        raise_err(ERR_INVALID_REQUEST, "expected_site_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_site_version must be an integer")
    if expected != site["version"]:
        raise_err(ERR_STALE_VERSION, "expected_site_version does not match site version")


def _overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _refresh_site_after_job_change(site):
    """ACTIVE_PRINT <-> SITE_READY recomputation."""
    if site["status"] in ("ACTIVE_PRINT", "SITE_READY"):
        active = any(
            j["status"] in ("PRINTING", "PAUSED")
            for j in services.site_jobs(site["id"])
        )
        site["status"] = "ACTIVE_PRINT" if active else "SITE_READY"
        touch(site)
    services.recompute_posture(site["id"])


@bp.post("/construction/sites/<site_id>/print-jobs")
def create_print_job(site_id):
    require_roles("PrintOperator")
    site = _site_or_404(site_id)
    body = body_dict(request.get_json(silent=True))
    _check_site_version(site, body)
    rev_id = req_str(body, "plan_revision_id")
    setup_id = req_str(body, "printer_setup_id")
    start = req_dt(body, "scheduled_start_at")
    end = req_dt(body, "scheduled_end_at")
    layers = req_int(body, "total_layers_planned", minimum=1)
    if rev_id not in store.revisions:
        raise_err(ERR_NOT_FOUND, "plan revision not found")
    setup = store.printer_setups.get(setup_id)
    if setup is None or setup["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "printer setup not found on this site")
    # schedule overlap on create (calculation print_schedule_overlap)
    for other in services.site_jobs(site_id):
        if other["status"] in NON_TERMINAL:
            if _overlap(start, end, parse_dt(other["scheduled_start_at"]), parse_dt(other["scheduled_end_at"])):
                raise_err(ERR_PRINT_SCHEDULE_OVERLAP, "scheduled interval overlaps another print job")
    job = stamp_created({
        "site_id": site_id,
        "plan_revision_id": rev_id,
        "printer_setup_id": setup_id,
        "scheduled_start_at": fmt_dt(start),
        "scheduled_end_at": fmt_dt(end),
        "actual_start_at": None,
        "actual_end_at": None,
        "total_layers_planned": layers,
        "layers_printed": 0,
        "cumulative_interruption_minutes": 0,
        "continuous_run_minutes": None,
        "max_permissible_interruption_minutes": None,
        "consumed_batch_id": None,
        "posture": "READY",
        "status": "SCHEDULED",
    })
    store.print_jobs[job["id"]] = job
    touch(site)
    return success_object(job, status=201)


@bp.get("/construction/sites/<site_id>/print-jobs")
def list_print_jobs(site_id):
    require_roles("PlatformAdmin", "SiteManager", "PrintOperator", "QualityInspector", "TradeContractor")
    _site_or_404(site_id)
    limit, offset = parse_pagination()
    jobs = services.site_jobs(site_id)
    status_filter = request.args.get("status")
    if status_filter:
        jobs = [j for j in jobs if j["status"] == status_filter]
    jobs.sort(key=lambda j: j["created_at"])
    total = len(jobs)
    return success_list(jobs[offset:offset + limit], limit, offset, total)


def _fresh_weather_ok(site_id):
    obs = services.latest_weather(site_id)
    if obs is None or not obs["is_print_permissible"]:
        return False
    observed = parse_dt(obs["observed_at"])
    return now() <= observed + timedelta(minutes=services.WEATHER_OBSERVATION_VALID_MIN)


def _qualified_batch(site_id):
    batches = [
        b for b in store.batches.values()
        if b["site_id"] == site_id and b["status"] == "QUALIFIED" and b["is_pumpable"]
    ]
    batches.sort(key=lambda b: b["created_at"])
    return batches[0] if batches else None


def _permit_covering(site_id, rev_id):
    apps = [
        p for p in store.permits.values()
        if p["site_id"] == site_id and p["plan_revision_id"] == rev_id
    ]
    apps.sort(key=lambda p: p["created_at"])
    for p in reversed(apps):
        if p["status"] == "APPROVED":
            return p
    return None


@bp.post("/construction/sites/<site_id>/print-jobs/<job_id>/transition")
def transition_job(site_id, job_id):
    require_roles("PrintOperator")
    site = _site_or_404(site_id)
    job = _job_or_404(site_id, job_id)
    body = body_dict(request.get_json(silent=True))
    to_state = body.get("to_state")
    if not isinstance(to_state, str):
        raise_err(ERR_INVALID_REQUEST, "to_state is required")

    if to_state == "READY_TO_PRINT":
        return _to_ready(site, job)
    if to_state == "PRINTING":
        return _to_printing(site, job)
    if to_state == "PAUSED":
        return _to_paused(site, job, body)
    if to_state == "COMPLETED":
        return _to_completed(site, job)
    if to_state == "ABORTED":
        return _to_aborted(site, job)
    if to_state == "CANCELLED":
        return _to_cancelled(site, job)
    raise_err(ERR_INVALID_REQUEST, "unknown to_state %s" % to_state)


def _to_ready(site, job):
    if job["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "job must be SCHEDULED")
    # priority 9: referential integrity
    rev = store.revisions.get(job["plan_revision_id"])
    if rev is None:
        raise_err(ERR_NOT_FOUND, "plan revision not found")
    if rev["status"] == "VOIDED":
        raise_err(ERR_PERMIT_REVISION_SUPERSEDED, "referenced revision has been voided")
    if rev["status"] != "APPROVED":
        raise_err(ERR_PLAN_REVISION_NOT_APPROVED, "referenced revision is not APPROVED")
    permit = _permit_covering(site["id"], job["plan_revision_id"])
    if permit is None:
        raise_err(ERR_PERMIT_NOT_APPROVED, "no APPROVED permit covers this revision")
    setup = store.printer_setups.get(job["printer_setup_id"])
    if setup is None or setup["status"] != "QUALIFIED":
        raise_err(ERR_PRINTER_NOT_QUALIFIED, "printer setup is not QUALIFIED")
    batch = _qualified_batch(site["id"])
    if batch is None:
        raise_err(ERR_BATCH_NOT_PUMPABLE, "no QUALIFIED pumpable batch available")
    # priority 11: weather + schedule constraints
    if not _fresh_weather_ok(site["id"]):
        raise_err(ERR_WEATHER_NOT_PERMISSIBLE, "latest weather observation is not print-permissible")
    start = parse_dt(job["scheduled_start_at"])
    end = parse_dt(job["scheduled_end_at"])
    if start < now() or end <= start:
        raise_err(ERR_INVALID_REQUEST, "scheduled window is invalid or in the past")
    for other in services.site_jobs(site["id"]):
        if other["id"] != job["id"] and other["status"] in NON_TERMINAL:
            if _overlap(start, end, parse_dt(other["scheduled_start_at"]), parse_dt(other["scheduled_end_at"])):
                raise_err(ERR_PRINT_SCHEDULE_OVERLAP, "scheduled interval overlaps another print job")
    job["status"] = "READY_TO_PRINT"
    job["posture"] = "READY"
    job["consumed_batch_id"] = batch["id"]
    touch(job)
    services.recompute_posture(site["id"])
    return success_object(job)


def _to_printing(site, job):
    if job["status"] == "READY_TO_PRINT":
        # priority 6: posture gate
        if site["posture"] == "STOP":
            raise_err(ERR_POSTURE_BLOCKED, "site posture is STOP")
        if now() < parse_dt(job["scheduled_start_at"]):
            raise_err(ERR_INVALID_STATE, "scheduled start has not been reached")
        if not _fresh_weather_ok(site["id"]):
            raise_err(ERR_WEATHER_NOT_PERMISSIBLE, "latest weather observation is not print-permissible")
        job["status"] = "PRINTING"
        job["actual_start_at"] = fmt_dt(now())
        touch(job)
        _refresh_site_after_job_change(site)
        return success_object(job)
    if job["status"] == "PAUSED":
        return _resume(site, job)
    raise_err(ERR_INVALID_STATE, "job cannot go to PRINTING from %s" % job["status"])


def _to_paused(site, job, body):
    if job["status"] != "PRINTING":
        raise_err(ERR_INVALID_STATE, "job must be PRINTING to pause")
    cause = body.get("cause")
    if cause not in CAUSES:
        raise_err(ERR_INVALID_REQUEST, "cause is required and must be a known cause")
    batch = store.batches.get(job.get("consumed_batch_id"))
    max_min = services.MAX_INTERRUPTION_MIN[batch["mix_code"]] if batch else None
    intr = stamp_created({
        "print_job_id": job["id"],
        "cause": cause,
        "paused_at": fmt_dt(now()),
        "resumed_at": None,
        "duration_minutes": None,
        "cure_penalty_layers": None,
        "max_permissible_interruption_minutes": max_min,
        "status": "OPEN",
    })
    store.interruptions[intr["id"]] = intr
    job["max_permissible_interruption_minutes"] = max_min
    job["status"] = "PAUSED"
    touch(job)
    if cause == "WEATHER":
        services.recompute_posture(site["id"])
    return success_object(job)


def _resume(site, job):
    intr = services.open_interruption(job["id"])
    # PRD §3.7: once the interruption's cure window is exceeded (whether the
    # OVERRUN flag was applied by lazy evaluation or is crossed by this very
    # resume attempt), the resume is rejected with
    # ERR_INTERRUPTION_CURE_EXCEEDED. This check runs before the priority-6
    # posture gate because an OVERRUN interruption caused by the job's own
    # pause is what puts the site into STOP; reporting POSTURE_BLOCKED would
    # mask the operative rejection.
    if intr is None:
        any_overrun = any(
            i["status"] == "OVERRUN" for i in services.job_interruptions(job["id"])
        )
        if any_overrun:
            raise_err(
                ERR_INTERRUPTION_CURE_EXCEEDED,
                "interruption exceeded its cure window",
            )
        raise_err(ERR_INVALID_STATE, "no OPEN interruption on this job")
    elapsed = (now() - parse_dt(intr["paused_at"])).total_seconds() / 60.0
    max_min = intr.get("max_permissible_interruption_minutes")
    if max_min is not None and elapsed > max_min:
        intr["status"] = "OVERRUN"
        touch(intr)
        job["posture"] = "BLOCKED"
        touch(job)
        services.recompute_posture(site["id"])
        raise_err(ERR_INTERRUPTION_CURE_EXCEEDED, "interruption exceeded its cure window")
    # Priority 6 posture gate (STOP from another job's overrun, a
    # DEMOLISH_REQUIRED inspection, or suspension).
    if site["posture"] == "STOP":
        raise_err(ERR_POSTURE_BLOCKED, "site posture is STOP")
    if not _fresh_weather_ok(site["id"]):
        raise_err(ERR_WEATHER_NOT_PERMISSIBLE, "latest weather observation is not print-permissible")
    if intr["cause"] == "MATERIAL":
        if _qualified_batch(site["id"]) is None:
            raise_err(ERR_BATCH_NOT_PUMPABLE, "no fresh QUALIFIED batch available")
        new_batch = _qualified_batch(site["id"])
        old = store.batches.get(job.get("consumed_batch_id"))
        if old is not None and old["status"] == "QUALIFIED" and old["id"] != new_batch["id"]:
            old["status"] = "EXHAUSTED"
            touch(old)
        job["consumed_batch_id"] = new_batch["id"]
    services.close_interruption(intr)
    services.recompute_cumulative_interruption(job)
    job["status"] = "PRINTING"
    touch(job)
    if job["cumulative_interruption_minutes"] > services.HARD_INTERRUPTION_CAP_MIN:
        _abort_effects(site, job)
        job["status"] = "ABORTED"
        touch(job)
    _refresh_site_after_job_change(site)
    return success_object(job)


def _to_completed(site, job):
    if job["status"] != "PRINTING":
        raise_err(ERR_INVALID_STATE, "job must be PRINTING to complete")
    insps = services.job_inspections(job["id"])
    if job["layers_printed"] < job["total_layers_planned"]:
        raise_err(ERR_PRINT_INCOMPLETE, "layers printed below plan")
    if any(i["disposition"] == "PENDING" for i in insps):
        raise_err(ERR_PRINT_INCOMPLETE, "a layer inspection is still PENDING")
    if any(i["disposition"] == "DEMOLISH_REQUIRED" for i in insps):
        raise_err(ERR_PRINT_INCOMPLETE, "a DEMOLISH_REQUIRED inspection blocks completion")
    end = now()
    job["actual_end_at"] = fmt_dt(end)
    start = parse_dt(job["actual_start_at"])
    elapsed_min = int((end - start).total_seconds() // 60)
    job["continuous_run_minutes"] = max(0, elapsed_min - job["cumulative_interruption_minutes"])
    job["status"] = "COMPLETED"
    job["utilization"] = None
    touch(job)
    batch = store.batches.get(job.get("consumed_batch_id"))
    if batch is not None and batch["status"] == "QUALIFIED":
        batch["status"] = "EXHAUSTED"
        touch(batch)
    _refresh_site_after_job_change(site)
    # learning curve + utilization
    dep_id = site.get("community_deployment_id")
    if dep_id:
        dep = store.deployments.get(dep_id)
        if dep is not None:
            job["utilization"] = services.job_utilization(job, site)
            services.recompute_learning_curve(dep)
            touch(dep)
    services.reevaluate_trade_tasks(site["id"])
    return success_object(job)


def _abort_effects(site, job):
    intr = services.open_interruption(job["id"])
    if intr is not None:
        services.close_interruption(intr)
        services.recompute_cumulative_interruption(job)
    batch = store.batches.get(job.get("consumed_batch_id"))
    if batch is not None and batch["status"] == "QUALIFIED":
        batch["status"] = "EXHAUSTED"
        touch(batch)


def _to_aborted(site, job):
    if job["status"] not in ("PRINTING", "PAUSED"):
        raise_err(ERR_INVALID_STATE, "job must be PRINTING or PAUSED to abort")
    _abort_effects(site, job)
    job["status"] = "ABORTED"
    touch(job)
    _refresh_site_after_job_change(site)
    return success_object(job)


def _to_cancelled(site, job):
    if job["status"] not in ("SCHEDULED", "READY_TO_PRINT"):
        raise_err(ERR_INVALID_STATE, "job must be SCHEDULED or READY_TO_PRINT to cancel")
    job["status"] = "CANCELLED"
    touch(job)
    _refresh_site_after_job_change(site)
    return success_object(job)
