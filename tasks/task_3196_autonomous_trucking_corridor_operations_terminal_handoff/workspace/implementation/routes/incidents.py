"""Incident reports, regulatory notice and the blocking cascade — PRD §3.5,
§3.13.  Endpoints 102-109.
"""

from datetime import timedelta

import db
import core
import services
import calculations as calc
from core import ApiError, D, now_iso, parse_iso
from response import ok, page_of
from http_util import pagination, must_get, get_or_none, body, coerce_int, arg
from routes._common import route
from models import create

SEVERITIES = ("MINOR", "MODERATE", "CRITICAL")

# §3.5: the incident tier is "banded by the corridor's weather profile and the
# applicable criteria table".  The scaffold names the tier without publishing the
# table, so the two high-risk weather classes the PRD declares in §3.1 —
# HIGH_WIND and LOW_VISIBILITY — take the two notice-bearing tiers.
TIER_BY_PROFILE = {
    "HIGH_WIND": "TIER_1",
    "LOW_VISIBILITY": "TIER_1",
    "HEAVY_PRECIPITATION": "TIER_2",
    "WINTER_SURFACE": "TIER_2",
    "CLEAR_DEFAULT": "TIER_3",
}


def register(app):

    @route(app, "/api/incident-reports", ["POST"], ["IncidentReviewer"])
    def create_incident():
        """§3.5: a filed report begins in FILED, is assigned a monotonic one-based
        report_sequence_number per corridor, resolves its incident_tier and
        recomputes regulatory_notice_required."""
        raw = body()
        allowed = {"corridor_id", "run_plan_id", "severity", "recordable_incidents",
                   "corrective_action_count", "review_days_allowed",
                   "reproduction_case_kind", "logs_populated"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in ("corridor_id", "run_plan_id", "severity"):
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        corridor = get_or_none("Corridor", raw["corridor_id"])
        if corridor is None:
            raise ApiError("ERR_CORRIDOR_NOT_FOUND")
        run = get_or_none("RunPlan", raw["run_plan_id"])
        if run is None:
            raise ApiError("ERR_RUN_PLAN_NOT_FOUND")
        if raw["severity"] not in SEVERITIES:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown severity.")

        row = create("IncidentReport", {
            "corridor_id": corridor["id"],
            "run_plan_id": run["id"],
            "severity": raw["severity"],
            "recordable_incidents": int(raw.get("recordable_incidents", 0) or 0),
            "corrective_action_count": int(raw.get("corrective_action_count", 0) or 0),
            "review_days_allowed": int(raw.get("review_days_allowed", 0) or 0),
            "reproduction_case_kind": raw.get("reproduction_case_kind"),
            "logs_populated": bool(raw.get("logs_populated", False)),
        })
        row["_carrier_id"] = run.get("carrier_id")
        row["_epoch_key"] = core.epoch_key()
        row["report_status"] = "FILED"
        # A monotonic one-based report_sequence_number per corridor in created_at
        # order.
        siblings = db.by("incident_reports", "corridor_id", corridor["id"])
        row["report_sequence_number"] = len(siblings)
        services.mark(row, "incident_tier", _tier(corridor))
        services.mark(row, "regulatory_notice_required", _notice_required(row))
        services.mark(row, "review_days_allowed", 3 if row["regulatory_notice_required"] else 5)
        services.flush(row)
        _recompute_carrier_for(row)
        return ok(row, 201)

    @route(app, "/api/incident-reports", ["GET"], ["Any"])
    def list_incidents():
        limit, offset = pagination()
        rows = db.all_rows("incident_reports")
        for field in ("corridor_id", "severity", "report_status"):
            value = arg(field)
            if value:
                rows = [r for r in rows if r.get(field) == value]
        carrier_id = arg("carrier_id")
        if carrier_id:
            rows = [r for r in rows if r.get("_carrier_id") == carrier_id]
        return page_of(db.sort_created(rows), limit, offset)

    @route(app, "/api/incident-reports/<rid>", ["GET"], ["Any"])
    def get_incident(rid):
        return ok(must_get("IncidentReport", rid))

    @route(app, "/api/incident-reports/<rid>/investigate", ["POST"], ["IncidentReviewer"])
    def investigate(rid):
        report = must_get("IncidentReport", rid)
        raw = body()
        _reject_unknown(raw)
        if report.get("report_status") != "FILED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only a filed report can be opened for investigation.")
        services.mark(report, "report_status", "INVESTIGATING")
        services.flush(report)
        _apply_incident_effects(report.get("corridor_id"))
        return ok(report)

    @route(app, "/api/incident-reports/<rid>/corrective-action", ["POST"],
           ["IncidentReviewer"])
    def corrective_action(rid):
        """§3.5: it will not proceed without at least one corrective action on
        file; a case presented as a replication rather than a reproduction is
        refused with ERR_REPRO_NOT_REPLICATION."""
        report = must_get("IncidentReport", rid)
        raw = body()
        allowed = {"corrective_action_count", "reproduction_case_kind"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if report.get("report_status") not in ("INVESTIGATING", "CORRECTIVE_ACTION"):
            raise ApiError("ERR_INVALID_STATE",
                           "Corrective action can only be recorded on an investigation.")
        kind = raw.get("reproduction_case_kind", report.get("reproduction_case_kind"))
        if isinstance(kind, str) and kind.strip().upper() == "REPLICATION":
            raise ApiError("ERR_REPRO_NOT_REPLICATION",
                           "The case must be labelled a reproduction, not a replication.")
        count = coerce_int(raw.get("corrective_action_count",
                                   report.get("corrective_action_count", 0)))
        if count < 1:
            raise ApiError("ERR_CORRECTIVE_ACTION_REQUIRED",
                           "At least one corrective action must be on file.")
        services.mark(report, "corrective_action_count", count)
        if kind is not None:
            services.mark(report, "reproduction_case_kind", kind)
        services.mark(report, "report_status", "CORRECTIVE_ACTION")
        services.mark(report, "regulatory_notice_required", _notice_required(report))
        services.mark(report, "review_days_allowed",
                      3 if report["regulatory_notice_required"] else 5)
        services.flush(report)
        _apply_incident_effects(report.get("corridor_id"))
        return ok(report)

    @route(app, "/api/incident-reports/<rid>/close", ["POST"], ["ComplianceOfficer"])
    def close_incident(rid):
        report = must_get("IncidentReport", rid)
        raw = body()
        _reject_unknown(raw)
        if report.get("report_status") != "CORRECTIVE_ACTION":
            raise ApiError("ERR_INVALID_STATE",
                           "Only a report in CORRECTIVE_ACTION can be closed.")
        if coerce_int(report.get("corrective_action_count") or 0) < 1:
            raise ApiError("ERR_CORRECTIVE_ACTION_REQUIRED",
                           "At least one corrective action must be on file.")
        services.mark(report, "report_status", "CLOSED")
        services.flush(report)
        _recompute_carrier_for(report)
        _apply_incident_effects(report.get("corridor_id"))
        return ok(report)

    @route(app, "/api/incident-reports/<rid>/submit", ["POST"], ["IncidentReviewer"])
    def submit_incident(rid):
        """§3.5: submission requires regulatory_notice_required to be true and the
        ledger clock to fall within review_days_allowed business days of the
        filing epoch, measured inclusively."""
        report = must_get("IncidentReport", rid)
        raw = body()
        _reject_unknown(raw)
        if report.get("report_status") != "INVESTIGATING":
            raise ApiError("ERR_INVALID_STATE",
                           "Only an investigating report can be submitted.")
        if not report.get("regulatory_notice_required"):
            raise ApiError("ERR_INVALID_STATE",
                           "Regulatory notice is not required for this report.")
        if not _within_review_window(report):
            raise ApiError("ERR_REVIEW_WINDOW_LAPSED",
                           "The incident's review window has lapsed.")
        services.mark(report, "report_status", "SUBMITTED")
        services.flush(report)
        _recompute_carrier_for(report)
        _apply_incident_effects(report.get("corridor_id"))
        return ok(report)

    @route(app, "/api/incident-reports/<rid>/reopen", ["POST"], ["IncidentReviewer"])
    def reopen_incident(rid):
        report = must_get("IncidentReport", rid)
        raw = body()
        _reject_unknown(raw)
        if report.get("report_status") not in ("CORRECTIVE_ACTION", "SUBMITTED"):
            raise ApiError("ERR_INVALID_STATE",
                           "Only a corrective-action or submitted report can be reopened.")
        if not _within_review_window(report):
            raise ApiError("ERR_REVIEW_WINDOW_LAPSED",
                           "The incident's review window has lapsed.")
        services.mark(report, "report_status", "INVESTIGATING")
        services.flush(report)
        _apply_incident_effects(report.get("corridor_id"))
        return ok(report)


def _tier(corridor):
    profile = corridor.get("weather_profile")
    return TIER_BY_PROFILE.get(profile, "TIER_3")


def _notice_required(report):
    """True when incident_tier is TIER_1 or TIER_2, or when severity is CRITICAL."""
    if report.get("incident_tier") in ("TIER_1", "TIER_2"):
        return True
    return report.get("severity") == "CRITICAL"


def _reject_unknown(raw):
    for key in raw:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' is not declared for this endpoint." % key)


def _recompute_carrier_for(report):
    carrier = db.get("carriers", report.get("_carrier_id"))
    if carrier is None:
        return
    services.recompute_carrier_recordable(carrier)
    services.recompute_carrier(carrier)
    services.flush(carrier)


def _critical_open_count(corridor_id):
    return len([r for r in db.by("incident_reports", "corridor_id", corridor_id)
                if r.get("severity") == "CRITICAL"
                and r.get("report_status") in ("INVESTIGATING", "SUBMITTED")])


def _apply_incident_effects(corridor_id):
    """§3.5: recomputes the corridor's blocking flag, and a critical report on an
    ACTIVE corridor forces it to LIMITED; a third critical report inside the review
    window forces SUSPENDED."""
    corridor = db.get("corridors", corridor_id)
    if corridor is None:
        return
    blocking = services.compute_blocking_incident(corridor_id)
    services.mark(corridor, "has_blocking_incident", blocking)
    services.recompute_corridor(corridor)
    services.flush(corridor)
    if blocking:
        if corridor.get("corridor_status") == "ACTIVE":
            services.limit_corridor(corridor)
        elif corridor.get("corridor_status") == "LIMITED" and _critical_open_count(corridor_id) >= 3:
            services.suspend_corridor(corridor)
    else:
        services.maybe_recover_limited(corridor)


def _within_review_window(report):
    """The ledger clock must fall within review_days_allowed business days of the
    filing epoch, measured inclusively."""
    filed = parse_iso(report.get("created_at"))
    if filed is None:
        return True
    allowed = int(report.get("review_days_allowed") or 0)
    if allowed <= 0:
        return False
    return _business_days_inclusive(filed, core.now()) <= allowed


def _business_days_inclusive(start, end):
    """Number of weekdays from `start` to `end` inclusive of both endpoints."""
    a = start.date()
    b = end.date()
    if b < a:
        return 1
    days = 0
    cursor = a
    while cursor <= b:
        if cursor.weekday() < 5:
            days += 1
        cursor += timedelta(days=1)
    return days