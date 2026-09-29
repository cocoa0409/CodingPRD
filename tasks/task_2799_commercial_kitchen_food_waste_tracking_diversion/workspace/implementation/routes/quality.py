"""Coaching alerts, data quality, corporate rollups and the logical clock."""
from datetime import timedelta

from flask import Blueprint

from db import base_row, db, iso, parse_ts, sort_rows, touch
from errors import fail
from middleware import (ALL_READERS, CORPORATE_LEAD, KITCHEN_STAFF,
                        PLATFORM_ADMIN, SHIFT_LEAD, SITE_MANAGER, authenticate,
                        require_site_scope)
from response import array_response, object_response, row_response
from routes.common import filtered, must_exist, respond_list
from services import derive
from validation import (bad, body_json, field_date, field_enum, field_str,
                       field_ts, field_array, query_enum, query_str)

bp = Blueprint("quality", __name__)

ALERT_STATUSES = ("OPEN", "ACKNOWLEDGED", "RESOLVED", "AUTO_RESOLVED", "EXPIRED")
ALERT_TYPES = ("INTENSITY_BREACH", "OVERPRODUCTION_SPIKE")
SEVERITIES = ("MEDIUM", "HIGH")
FINDING_TYPES = ("MISSED_CAPTURE", "DUPLICATE_ENTRY", "WEIGHT_OUTLIER")
FINDING_STATUSES = ("OPEN", "CONFIRMED", "DISMISSED")
ROLLUP_STATUSES = ("DRAFT", "PUBLISHED")
GOAL_STATES = ("ALL_ON_TRACK", "PARTIAL", "NONE_ON_TRACK")


# ------------------------------------------------------------ coaching alerts
@bp.route("/coaching-alerts/<alert_id>/acknowledge", methods=["POST"])
def acknowledge_alert(alert_id):
    caller = authenticate((KITCHEN_STAFF, SHIFT_LEAD))
    body_json()
    alert = must_exist(db.alerts, alert_id, "ERR_ALERT_NOT_FOUND")
    if alert["status"] != "OPEN":
        fail("ERR_INVALID_ALERT_STATE", "Only an OPEN alert may be acknowledged.")
    alert["status"] = "ACKNOWLEDGED"
    alert["acknowledged_by_user_id"] = caller.user_id
    touch(alert)
    # The site's open_alert_count deliberately does not change here.
    return row_response(alert)


@bp.route("/coaching-alerts/<alert_id>/resolve", methods=["POST"])
def resolve_alert(alert_id):
    caller = authenticate((SHIFT_LEAD,))
    body = body_json()
    resolution_note = field_str(body, "resolution_note")
    alert = must_exist(db.alerts, alert_id, "ERR_ALERT_NOT_FOUND")
    if alert["status"] != "ACKNOWLEDGED":
        fail("ERR_INVALID_ALERT_STATE",
             "Only an ACKNOWLEDGED alert may be resolved.")
    alert["status"] = "RESOLVED"
    alert["resolution_note"] = resolution_note
    alert["resolved_by_user_id"] = caller.user_id
    alert["resolved_at"] = db.now_iso()
    touch(alert)
    site = db.sites[alert["site_id"]]
    derive.recompute_site(site)
    touch(site)
    return row_response(alert)


@bp.route("/coaching-alerts/<alert_id>", methods=["GET"])
def get_alert(alert_id):
    authenticate(ALL_READERS)
    return row_response(must_exist(db.alerts, alert_id, "ERR_ALERT_NOT_FOUND"))


@bp.route("/coaching-alerts", methods=["GET"])
def list_alerts():
    authenticate(ALL_READERS)
    rows = filtered(list(db.alerts.values()),
                    site_id=query_str("site_id"),
                    shift_id=query_str("shift_id"),
                    waste_entry_id=query_str("waste_entry_id"),
                    status=query_enum("status", ALERT_STATUSES),
                    alert_type=query_enum("alert_type", ALERT_TYPES),
                    severity=query_enum("severity", SEVERITIES))
    return respond_list(rows)


# --------------------------------------------------------------- data quality
@bp.route("/data-quality-scans", methods=["POST"])
def run_scan():
    caller = authenticate((SITE_MANAGER, PLATFORM_ADMIN))
    body = body_json()
    site_id = field_str(body, "site_id")
    scan_date = field_date(body, "scan_date")
    site = must_exist(db.sites, site_id, "ERR_SITE_NOT_FOUND")
    require_site_scope(caller, site_id)
    created = derive.run_data_quality_scan(site, scan_date)
    return array_response(created)


@bp.route("/data-quality-findings/<finding_id>/resolve", methods=["POST"])
def resolve_finding(finding_id):
    caller = authenticate((SITE_MANAGER,))
    body = body_json()
    resolution = field_enum(body, "resolution", ("CONFIRMED", "DISMISSED"))
    field_str(body, "resolution_note", required=False)
    finding = must_exist(db.findings, finding_id, "ERR_FINDING_NOT_FOUND")
    require_site_scope(caller, finding["site_id"])
    if finding["status"] != "OPEN":
        fail("ERR_INVALID_FINDING_STATE", "This finding is already resolved.")
    finding["status"] = resolution
    finding["resolved_by_user_id"] = caller.user_id
    touch(finding)
    return row_response(finding)


@bp.route("/data-quality-findings/<finding_id>", methods=["GET"])
def get_finding(finding_id):
    authenticate(ALL_READERS)
    return row_response(must_exist(db.findings, finding_id,
                                   "ERR_FINDING_NOT_FOUND"))


