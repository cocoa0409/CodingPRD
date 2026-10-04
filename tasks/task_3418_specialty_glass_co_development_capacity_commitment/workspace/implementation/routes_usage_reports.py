"""UsageReport endpoints: submit (per-line-round provisional), get, list,
accept (sum-then-round final), dispute."""
from flask import Blueprint, request

import serializers
import store
from calculations import (
    royalty_final_cents,
    royalty_provisional_cents,
    royalty_rate,
)
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_IP_LITIGATION_HOLD,
    ERR_MARKETING_NOT_APPROVED,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_REPORT_PERIOD_OVERLAP,
)
from response import success_list, success_object
from validation import (
    ALL_ROLES,
    ROLE_DEVICE_MAKER,
    ROLE_FINANCE_CONTROLLER,
    authenticate,
    get_body,
    req_field,
    as_str,
    as_int,
    as_enum,
    as_datetime,
    pagination_args,
)

bp = Blueprint("usage_reports", __name__)

CHANNELS = {"DOMESTIC", "EXPORT"}


def _get_report_or_404(report_id):
    report = store.usage_reports.get(report_id)
    if report is None:
        raise ApiError(ERR_NOT_FOUND, "Usage report not found")
    return report


@bp.route("/glass/usage-reports", methods=["POST"])
def create_usage_report():
    user_id = authenticate({ROLE_DEVICE_MAKER})
    body = get_body()
    license_id = as_str(req_field(body, "license_id"), "license_id")
    period_start = as_datetime(req_field(body, "period_start"), "period_start")
    period_end = as_datetime(req_field(body, "period_end"), "period_end")
    # Closed interval, inclusive at both ends, end strictly after start.
    if period_end <= period_start:
        raise ApiError(
            ERR_INVALID_REQUEST, "period_end must be strictly after period_start"
        )
    raw_lines = req_field(body, "lines")
    if not isinstance(raw_lines, list) or len(raw_lines) == 0:
        raise ApiError(ERR_INVALID_REQUEST, "lines must be a non-empty array")
    lines = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            raise ApiError(ERR_INVALID_REQUEST, "each line must be an object")
        channel = as_enum(req_field(raw, "channel"), "channel", CHANNELS)
        units = as_int(req_field(raw, "units"), "units")
        revenue = as_int(req_field(raw, "net_revenue_cents"), "net_revenue_cents")
        if units <= 0:
            raise ApiError(ERR_INVALID_REQUEST, "line units must be strictly positive")
        if revenue < 0:
            raise ApiError(
                ERR_INVALID_REQUEST, "line net_revenue_cents must be zero or more"
            )
        lines.append(
            {"channel": channel, "units": units, "net_revenue_cents": revenue}
        )
    lic = store.licenses.get(license_id)
    if lic is None:
        raise ApiError(ERR_NOT_FOUND, "License not found")
    # Priority 5: ownership — caller is the licensee.
    if user_id != lic["device_maker_id"]:
        raise ApiError(ERR_OWNERSHIP_MISMATCH, "Caller is not the licensee")
    # Priority 6: creation-time state gate on the referenced license.
    if lic["license_status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "License must be ACTIVE or SUSPENDED")
    # Priority 9: IP litigation hold on the license's maker.
    maker = store.device_makers[lic["device_maker_id"]]
    if maker["ip_review_status"] == "CONFIRMED_INFRINGEMENT":
        raise ApiError(ERR_IP_LITIGATION_HOLD, "Device maker under IP litigation hold")
    # Priority 16: one live report per period; DISPUTED/HELD are superseded.
    for rep in store.usage_reports.values():
        if rep["license_id"] != lic["id"]:
            continue
        if rep["status"] not in ("SUBMITTED", "ACCEPTED"):
            continue
        if period_start <= rep["period_end"] and rep["period_start"] <= period_end:
            raise ApiError(
                ERR_REPORT_PERIOD_OVERLAP,
                "Period overlaps an existing SUBMITTED or ACCEPTED report",
            )
    total_units = sum(l["units"] for l in lines)
    rate = royalty_rate(total_units)
    report = store.base_fields()
    report.update(
        {
            "license_id": lic["id"],
            "period_start": period_start,
            "period_end": period_end,
            "lines": lines,
            "status": "SUBMITTED",
            "royalty_rate_applied": rate,
            "provisional_royalty_cents": royalty_provisional_cents(lines, rate),
            "final_royalty_cents": None,
        }
    )
    store.usage_reports[report["id"]] = report
    return success_object(serializers.usage_report(report), status=201)


@bp.route("/glass/usage-reports/<usageReportId>", methods=["GET"])
def get_usage_report(usageReportId):
    authenticate(ALL_ROLES)
    return success_object(serializers.usage_report(_get_report_or_404(usageReportId)))


@bp.route("/glass/usage-reports", methods=["GET"])
def list_usage_reports():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    f_license = request.args.get("license_id")
    f_status = request.args.get("status")
    items = list(store.usage_reports.values())
    if f_license is not None:
        items = [r for r in items if r["license_id"] == f_license]
    if f_status is not None:
        items = [r for r in items if r["status"] == f_status]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serializers.usage_report(r) for r in page], limit, offset, total)


@bp.route("/glass/usage-reports/<usageReportId>/accept", methods=["POST"])
def accept_usage_report(usageReportId):
    authenticate({ROLE_FINANCE_CONTROLLER})
    get_body()
    report = _get_report_or_404(usageReportId)
    if report["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "accept requires SUBMITTED")
    lic = store.licenses[report["license_id"]]
    if lic["license_status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "License must be ACTIVE or SUSPENDED")
    # Priority 22: marketing must be APPROVED.
    if lic["marketing_status"] != "APPROVED":
        raise ApiError(
            ERR_MARKETING_NOT_APPROVED, "License marketing is not APPROVED"
        )
    # Final variant: sum raw revenues, then round half up exactly once.
    final = royalty_final_cents(report["lines"], report["royalty_rate_applied"])
    report["final_royalty_cents"] = final
    report["status"] = "ACCEPTED"
    store.touch(report)
    lic["cumulative_royalty_cents"] += final
    store.touch(lic)
    return success_object(serializers.usage_report(report))


@bp.route("/glass/usage-reports/<usageReportId>/dispute", methods=["POST"])
def dispute_usage_report(usageReportId):
    authenticate({ROLE_FINANCE_CONTROLLER})
    get_body()  # optional reason; accepted but not persisted
    report = _get_report_or_404(usageReportId)
    if report["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "dispute requires SUBMITTED")
    report["status"] = "DISPUTED"
    store.touch(report)
    return success_object(serializers.usage_report(report))
