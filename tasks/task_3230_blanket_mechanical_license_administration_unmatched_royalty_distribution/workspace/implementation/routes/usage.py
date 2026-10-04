"""UsageReport + UsageLine endpoints."""
import re
from datetime import timezone

from flask import Blueprint, request

import db
from auth import require_roles
from calc import (schedule_for_month, line_royalty_cents, deterministic_match,
                  spawn_accrual)
from errors import err
from lookups import get_sp, get_report, get_line, check_child
from postings import recompute_report_totals, queue_matched_postings
from response import ok_list, ok_object
from util import body_json, make_record, touch, month_bounds, parse_iso

bp = Blueprint("usage", __name__)

SP_WRITE = ("ServiceProviderUser", "MLCAdministrator")
SP_USER = ("ServiceProviderUser",)
ADMIN = ("MLCAdministrator",)
READ = ("MLCAdministrator", "ServiceProviderUser")
LINE_READ = ("MLCAdministrator", "ServiceProviderUser", "MemberUser")

ISRC_RE = re.compile(r"^[A-Za-z]{2}[A-Za-z0-9]{3}[0-9]{7}$")


def report_view(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def line_view(l):
    return {k: v for k, v in l.items() if not k.startswith("_")}


def accrual_view(a):
    return {k: v for k, v in a.items() if not k.startswith("_")}


def _month_fully_elapsed(reporting_month):
    _, month_end = month_bounds(reporting_month)
    return month_end < db.now()


def _get_report_scoped(sp_id, report_id):
    sp = get_sp(sp_id)
    r = get_report(report_id)
    check_child(r, "service_provider_id", sp_id, "ERR_USAGE_REPORT_NOT_FOUND")
    return sp, r


@bp.route("/mlc/service-providers/<sp_id>/usage-reports", methods=["POST"])
@require_roles(*SP_WRITE)
def create_report(sp_id, _user_id, _role):
    sp = get_sp(sp_id)
    body = body_json(required=("reporting_month",))
    rm = body["reporting_month"]
    month_bounds(rm)  # validates format
    if sp["participation_status"] != "ACTIVE":
        raise err("ERR_DSP_NOT_ACTIVE")
    if not _month_fully_elapsed(rm):
        raise err("ERR_FUTURE_PERIOD")
    rec = make_record()
    rec.update({
        "service_provider_id": sp_id,
        "reporting_month": rm,
        "status": "DRAFT",
        "accepted_rate_schedule_version": None,
        "total_usage_cents": 0,
        "matched_usage_cents": 0,
        "unmatched_usage_cents": 0,
        "payment_due_at": None,
    })
    db.usage_reports[rec["id"]] = rec
    return ok_object(report_view(rec), 201)


@bp.route("/mlc/service-providers/<sp_id>/usage-reports/<report_id>", methods=["GET"])
@require_roles(*READ)
def get_one_report(sp_id, report_id, _user_id, _role):
    _, r = _get_report_scoped(sp_id, report_id)
    return ok_object(report_view(r))


@bp.route("/mlc/service-providers/<sp_id>/usage-reports/<report_id>/lines",
          methods=["POST"])
@require_roles(*SP_WRITE)
def add_line(sp_id, report_id, _user_id, _role):
    sp, r = _get_report_scoped(sp_id, report_id)
    body = body_json(required=("isrc", "track_title", "plays_count", "duration_seconds"))
    if r["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE")
    if not ISRC_RE.match(str(body["isrc"])):
        raise err("ERR_INVALID_REQUEST", "isrc must be 12 chars: 2 letters, 3 alphanumeric, 7 digits")
    plays = body["plays_count"]
    dur = body["duration_seconds"]
    if not isinstance(plays, int) or plays <= 0:
        raise err("ERR_INVALID_REQUEST", "plays_count must be > 0")
    if not isinstance(dur, int) or dur <= 0:
        raise err("ERR_INVALID_REQUEST", "duration_seconds must be > 0")
    sched = schedule_for_month(r["reporting_month"])
    royalties = line_royalty_cents(sched, plays, dur)
    rec = make_record()
    rec.update({
        "report_id": report_id,
        "isrc": body["isrc"],
        "track_title": body["track_title"],
        "plays_count": plays,
        "duration_seconds": dur,
        "royalties_cents": royalties,
        "status": "PENDING_MATCH",
        "matched_work_id": None,
    })
    db.usage_lines[rec["id"]] = rec
    touch(r)
    return ok_object(line_view(rec), 201)


@bp.route("/mlc/service-providers/<sp_id>/usage-reports/<report_id>/lines",
          methods=["GET"])
@require_roles(*READ)
def list_lines(sp_id, report_id, _user_id, _role):
    _get_report_scoped(sp_id, report_id)
    items = sorted(
        (l for l in db.usage_lines.values() if l["report_id"] == report_id),
        key=lambda l: l["created_at"])
    status = request.args.get("status")
    if status:
        items = [l for l in items if l["status"] == status]
    return ok_list([line_view(l) for l in items])


@bp.route("/mlc/usage-lines/<line_id>", methods=["GET"])
@require_roles(*LINE_READ)
def get_one_line(line_id, _user_id, _role):
    return ok_object(line_view(get_line(line_id)))


@bp.route("/mlc/usage-lines", methods=["GET"])
@require_roles(*LINE_READ)
def list_lines_flat(_user_id, _role):
    items = sorted(db.usage_lines.values(), key=lambda l: l["created_at"])
    for field in ("matched_work_id", "status", "report_id"):
        v = request.args.get(field)
        if v:
            items = [l for l in items if l.get(field) == v]
    return ok_list([line_view(l) for l in items])


@bp.route("/mlc/usage-lines/<line_id>/accruals", methods=["GET"])
@require_roles("MLCAdministrator", "MemberUser", "PublicSearcher")
def list_line_accruals(line_id, _user_id, _role):
    get_line(line_id)
    items = sorted(
        (a for a in db.accruals.values() if a["usage_line_id"] == line_id),
        key=lambda a: a["created_at"])
    return ok_list([accrual_view(a) for a in items])


@bp.route("/mlc/service-providers/<sp_id>/usage-reports/<report_id>/submit",
          methods=["POST"])
@require_roles(*SP_USER)
def submit_report(sp_id, report_id, _user_id, _role):
    sp, r = _get_report_scoped(sp_id, report_id)
    body = body_json(required=("accepted_rate_schedule_version",))
    if r["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE")
    if sp["participation_status"] != "ACTIVE":
        raise err("ERR_DSP_NOT_ACTIVE")
    lines = [l for l in db.usage_lines.values() if l["report_id"] == report_id]
    if not lines:
        raise err("ERR_EMPTY_REPORT")
    if not _month_fully_elapsed(r["reporting_month"]):
        raise err("ERR_FUTURE_PERIOD")
    if body["accepted_rate_schedule_version"] != sp["accepted_rate_schedule_version"]:
        raise err("ERR_STALE_RATE_SCHEDULE")
    recompute_report_totals(r)
    r["status"] = "SUBMITTED"
    touch(r)
    touch(sp)
    return ok_object(report_view(r))


def _acceptance_match_sweep(r, sp):
    """Run the match sweep over PENDING_MATCH lines at acceptance.
    Returns (matched_cents, unmatched_cents)."""
    matched = 0
    unmatched = 0
    lines = sorted(
        (l for l in db.usage_lines.values()
         if l["report_id"] == r["id"] and l["status"] == "PENDING_MATCH"),
        key=lambda l: l["created_at"])
    for line in lines:
        work = deterministic_match(line)
        if work is not None:
            line["status"] = "MATCHED"
            line["matched_work_id"] = work["id"]
            work["match_run_count"] += 1
            touch(work)
            touch(line)
            queue_matched_postings(line, r, "MATCHED_EARNINGS")
            matched += line["royalties_cents"]
        else:
            line["status"] = "UNMATCHED"
            touch(line)
            spawn_accrual(line, r, sp)
            unmatched += line["royalties_cents"]
    return matched, unmatched


@bp.route("/mlc/service-providers/<sp_id>/usage-reports/<report_id>/accept",
          methods=["POST"])
@require_roles(*ADMIN)
def accept_report(sp_id, report_id, _user_id, _role):
    sp, r = _get_report_scoped(sp_id, report_id)
    body = body_json(required=("accepted_rate_schedule_version",))
    if r["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE")
    if body["accepted_rate_schedule_version"] != sp["accepted_rate_schedule_version"]:
        raise err("ERR_STALE_RATE_SCHEDULE")
    # In-order acceptance: no earlier reporting_month still SUBMITTED
    earlier = any(
        other["service_provider_id"] == sp_id
        and other["id"] != report_id
        and other["status"] == "SUBMITTED"
        and other["reporting_month"] < r["reporting_month"]
        for other in db.usage_reports.values())
    if earlier:
        raise err("ERR_OUT_OF_ORDER_ACCEPTANCE")
    matched, unmatched = _acceptance_match_sweep(r, sp)
    total = sum(
        l["royalties_cents"] for l in db.usage_lines.values()
        if l["report_id"] == report_id)
    # Data-quality circuit breaker: unmatched*100 > 60*total -> reject
    if unmatched * 100 > 60 * total:
        raise err("ERR_MATCH_RATE_FLOOR_BREACH")
    r["matched_usage_cents"] = matched
    r["unmatched_usage_cents"] = unmatched
    r["total_usage_cents"] = total
    r["accepted_rate_schedule_version"] = sp["accepted_rate_schedule_version"]
    # payment_due_at = 15th of month following reporting month, 00:00:00Z
    month_start, month_end = month_bounds(r["reporting_month"])
    due = month_end.replace(day=15)
    r["payment_due_at"] = due.strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"
    r["status"] = "ACCEPTED"
    touch(r)
    sp["audit_credits"] += 1
    touch(sp)
    return ok_object(report_view(r))


@bp.route("/mlc/service-providers/<sp_id>/usage-reports/<report_id>/reject",
          methods=["POST"])
@require_roles(*ADMIN)
def reject_report(sp_id, report_id, _user_id, _role):
    sp, r = _get_report_scoped(sp_id, report_id)
    body_json()
    if r["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE")
    r["status"] = "REJECTED"
    touch(r)
    return ok_object(report_view(r))


@bp.route("/mlc/service-providers/<sp_id>/usage-reports/<report_id>/reopen",
          methods=["POST"])
@require_roles(*SP_USER)
def reopen_report(sp_id, report_id, _user_id, _role):
    sp, r = _get_report_scoped(sp_id, report_id)
    body_json()
    if r["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE")
    # Re-derive line pricing under the rules (reporting month window)
    sched = schedule_for_month(r["reporting_month"])
    for line in db.usage_lines.values():
        if line["report_id"] == report_id:
            line["royalties_cents"] = line_royalty_cents(
                sched, line["plays_count"], line["duration_seconds"])
            touch(line)
    r["status"] = "DRAFT"
    touch(r)
    return ok_object(report_view(r))