@bp.route("/data-quality-findings", methods=["GET"])
def list_findings():
    authenticate(ALL_READERS)
    rows = filtered(list(db.findings.values()),
                    site_id=query_str("site_id"),
                    waste_entry_id=query_str("waste_entry_id"),
                    station_id=query_str("station_id"),
                    shift_id=query_str("shift_id"),
                    finding_type=query_enum("finding_type", FINDING_TYPES),
                    status=query_enum("status", FINDING_STATUSES))
    return respond_list(rows)


# ----------------------------------------------------------- corporate rollups
@bp.route("/corporate-rollups", methods=["POST"])
def create_rollup():
    caller = authenticate((CORPORATE_LEAD,))
    body = body_json()
    period_start = field_date(body, "period_start")
    period_end = field_date(body, "period_end")
    if period_end < period_start:
        bad("period_end may not be earlier than period_start.")
    site_ids = field_array(body, "site_ids", min_len=1)
    for value in site_ids:
        if not isinstance(value, str) or value == "":
            bad("Every member of 'site_ids' must be a site identifier.")
    for value in site_ids:
        must_exist(db.sites, value, "ERR_SITE_NOT_FOUND")
    if len(set(site_ids)) != len(site_ids):
        fail("ERR_DUPLICATE_SITE_IN_SCOPE",
             "A site may appear at most once in site_ids.")
    rollup = base_row(
        period_start=period_start,
        period_end=period_end,
        site_ids=list(site_ids),
        status="DRAFT",
        prepared_by_user_id=caller.user_id,
        published_by_user_id=None,
        published_at=None,
        in_scope_site_count=len(site_ids),
        total_captured_weight_grams=0,
        total_valued_cost_cents=0,
        total_diverted_weight_grams=0,
        diversion_rate_pct=None,
        sites_on_track_count=0,
        goal_attainment_state="NONE_ON_TRACK",
        published_metrics=None,
    )
    derive.recompute_rollup(rollup)
    db.rollups[rollup["id"]] = rollup
    return row_response(rollup, 201)


@bp.route("/corporate-rollups/<rollup_id>/publish", methods=["POST"])
def publish_rollup(rollup_id):
    caller = authenticate((CORPORATE_LEAD,))
    body_json()
    rollup = must_exist(db.rollups, rollup_id, "ERR_ROLLUP_NOT_FOUND")
    if rollup["status"] != "DRAFT":
        fail("ERR_ROLLUP_ALREADY_PUBLISHED", "This rollup is already published.")
    if rollup["prepared_by_user_id"] == caller.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The lead who prepared a rollup may not publish it.")
    if derive.site_has_open_findings(set(rollup["site_ids"])):
        fail("ERR_ROLLUP_DATA_QUALITY_BLOCKED",
             "An in-scope site still holds an OPEN data-quality finding.")
    derive.recompute_rollup(rollup)
    rollup["published_metrics"] = {
        "total_captured_weight_grams": rollup["total_captured_weight_grams"],
        "total_valued_cost_cents": rollup["total_valued_cost_cents"],
        "total_diverted_weight_grams": rollup["total_diverted_weight_grams"],
        "diversion_rate_pct": rollup["diversion_rate_pct"],
        "sites_on_track_count": rollup["sites_on_track_count"],
        "goal_attainment_state": rollup["goal_attainment_state"],
    }
    rollup["published_by_user_id"] = caller.user_id
    rollup["published_at"] = db.now_iso()
    rollup["status"] = "PUBLISHED"
    touch(rollup)
    return row_response(rollup)


@bp.route("/corporate-rollups/<rollup_id>", methods=["GET"])
def get_rollup(rollup_id):
    authenticate(ALL_READERS)
    rollup = must_exist(db.rollups, rollup_id, "ERR_ROLLUP_NOT_FOUND")
    if rollup["status"] == "DRAFT":
        derive.recompute_rollup(rollup)
    return row_response(rollup)


@bp.route("/corporate-rollups", methods=["GET"])
def list_rollups():
    authenticate(ALL_READERS)
    status = query_enum("status", ROLLUP_STATUSES)
    goal_state = query_enum("goal_attainment_state", GOAL_STATES)
    for rollup in db.rollups.values():
        if rollup["status"] == "DRAFT":
            derive.recompute_rollup(rollup)
    rows = filtered(list(db.rollups.values()), status=status,
                    goal_attainment_state=goal_state)
    return respond_list(rows)


# ------------------------------------------------------------- logical clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # The one endpoint open to any caller: no identity headers are required and
    # neither authentication error applies to it.
    body = body_json()
    current = field_ts(body, "current_utc")
    if not current > db.clock:
        fail("ERR_CLOCK_NOT_MONOTONIC",
             "current_utc must be strictly greater than the stored clock.")
    db.clock = current
    reevaluated = []
    resolved = []
    active = [t for t in db.targets.values() if t["status"] == "ACTIVE"]
    for target in sort_rows(active):
        deadline = parse_ts(target["window_end"] + "T00:00:00Z") + timedelta(days=1)
        if current < deadline:
            continue
        derive.apply_attainment(target)
        reevaluated.append(target["id"])
        if target["attainment_state"] == "ACHIEVED_PENDING":
            target["status"] = "ACHIEVED"
        else:
            target["status"] = "MISSED"
        target["resolved_at"] = iso(current)
        touch(target)
        resolved.append(target["id"])
    return object_response({
        "current_utc": iso(current),
        "reevaluated_target_ids": reevaluated,
        "resolved_target_ids": resolved,
    })
