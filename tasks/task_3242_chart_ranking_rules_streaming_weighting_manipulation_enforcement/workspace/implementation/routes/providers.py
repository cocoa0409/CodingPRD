"""Provider and consumption report routes."""

from flask import Blueprint, request

import errors
from db import db
from helpers import (
    envelope_ok,
    get_json,
    iso3,
    paginate,
    pagination_params,
    parse_dt,
    require_roles,
    touch,
)
from services import (
    FEED_KIND_COMPONENTS,
    get_chart,
    get_provider,
    get_report,
    get_title,
    get_week,
    new_entity,
    require_no_active_freeze,
    ser_provider,
    ser_report,
)

bp = Blueprint("providers", __name__)

ALL_ROLES = ("PlatformAdmin", "ChartManager", "ChartOps", "DataProvider", "LabelRep", "Investigator")
REPORT_READ_ROLES = ("PlatformAdmin", "ChartManager", "ChartOps", "Investigator")


@bp.route("/providers", methods=["POST"])
def create_provider():
    require_roles("PlatformAdmin")
    payload = get_json()
    provider_code = payload.get("provider_code")
    for p in db.providers.values():
        if p["provider_code"] == provider_code:
            raise errors.ApiError("ERR_VALIDATION", "provider_code must be unique", 422)

    p = new_entity()
    p.update(
        provider_code=provider_code,
        display_name=payload.get("display_name"),
        feed_kind=payload.get("feed_kind"),
        territory=payload.get("territory"),
        status="ACTIVE",
    )
    db.providers[p["id"]] = p
    return envelope_ok(ser_provider(p), response_type="object", status=201)


@bp.route("/providers", methods=["GET"])
def list_providers():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    feed_kind = request.args.get("feed_kind")
    territory = request.args.get("territory")
    items = sorted(db.providers.values(), key=lambda p: (p["created_at"], p["_seq"]))
    if feed_kind:
        items = [p for p in items if p["feed_kind"] == feed_kind]
    if territory:
        items = [p for p in items if p["territory"] == territory]
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_provider(p) for p in page], response_type="array", pagination=page_meta)


@bp.route("/providers/<pid>", methods=["GET"])
def get_provider_route(pid):
    require_roles(*ALL_ROLES)
    p = get_provider(pid)
    return envelope_ok(ser_provider(p), response_type="object")


@bp.route("/providers/<pid>/suspend", methods=["POST"])
def suspend_provider(pid):
    require_roles("PlatformAdmin")
    p = get_provider(pid)
    p["status"] = "SUSPENDED"
    touch(p)
    return envelope_ok(ser_provider(p), response_type="object", status=200)


@bp.route("/providers/<pid>/reports", methods=["GET"])
def list_provider_reports(pid):
    require_roles(*REPORT_READ_ROLES)
    p = get_provider(pid)
    limit, offset = pagination_params()
    status_filter = request.args.get("status")
    items = sorted(
        [r for r in db.consumption_reports.values() if r["provider_id"] == p["id"]],
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_report(r) for r in page], response_type="array", pagination=page_meta)


