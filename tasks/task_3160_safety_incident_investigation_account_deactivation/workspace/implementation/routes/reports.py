"""Regulator reports: queueing, rollup, the filing window and the publication attempt."""

from flask import Blueprint, request

from db import STORE, add_days, now
from calculations import (graduated_rollup, regulator_report_required)
from errors import ApiError, ERR_INVALID_STATE, ERR_REGULATOR_REPORT_BLOCKED, ERR_RESOURCE_NOT_FOUND
from middleware import (assert_version_matches, body, new_id, require_version, route,
                        stamp, touch)
from response import created, read_pagination, success, success_list
from serializers import regulator_report as serialize_report
from serializers import render_mapping
from services import common

bp = Blueprint("reports", __name__)

_READ_ROLES = ("PlatformAdmin", "RegulatorLiaison", "SafetyOperationsLead")


def get_report(report_id):
    report = STORE.regulator_reports.get(report_id)
    if report is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such regulator report: %s" % report_id)
    return report


@bp.route("/safety/regulator-reports", methods=["POST"])
@route("RegulatorLiaison")
def create_report(ident):
    payload = body()
    incident = STORE.incidents.get(payload.get("incident_id"))
    if incident is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such incident: %s" % payload.get("incident_id"))
    account = STORE.accounts.get(incident.get("account_id")) or {}
    region_code = account.get("home_region_code")

    # The decision cascade files through the report already queued for the
    # incident; queueing a second one for the same channel is a no-op.
    for existing in STORE.reports_for_incident(incident.get("id")):
        if existing.get("report_channel") == payload.get("report_channel"):
            return created(serialize_report(existing))

    # A report whose ALWAYS_LAW_ENFORCEMENT window block is not yet open lands
    # at BLOCKED rather than BACKLOG.
    if common.regulator_window_is_blocked(region_code):
        report_status = "BLOCKED"
    else:
        report_status = "BACKLOG"

    report = {
        "id": new_id(),
        "incident_id": incident.get("id"),
        "region_code": region_code,
        "report_channel": payload.get("report_channel"),
        "filing_basis": payload.get("filing_basis"),
        "filed_at": None,
        "report_status": report_status,
        "_window_index": 0,
    }
    stamp(report)
    STORE.regulator_reports[report["id"]] = report
    return created(serialize_report(report))


@bp.route("/safety/regulator-reports", methods=["GET"])
@route(*_READ_ROLES)
def list_reports(ident):
    limit, offset = read_pagination(request.args)
    items = list(STORE.regulator_reports.values())

    def keep(report):
        for field in ("incident_id", "report_status"):
            wanted = request.args.get(field)
            if wanted is not None and report.get(field) != wanted:
                return False
        return True

    items = [r for r in items if keep(r)]
    items.sort(key=lambda r: (r.get("created_at"), r.get("id") or ""))
    return success_list([serialize_report(r) for r in items], limit, offset)


@bp.route("/safety/regulator-reports/<report_id>", methods=["GET"])
@route(*_READ_ROLES)
def get_one_report(ident, report_id):
    return success(serialize_report(get_report(report_id)))


@bp.route("/safety/regulator-reports/rollup-sweep", methods=["POST"])
@route("RegulatorLiaison")
def rollup_sweep(ident):
    payload = body()
    incident = STORE.incidents.get(payload.get("incident_id"))
    if incident is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such incident: %s" % payload.get("incident_id"))
    account = STORE.accounts.get(incident.get("account_id"))
    if account is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND, message="No such account.")

    produced = _run_rollup(incident, account)
    return success_list([serialize_report(r) for r in produced], 100, 0)


def _run_rollup(incident, account):
    from services.regulator import run_rollup
    return run_rollup(incident, account)


@bp.route("/safety/regulator-reports/window-open", methods=["POST"])
@route("RegulatorLiaison")
def window_open(ident):
    payload = body()
    report_id = payload.get("report_id")
    report = STORE.regulator_reports.get(report_id) if report_id else None
    if report is None:
        # The report is addressed through the version expectation's parent when
        # no explicit identifier is supplied.
        candidates = [r for r in STORE.regulator_reports.values()
                      if r.get("report_status") == "BLOCKED"]
        candidates.sort(key=lambda r: (r.get("created_at"), r.get("id") or ""))
        report = candidates[0] if candidates else None
    if report is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No regulator report is awaiting its filing window.")

    require_version(payload, "expected_report_version")
    assert_version_matches(payload, "expected_report_version", report, "RegulatorReport")

    # The region's blocked window closes: the report files retroactively, the
    # incident returns to PENDING_DECISION and the DRAFT action moves up.
    common.close_regulator_windows(report.get("region_code"))

    if report.get("report_status") == "BLOCKED":
        report["report_status"] = "FILED"
        report["filed_at"] = now()
        incident = STORE.incidents.get(report.get("incident_id"))
        if incident is not None and incident.get("incident_status") == "MANDATORY_REPORTED_BLOCKED":
            incident["incident_status"] = "PENDING_DECISION"
            touch(incident)
            account = STORE.accounts.get(incident.get("account_id"))
            if account is not None:
                account["status"] = "PENDING_DECISION"
                common.refresh_account(account)
        action = STORE.action_for_incident(report.get("incident_id"))
        if action is not None and action.get("enforcement_status") == "DRAFT":
            action["enforcement_status"] = "MANDATORY_REPORTED"
            touch(action)
            account = STORE.accounts.get(action.get("account_id"))
            if account is not None:
                account["standing_enforcement_count"] = (
                    account.get("standing_enforcement_count") or 0) + 1
                common.refresh_account(account)
    touch(report)
    return success(serialize_report(report))


@bp.route("/safety/regulator-reports/attempt", methods=["POST"])
@route("RegulatorLiaison")
def attempt(ident):
    payload = body()
    report_id = payload.get("report_id")
    report = STORE.regulator_reports.get(report_id)
    if report is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such regulator report: %s" % report_id)

    if report.get("report_status") == "BLOCKED":
        raise ApiError(*ERR_REGULATOR_REPORT_BLOCKED,
                       message="The report still sits inside an active regulator window "
                               "block.")

    try:
        window_index = int(payload.get("window_index") or 0)
    except (TypeError, ValueError):
        window_index = 0

    incident = STORE.incidents.get(report.get("incident_id")) or {}
    account = STORE.accounts.get(incident.get("account_id"))
    rollup = graduated_rollup(incident.get("account_id"))

    published_at = add_days(report.get("created_at"), window_index * 365)
    included = True
    dropped_reason = None

    if account is not None and account.get("status") == "APPEAL_PENDING" \
            and report.get("report_status") == "FILED":
        if now() >= add_days(report.get("filed_at") or report.get("created_at"), 365):
            included = False
            dropped_reason = "REINSTATED_AFTER_365_DAYS"
            account["status"] = "REINSTATED"
            common.refresh_account(account)

    report["_window_index"] = window_index
    touch(report)

    return success(render_mapping({
        "incident_id": report.get("incident_id"),
        "window_index": window_index,
        "included": included,
        "dropped_reason": dropped_reason,
        "published_at": published_at,
        "rollup": rollup,
    }))