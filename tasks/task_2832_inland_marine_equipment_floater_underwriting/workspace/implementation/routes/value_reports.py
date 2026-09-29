from flask import Blueprint

import cascades
import rating
import store
import views
from common import (API_PREFIX, envelope_list, envelope_object, fail, paginate,
                    parse_pagination, require)

bp = Blueprint("value_reports", __name__)

REPORT = "/value-reports/<report_id>"


def _report(report_id):
    return store.find(store.value_reports, report_id, "ERR_VALUE_REPORT_NOT_FOUND")


@bp.get(API_PREFIX + REPORT)
def get_report(report_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster", "Policyholder")
    report = _report(report_id)
    return envelope_object(views.report_view(report), 200)


@bp.get(API_PREFIX + REPORT + "/superseded-reports")
def list_superseded(report_id):
    require("Underwriter", "UnderwritingManager", "Policyholder")
    _report(report_id)
    limit, offset = parse_pagination()
    rows = store.order([r for r in store.value_reports.values()
                        if r.get("superseded_by_report_id") == report_id])
    page, total = paginate(rows, limit, offset)
    return envelope_list([views.report_view(r) for r in page], limit, offset, total)


@bp.post(API_PREFIX + REPORT + "/adjudicate")
def adjudicate_report(report_id):
    require("Underwriter")
    report = _report(report_id)
    if report["status"] != "SUBMITTED":
        fail("ERR_REPORT_ALREADY_ADJUDICATED", "Report is %s" % report["status"])
    part = store.coverage_parts[report["coverage_part_id"]]
    policy = store.policies[part["policy_id"]]
    premium = rating.reporting_period_earned_premium(
        report["reported_value_cents"], part["reporting_annual_rate_bp"] or 0,
        report["period_days"])
    late = report["submitted_at"].date() > report["due_date"]
    report["period_earned_premium_cents"] = premium
    if late:
        penalty = rating.reporting_late_penalty(premium)
        report["late_penalty_cents"] = penalty
        report["status"] = "PENALIZED"
    else:
        penalty = 0
        report["late_penalty_cents"] = 0
        report["status"] = "ACCEPTED"
    store.touch(report)
    store.append_entry(policy["id"], "REPORTING_ADJUSTMENT", premium,
                       "Reporting adjustment for value report %s" % report["id"])
    if late:
        store.append_entry(policy["id"], "LATE_REPORTING_PENALTY", penalty,
                           "Late reporting penalty on value report %s" % report["id"])
    # earned_reported_premium_cents is derived from the ACCEPTED/PENALIZED reports
    # on the part, so the part row only needs its updated_at refreshed.
    store.touch(part)
    for sibling in store.reports_of_part(part["id"]):
        if sibling["id"] == report["id"]:
            continue
        if sibling["status"] not in ("SUBMITTED", "DELINQUENT"):
            continue
        if (sibling["period_start_date"] != report["period_start_date"]
                or sibling["period_end_date"] != report["period_end_date"]):
            continue
        sibling["status"] = "SUPERSEDED"
        sibling["superseded_by_report_id"] = report["id"]
        store.touch(sibling)
    cascades.cure_delinquency(policy)
    return envelope_object(views.report_view(report), 200)