@bp.route("/providers/<pid>/reports", methods=["POST"])
def submit_report(pid):
    user_id, role = require_roles("DataProvider")
    p = get_provider(pid)
    # DataProvider identity: X-User-ID is the provider id
    if user_id != p["id"]:
        raise errors.unauthorized("DataProvider may only submit under its own registration")

    payload = get_json()
    title_id = payload.get("title_product_id")
    week_id = payload.get("chart_week_id")
    title = db.title_products.get(title_id)
    if title is None:
        raise errors.not_found("TitleProduct not found")
    week = db.chart_weeks.get(week_id)
    if week is None:
        raise errors.not_found("ChartWeek not found")

    component_kind = payload.get("component_kind")
    quantity = payload.get("quantity")
    event_time_s = payload.get("event_time")
    file_fingerprint = payload.get("file_fingerprint")

    event_time = parse_dt(event_time_s)

    # component kind must be permitted by provider feed_kind
    permitted = FEED_KIND_COMPONENTS.get(p["feed_kind"], set())
    if component_kind not in permitted:
        raise errors.component_kind_mismatch()

    # duplicate fingerprint from same provider
    for r in db.consumption_reports.values():
        if r["provider_id"] == p["id"] and r["file_fingerprint"] == file_fingerprint:
            raise errors.duplicate_report_batch()

    # event_time within [opens_at, reporting_cutoff)
    opens_at = parse_dt(week["opens_at"])
    cutoff = parse_dt(week["reporting_cutoff"])
    if not (opens_at <= event_time < cutoff):
        raise errors.reporting_cutoff_passed()

    report = new_entity()
    report.update(
        provider_id=p["id"],
        title_product_id=title["id"],
        chart_week_id=week["id"],
        component_kind=component_kind,
        quantity=quantity,
        event_time=iso3(event_time),
        file_fingerprint=file_fingerprint,
        status="RECEIVED",
        review_reason=None,
    )
    db.consumption_reports[report["id"]] = report
    return envelope_ok(ser_report(report), response_type="object", status=201)


@bp.route("/consumption-reports/<rid>", methods=["GET"])
def get_report_route(rid):
    require_roles(*REPORT_READ_ROLES)
    r = get_report(rid)
    return envelope_ok(ser_report(r), response_type="object")


def _review_report(rid, target_status, reason_field=False):
    require_roles("ChartOps")
    r = get_report(rid)
    week = get_week(r["chart_week_id"])
    chart = get_chart(week["chart_id"])
    payload = get_json()

    if target_status == "ACCEPTED":
        require_no_active_freeze(chart["id"])

    if r["status"] != "RECEIVED":
        raise errors.invalid_state("Report must be RECEIVED")

    if target_status == "ACCEPTED":
        provider = get_provider(r["provider_id"])
        if provider["status"] != "ACTIVE":
            raise errors.account_suspended("Provider is SUSPENDED")
        if week["status"] != "OPEN":
            raise errors.invalid_state("Week must be OPEN to accept reports")
        permitted = FEED_KIND_COMPONENTS.get(provider["feed_kind"], set())
        if r["component_kind"] not in permitted:
            raise errors.component_kind_mismatch()
        opens_at = parse_dt(week["opens_at"])
        cutoff = parse_dt(week["reporting_cutoff"])
        event_time = parse_dt(r["event_time"])
        if not (opens_at <= event_time < cutoff):
            raise errors.reporting_cutoff_passed()
    else:
        if week["status"] != "OPEN":
            raise errors.invalid_state("Week must be OPEN")

    r["status"] = target_status
    if reason_field:
        r["review_reason"] = payload.get("reason")
    touch(r)
    return envelope_ok(ser_report(r), response_type="object", status=200)


@bp.route("/consumption-reports/<rid>/accept", methods=["POST"])
def accept_report(rid):
    return _review_report(rid, "ACCEPTED")


@bp.route("/consumption-reports/<rid>/quarantine", methods=["POST"])
def quarantine_report(rid):
    return _review_report(rid, "QUARANTINED", reason_field=True)


@bp.route("/consumption-reports/<rid>/reject", methods=["POST"])
def reject_report(rid):
    return _review_report(rid, "REJECTED", reason_field=True)


# ---------------------------------------------------------------------------
# Reverse reachability
# ---------------------------------------------------------------------------

@bp.route("/chart-weeks/<wid>/reports", methods=["GET"])
def list_week_reports(wid):
    require_roles(*REPORT_READ_ROLES)
    week = get_week(wid)
    limit, offset = pagination_params()
    status_filter = request.args.get("status")
    items = sorted(
        [r for r in db.consumption_reports.values() if r["chart_week_id"] == week["id"]],
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_report(r) for r in page], response_type="array", pagination=page_meta)
