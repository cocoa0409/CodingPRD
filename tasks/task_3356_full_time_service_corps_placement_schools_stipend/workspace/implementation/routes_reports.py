from datetime import timedelta

from flask import Blueprint

from db import store, new_entity, touch, parse_date, clock_date
from errors import ApiError, bad_request, not_found, invalid_state
from middleware import (auth, body, need, need_str, need_date, forbid_role,
                        not_owner)
from response import ok
from serialize import report_json
import services as svc

bp = Blueprint("reports", __name__)

REPORT_STATES = {"DRAFT", "SUBMITTED", "RETURNED", "ACCEPTED"}


def get_report_or_404(report_id):
    r = store.reports.get(report_id)
    if r is None:
        not_found("EvaluationReport not found")
    return r


@bp.route("/corps/evaluation-reports", methods=["POST"])
def create_report():
    auth(["ProgramManager"])
    data = body()
    school_id = need_str(data, "school_id")
    period_start = need_date(data, "period_start")
    period_end = need_date(data, "period_end")
    if parse_date(period_end) < parse_date(period_start):
        bad_request("period_end must be on or after period_start")
    school = store.schools.get(school_id)
    if school is None:
        not_found("School not found")
    if school["agreement_status"] not in ("ACTIVE", "COMPLETED"):
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409,
                       "School agreement must be ACTIVE or COMPLETED")
    eligible, improved, pct = svc.evaluation_metrics(school_id, period_start,
                                                     period_end)
    r = new_entity({
        "school_id": school_id,
        "period_start": period_start,
        "period_end": period_end,
        "eligible_student_count": eligible,
        "improved_student_count": improved,
        "pct_improved": pct,
        "status": "DRAFT",
        "return_reason": None,
    })
    store.reports[r["id"]] = r
    return ok(report_json(r), 201)


@bp.route("/corps/evaluation-reports/<report_id>/state", methods=["POST"])
def report_state(report_id):
    uid, role = auth(["ProgramManager", "SchoolLiaison"])
    data = body()
    to_status = need(data, "to_status")
    if to_status not in REPORT_STATES:
        bad_request("to_status must be a valid EvaluationReport status")
    return_reason = data.get("return_reason")
    if to_status == "RETURNED":
        if return_reason is None or not isinstance(return_reason, str) \
                or not return_reason.strip():
            bad_request("return_reason is required for RETURNED")
    elif return_reason is not None and not isinstance(return_reason, str):
        bad_request("return_reason must be a string")
    r = get_report_or_404(report_id)
    school = store.schools.get(r["school_id"])

    if to_status == "SUBMITTED":
        if role != "ProgramManager":
            forbid_role("Only a ProgramManager submits reports")
        if r["status"] not in ("DRAFT", "RETURNED"):
            invalid_state("Report in %s cannot be submitted" % r["status"])
        # Temporal window (priority 15) precedes the data-sharing gate (17).
        if clock_date() > parse_date(r["period_end"]) + timedelta(days=45):
            raise ApiError("ERR_REPORT_WINDOW_CLOSED", 422,
                           "Report submission window has closed")
        if school is None or school["data_sharing_status"] != "SIGNED":
            raise ApiError("ERR_DATA_SHARING_NOT_SIGNED", 409,
                           "School data-sharing agreement is not SIGNED")
        r["status"] = "SUBMITTED"
        r["return_reason"] = None
    elif to_status in ("ACCEPTED", "RETURNED"):
        if role != "SchoolLiaison":
            forbid_role("Only the SchoolLiaison reviews reports")
        if uid != r["school_id"]:
            not_owner("SchoolLiaison may only review their own school's reports")
        if r["status"] != "SUBMITTED":
            invalid_state("Report in %s cannot transition to %s"
                          % (r["status"], to_status))
        if to_status == "ACCEPTED":
            r["status"] = "ACCEPTED"
        else:
            r["status"] = "RETURNED"
            r["return_reason"] = return_reason
    else:
        invalid_state("Report status %s cannot transition to %s"
                      % (r["status"], to_status))
    touch(r)
    return ok(report_json(r), 200)
