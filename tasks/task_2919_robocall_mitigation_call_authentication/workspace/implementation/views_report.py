"""Mitigation effectiveness reporting (PRD 3.9)."""
from flask import Blueprint

import auth
import calc
import derive
import envelope
import errors
import ser
import store
import valid
from store import db, touch
from views_provider import load_provider

bp = Blueprint("reports", __name__)

VARIANTS = ("PROVISIONAL", "CERTIFIED")
STATES = ("GENERATED", "SIGNED_OFF", "FILED", "SUPERSEDED")
SUPERSEDABLE = ("GENERATED", "SIGNED_OFF")

READ_ROLES = (auth.REGULATOR, auth.COMPLIANCE_OFFICER, auth.PROVIDER_ADMIN)


def load_report(report_id):
    row = db.reports.get(report_id)
    if row is None:
        errors.fail(errors.ERR_REPORT_NOT_FOUND,
                    "No effectiveness report with id %s" % report_id)
    return row


def _in_period(moment, start, end):
    return moment is not None and start <= moment < end


def gather_counts(provider_id, start, end):
    now = db.now()
    attestations = [r for r in db.attestations.values()
                    if r["provider_id"] == provider_id
                    and _in_period(r["origination_time"], start, end)]
    tracebacks = [r for r in db.tracebacks.values()
                  if r["provider_id"] == provider_id
                  and _in_period(r["received_at"], start, end)]
    notices = [r for r in db.notices.values()
               if r["provider_id"] == provider_id
               and _in_period(r["notified_at"], start, end)]
    return {
        "signed_call_count": len(attestations),
        "attestation_a_count": len([
            r for r in attestations if r["attestation_level"] == "A"]),
        "traceback_total_count": len(tracebacks),
        "traceback_on_time_count": len([
            r for r in tracebacks if r["state"] == "RESPONDED"]),
        "traceback_pending_count": len([
            r for r in tracebacks
            if r["state"] == "RECEIVED"
            and r["response_deadline_at"] >= now]),
        "notice_total_count": len(notices),
        "notice_mitigated_count": len([
            r for r in notices
            if r["state"] in ("MITIGATED", "ALL_TRAFFIC_BLOCKED")]),
        "notice_open_count": len([
            r for r in notices
            if r["state"] in ("NOTIFIED", "UNDER_INVESTIGATION")
            and r["mitigation_deadline_at"] >= now]),
    }


def compute_report(row):
    counts = gather_counts(row["provider_id"], row["period_start"],
                           row["period_end"])
    scores = calc.effectiveness(
        row["variant"], counts["signed_call_count"],
        counts["attestation_a_count"], counts["traceback_total_count"],
        counts["traceback_on_time_count"], counts["traceback_pending_count"],
        counts["notice_total_count"], counts["notice_mitigated_count"],
        counts["notice_open_count"])
    row.update(counts)
    row.update(scores)


@bp.route("/rmd/effectiveness-reports", methods=["POST"])
@auth.require(auth.COMPLIANCE_OFFICER)
def generate_report():
    data = valid.body()
    provider_id = valid.req_str(data, "provider_id")
    period_start, raw_start = valid.req_dt(data, "period_start")
    period_end, raw_end = valid.req_dt(data, "period_end")
    variant = valid.req_enum(data, "variant", VARIANTS)
    expected = valid.req_int(data, "expected_provider_version")
    valid.check_interval(period_start, period_end)
    provider = load_provider(provider_id)
    if expected != provider["version"]:
        errors.fail(errors.ERR_STALE_PROVIDER_VERSION,
                    "expected_provider_version does not match the provider")
    if period_end > db.now():
        errors.fail(errors.ERR_REPORT_PERIOD_NOT_ELAPSED,
                    "period_end lies after the current logical clock")

    for other in store.order_rows(list(db.reports.values())):
        if other["provider_id"] != provider_id:
            continue
        if other["state"] not in SUPERSEDABLE:
            continue
        if (period_start < other["period_end"]
                and other["period_start"] < period_end):
            other["state"] = "SUPERSEDED"
            touch(other)

    row = store.base_row()
    row.update({
        "provider_id": provider_id,
        "period_start": period_start,
        "period_end": period_end,
        "variant": variant,
        "state": "GENERATED",
        "signed_off_by_user_id": None,
        "signed_off_at": None,
        "filed_at": None,
    })
    store.remember_raw(row, "period_start", raw_start)
    store.remember_raw(row, "period_end", raw_end)
    compute_report(row)
    db.reports[row["id"]] = row
    return envelope.created(ser.report(row))


@bp.route("/rmd/effectiveness-reports/<report_id>/certify", methods=["POST"])
@auth.require(auth.COMPLIANCE_OFFICER)
def certify_report(report_id):
    row = load_report(report_id)
    plan = derive.operative_plan(row["provider_id"])
    if plan is not None and auth.acting_id() == plan["filed_by_user_id"]:
        errors.fail(errors.ERR_SEGREGATION_OF_DUTIES,
                    "The officer who filed the operative plan may not sign "
                    "off this report")
    if plan is None or plan["filing_state"] != "ACCEPTED":
        errors.fail(errors.ERR_PLAN_STATE_INVALID,
                    "The provider's operative mitigation plan is not ACCEPTED")
    if row["state"] != "GENERATED":
        errors.fail(errors.ERR_REPORT_STATE_INVALID,
                    "Only a GENERATED report can be certified")

    row["state"] = "SIGNED_OFF"
    row["variant"] = "CERTIFIED"
    row["signed_off_by_user_id"] = auth.acting_id()
    row["signed_off_at"] = db.now()
    compute_report(row)
    touch(row)
    return envelope.ok(ser.report(row))


@bp.route("/rmd/effectiveness-reports/<report_id>/file", methods=["POST"])
@auth.require(auth.COMPLIANCE_OFFICER)
def file_report(report_id):
    row = load_report(report_id)
    if row["state"] != "SIGNED_OFF":
        errors.fail(errors.ERR_REPORT_STATE_INVALID,
                    "Only a SIGNED_OFF report can be filed")
    row["state"] = "FILED"
    row["filed_at"] = db.now()
    touch(row)
    return envelope.ok(ser.report(row))


@bp.route("/rmd/effectiveness-reports/<report_id>", methods=["GET"])
@auth.require(*READ_ROLES)
def read_report(report_id):
    row = load_report(report_id)
    auth.own_provider(row["provider_id"])
    return envelope.ok(ser.report(row))


@bp.route("/rmd/effectiveness-reports", methods=["GET"])
@auth.require(*READ_ROLES)
def list_reports():
    limit, offset = envelope.pagination()
    provider_id = valid.arg_str("provider_id")
    state = valid.arg_enum("state", STATES)
    variant = valid.arg_enum("variant", VARIANTS)

    rows = auth.scope_rows(db.reports.values(),
                           provider_of=lambda r: r["provider_id"])
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if variant is not None:
        rows = [r for r in rows if r["variant"] == variant]
    return envelope.collection(rows, ser.report, limit, offset)
