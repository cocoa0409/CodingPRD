"""CostReport endpoints: open-book monthly reporting (PRD 3.8)."""
from flask import Blueprint

import clock
import guards
import lookups
import response as resp
import serializers
import validation as v
from db import db, new_record, sorted_rows, touch
from errors import ApiError
from money import MONEY_ZERO, q2
from middleware import (
    CONSTRUCTION_MANAGER,
    INDEPENDENT_AUDITOR,
    OWNER_REPRESENTATIVE,
    PROGRAM_ADMIN,
    endpoint,
)
from services import derive

bp = Blueprint("cost_reports", __name__)

REPORT_STATUSES = ("OPEN", "RECONCILIATION_HELD", "DISPUTED", "RECONCILED")
DECISIONS = ("RECONCILE", "DISPUTE")
READ_ROLES = (
    CONSTRUCTION_MANAGER,
    OWNER_REPRESENTATIVE,
    INDEPENDENT_AUDITOR,
    PROGRAM_ADMIN,
)


def _state_error(message):
    return ApiError("ERR_COST_REPORT_STATE_INVALID", message)


@bp.route("/cost-reports", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def create_cost_report():
    body = v.json_body()
    project_id = v.get_id(body, "project_id", required=True)
    period_start = v.get_datetime(body, "period_start", required=True)
    period_end = v.get_datetime(body, "period_end", required=True)
    v.require_before(period_start, period_end, "period_start", "period_end")

    project = lookups.project(project_id)
    # The settled-closeout rule owns this operation (PRD 2.11 note); checking the
    # gmp gate first would make ERR_CLOSEOUT_ALREADY_SETTLED unreachable here,
    # because settlement also drives gmp_status to CLOSED.
    guards.require_not_settled(project)
    guards.require_gmp_executed(project)

    for other in derive.project_reports(project["id"]):
        # Half-open intervals: adjacency (start == other end) is not an overlap.
        if period_start < other["period_end"] and other["period_start"] < period_end:
            raise ApiError(
                "ERR_COST_PERIOD_OVERLAP",
                "the reporting period overlaps cost report %s" % other["id"],
            )

    report = new_record({
        "project_id": project["id"],
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "lines": [],
        "line_count": 0,
        "reported_cost_total": MONEY_ZERO,
        "undisputed_cost_total": MONEY_ZERO,
        "disputed_cost_total": MONEY_ZERO,
        "buyout_savings_to_date": MONEY_ZERO,
        "held_reason": None,
        "reconciled_at": None,
        "reconciliation_note": None,
    })
    db.cost_reports[report["id"]] = report
    return resp.created(serializers.cost_report(report))


@bp.route("/cost-reports/<rid>/lines", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def append_line(rid):
    body = v.json_body()
    cost_code = v.get_str(body, "cost_code", required=True, min_len=1, max_len=60)
    quantity = v.get_quantity(body, "quantity", required=True)
    unit_rate = v.get_unit_rate(body, "unit_rate", required=True)
    markup_pct = v.get_ratio(body, "markup_pct", required=True)
    work_package_id = v.get_id(body, "work_package_id", required=False)
    qualification_item_id = v.get_id(body, "qualification_item_id", required=False)
    disputed = v.get_bool(body, "disputed", required=False, default=False)

    report = lookups.cost_report(rid)
    package = None
    item = None
    if work_package_id is not None:
        # PRD 2.9 lists "a cost line's `work_package_id`" among the body
        # identifiers that yield ERR_RESOURCE_NOT_FOUND, carving it out of the
        # general work_package_id -> ERR_WORK_PACKAGE_NOT_FOUND rule.
        package = lookups.resource(db.work_packages, work_package_id, "work package")
    if qualification_item_id is not None:
        item = lookups.qualification_item(qualification_item_id)

    project = lookups.project(report["project_id"])
    if report["status"] not in ("OPEN", "DISPUTED"):
        raise _state_error(
            "report status is %s; appending a line requires OPEN or DISPUTED"
            % report["status"]
        )
    guards.require_not_settled(project)

    if package is not None and package["project_id"] != project["id"]:
        raise ApiError(
            "ERR_CROSS_PROJECT_REFERENCE",
            "work_package_id belongs to a different project",
        )
    if item is not None:
        owner = lookups.project_of_qualification_item(item)
        if owner is None or owner["id"] != project["id"]:
            raise ApiError(
                "ERR_CROSS_PROJECT_REFERENCE",
                "qualification_item_id belongs to a different project",
            )

    # Normative rounding order: the extended amount is rounded per line, before
    # it enters any subtotal (PRD 3.8).
    line_amount = q2(quantity * unit_rate * (1 + markup_pct))
    line = {
        "line_seq": report["line_count"] + 1,
        "cost_code": cost_code,
        "work_package_id": work_package_id,
        "qualification_item_id": qualification_item_id,
        "quantity": quantity,
        "unit_rate": unit_rate,
        "markup_pct": markup_pct,
        "line_amount": line_amount,
        "disputed": disputed,
    }
    report["lines"].append(line)
    derive.recompute_report_totals(report)
    touch(report)
    return resp.created(serializers.cost_report(report))


@bp.route("/cost-reports/<rid>/reconcile", methods=["POST"])
@endpoint(OWNER_REPRESENTATIVE)
def reconcile(rid):
    body = v.json_body()
    decision = v.get_enum(body, "decision", DECISIONS, required=True)
    note = v.get_str(body, "reconciliation_note", required=False, min_len=0)
    report = lookups.cost_report(rid)
    project = lookups.project(report["project_id"])

    if decision == "RECONCILE":
        if report["status"] not in ("OPEN", "DISPUTED"):
            raise _state_error(
                "report status is %s; RECONCILE requires OPEN or DISPUTED"
                % report["status"]
            )
        if report["line_count"] < 1:
            raise _state_error(
                "RECONCILE requires the report to carry at least one cost line"
            )
        report["status"] = "RECONCILED"
        report["reconciled_at"] = clock.now()
    else:
        if report["status"] != "OPEN":
            raise _state_error(
                "report status is %s; DISPUTE requires OPEN" % report["status"]
            )
        if report["disputed_cost_total"] <= MONEY_ZERO:
            raise _state_error(
                "DISPUTE requires disputed_cost_total to be greater than 0.00"
            )
        report["status"] = "DISPUTED"

    if note is not None:
        report["reconciliation_note"] = note
    report["buyout_savings_to_date"] = project["buyout_savings_trade_level"]
    touch(report)
    return resp.ok(serializers.cost_report(report))


@bp.route("/cost-reports/<rid>/release-hold", methods=["POST"])
@endpoint(OWNER_REPRESENTATIVE)
def release_hold(rid):
    body = v.json_body()
    v.get_str(body, "release_note", required=False, min_len=0)
    report = lookups.cost_report(rid)
    project = lookups.project(report["project_id"])
    if report["status"] != "RECONCILIATION_HELD":
        raise _state_error(
            "report status is %s; a release requires RECONCILIATION_HELD"
            % report["status"]
        )
    guards.require_posture_recovered(project)
    report["status"] = "OPEN"
    report["held_reason"] = None
    touch(report)
    return resp.ok(serializers.cost_report(report))


@bp.route("/cost-reports", methods=["GET"])
@endpoint(*READ_ROLES)
def list_cost_reports():
    limit, offset = v.pagination()
    project_id = v.query_filter("project_id")
    status = v.query_filter("status", REPORT_STATUSES)
    rows = []
    for row in db.cost_reports.values():
        if project_id is not None and row["project_id"] != project_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return resp.listing(
        [serializers.cost_report(r) for r in page], limit, offset, total
    )


@bp.route("/cost-reports/<rid>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_cost_report(rid):
    return resp.ok(serializers.cost_report(lookups.cost_report(rid)))
