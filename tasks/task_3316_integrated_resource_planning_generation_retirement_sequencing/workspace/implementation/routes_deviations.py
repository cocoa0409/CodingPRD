"""PlanDeviationReport routes."""

from flask import Blueprint, request

from calculations import compute_deviation_report
from db import store
from errors import (
    ERR_DUPLICATE_REPORT, ERR_INVALID_REQUEST, ERR_PLAN_NOT_APPROVED,
    ERR_PLAN_NOT_FOUND, raise_error,
)
from helpers import (
    body, get_int, get_num, paginate, parse_pagination, require_fields,
    stamp_new,
)
from middleware import require_roles
from response import success_list, success_object
from routes_plans import get_plan_or_404
from serializers import deviation_report_view

bp = Blueprint("deviation_reports", __name__)

REPORT_ROLES = ("UtilityPlanner", "Commissioner", "Intervener", "PlatformAdmin")
ERR_REPORT_NOT_FOUND = ("ERR_PLAN_NOT_FOUND", 404)  # no dedicated id in catalog


def get_report_or_404(report_id: str) -> dict:
    r = store.deviation_reports.get(report_id)
    if r is None:
        raise_error(ERR_REPORT_NOT_FOUND, f"Deviation report {report_id} not found")
    return r


@bp.route("/plans/<planId>/deviation-reports", methods=["POST"])
@require_roles("UtilityPlanner")
def create_deviation_report(user_id, role, planId):
    plan = get_plan_or_404(planId)
    payload = body()
    require_fields(payload, "report_year", "actual_load_mw")
    report_year = get_int(payload, "report_year")
    actual = get_num(payload, "actual_load_mw")
    if actual < 0:
        raise_error(ERR_INVALID_REQUEST, "actual_load_mw must be >= 0")
    # State gate (priority 5).
    if plan["status"] not in ("APPROVED", "APPROVED_WITH_CONDITIONS"):
        raise_error(ERR_PLAN_NOT_APPROVED, "Plan is not approved")
    # Uniqueness (priority 7).
    for r in store.deviation_reports.values():
        if r["plan_id"] == plan["id"] and r["report_year"] == report_year:
            raise_error(ERR_DUPLICATE_REPORT,
                        "Report for (plan, report_year) already exists")
    computed = compute_deviation_report(plan, report_year, actual)
    r = stamp_new({
        "plan_id": plan["id"],
        "report_year": report_year,
        "actual_load_mw": actual,
        **computed,
    }, with_version=False)
    store.deviation_reports[r["id"]] = r
    return success_object(deviation_report_view(r), 201)


@bp.route("/plans/<planId>/deviation-reports", methods=["GET"])
@require_roles(*REPORT_ROLES)
def list_plan_reports(user_id, role, planId):
    plan = get_plan_or_404(planId)
    limit, offset = parse_pagination()
    items = [r for r in store.deviation_reports.values() if r["plan_id"] == plan["id"]]
    page, total = paginate(items, limit, offset)
    return success_list([deviation_report_view(r) for r in page], limit, offset, total)


@bp.route("/deviation-reports", methods=["GET"])
@require_roles(*REPORT_ROLES)
def list_reports_flat(user_id, role):
    limit, offset = parse_pagination()
    items = list(store.deviation_reports.values())
    if "plan_id" in request.args:
        items = [r for r in items if r["plan_id"] == request.args["plan_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([deviation_report_view(r) for r in page], limit, offset, total)


@bp.route("/deviation-reports/<reportId>", methods=["GET"])
@require_roles(*REPORT_ROLES)
def get_report(user_id, role, reportId):
    r = get_report_or_404(report_id)
    return success_object(deviation_report_view(r), 200)
