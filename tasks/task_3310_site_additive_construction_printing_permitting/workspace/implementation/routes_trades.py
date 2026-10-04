"""Conventional trade task routes."""
from flask import Blueprint, request

from db import store, now, fmt_dt, stamp_created, touch, parse_dt
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_POSTURE_BLOCKED,
    ERR_TRADE_TOO_EARLY,
    ERR_TRADE_OVERRUN,
    ERR_FORBIDDEN,
)
from middleware import require_roles, get_role, parse_pagination
from validate import body_dict, req_enum, req_int, req_dt, opt_str
from response import success_object, success_list
import services

bp = Blueprint("trades", __name__)

TRADES = {"ROOF", "ELECTRICAL", "PLUMBING", "MECHANICAL"}


def _site_or_404(site_id):
    site = store.sites.get(site_id)
    if site is None:
        raise_err(ERR_NOT_FOUND, "site not found")
    services.lazy_eval_site(site)
    return site


def _check_site_version(site, body):
    expected = body.get("expected_site_version")
    if expected is None:
        raise_err(ERR_INVALID_REQUEST, "expected_site_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_site_version must be an integer")
    if expected != site["version"]:
        raise_err(ERR_STALE_VERSION, "expected_site_version does not match site version")


@bp.post("/construction/sites/<site_id>/trade-tasks")
def create_trade_task(site_id):
    require_roles("SiteManager")
    site = _site_or_404(site_id)
    body = body_dict(request.get_json(silent=True))
    _check_site_version(site, body)
    job_id = body.get("depends_on_print_job_id")
    if not isinstance(job_id, str) or not job_id:
        raise_err(ERR_INVALID_REQUEST, "depends_on_print_job_id is required")
    job = store.print_jobs.get(job_id)
    if job is None or job["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "depended-on print job not found on this site")
    depends_trade = opt_str(body, "depends_on_trade_task_id")
    if depends_trade is not None:
        prior = store.trade_tasks.get(depends_trade)
        if prior is None or prior["site_id"] != site_id:
            raise_err(ERR_NOT_FOUND, "depended-on trade task not found on this site")
    task = stamp_created({
        "site_id": site_id,
        "trade": req_enum(body, "trade", TRADES),
        "sequence_rank": req_int(body, "sequence_rank", minimum=1),
        "earliest_start_at": fmt_dt(req_dt(body, "earliest_start_at")),
        "latest_end_at": fmt_dt(req_dt(body, "latest_end_at")),
        "depends_on_print_job_id": job_id,
        "depends_on_trade_task_id": depends_trade,
        "actual_start_at": None,
        "actual_end_at": None,
        "is_startable": False,
        "start_blockers": [],
        "status": "PLANNED",
    })
    store.trade_tasks[task["id"]] = task
    services.recompute_trade_task(task)
    touch(site)
    return success_object(task, status=201)


@bp.get("/construction/sites/<site_id>/trade-tasks")
def list_trade_tasks(site_id):
    require_roles("PlatformAdmin", "SiteManager", "TradeContractor", "QualityInspector")
    _site_or_404(site_id)
    limit, offset = parse_pagination()
    tasks = [t for t in store.trade_tasks.values() if t["site_id"] == site_id]
    status_filter = request.args.get("status")
    if status_filter:
        tasks = [t for t in tasks if t["status"] == status_filter]
    trade_filter = request.args.get("trade")
    if trade_filter:
        tasks = [t for t in tasks if t["trade"] == trade_filter]
    tasks.sort(key=lambda t: t["created_at"])
    total = len(tasks)
    return success_list(tasks[offset:offset + limit], limit, offset, total)


@bp.post("/construction/sites/<site_id>/trade-tasks/<task_id>/transition")
def transition_trade_task(site_id, task_id):
    role = require_roles("TradeContractor", "SiteManager")
    site = _site_or_404(site_id)
    task = store.trade_tasks.get(task_id)
    if task is None or task["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "trade task not found")
    body = body_dict(request.get_json(silent=True))
    to_state = body.get("to_state")
    if not isinstance(to_state, str):
        raise_err(ERR_INVALID_REQUEST, "to_state is required")

    if to_state == "IN_PROGRESS":
        if role != "TradeContractor":
            raise_err(ERR_FORBIDDEN, "only TradeContractor may start a trade task")
        services.reevaluate_trade_tasks(site_id)
        services.recompute_trade_task(task)
        # priority 6: posture gate
        if site["posture"] == "STOP":
            raise_err(ERR_POSTURE_BLOCKED, "site posture is STOP")
        # priority 7: temporal gate
        if now() < parse_dt(task["earliest_start_at"]):
            raise_err(ERR_TRADE_TOO_EARLY, "earliest_start_at has not been reached")
        # priority 8: state
        if task["status"] != "READY":
            raise_err(ERR_INVALID_STATE, "task must be READY to start")
        if not task["is_startable"]:
            raise_err(ERR_INVALID_STATE, "task is not startable")
        task["status"] = "IN_PROGRESS"
        task["actual_start_at"] = fmt_dt(now())
        touch(task)
        return success_object(task)

    if to_state == "COMPLETED":
        if role != "TradeContractor":
            raise_err(ERR_FORBIDDEN, "only TradeContractor may complete a trade task")
        if now() > parse_dt(task["latest_end_at"]):
            raise_err(ERR_TRADE_OVERRUN, "latest_end_at has passed")
        if task["status"] != "IN_PROGRESS":
            raise_err(ERR_INVALID_STATE, "task must be IN_PROGRESS to complete")
        task["status"] = "COMPLETED"
        task["actual_end_at"] = fmt_dt(now())
        touch(task)
        services.reevaluate_trade_tasks(site_id)
        return success_object(task)

    if to_state == "CANCELLED":
        if role != "SiteManager":
            raise_err(ERR_FORBIDDEN, "only SiteManager may cancel a trade task")
        if task["status"] not in ("PLANNED", "READY"):
            raise_err(ERR_INVALID_STATE, "task must be PLANNED or READY to cancel")
        task["status"] = "CANCELLED"
        touch(task)
        services.reevaluate_trade_tasks(site_id)
        return success_object(task)

    raise_err(ERR_INVALID_REQUEST, "unknown to_state %s" % to_state)
