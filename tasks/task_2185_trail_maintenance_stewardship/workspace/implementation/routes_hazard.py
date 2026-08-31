"""Condition reports: intake, triage, disposition, resolution and voiding."""

import math

from flask import Blueprint, request

import calc
import domain
import store
import validation as v
from auth import ALL_ROLES, require, role
from envelope import created, ok, paginate
from errors import fail
from store import new_entity, touch

bp = Blueprint("hazard", __name__)

HAZARD_TYPES = ("BLOWDOWN", "TREAD_EROSION", "DRAINAGE_FAILURE", "BRIDGE_DAMAGE",
                "SIGNAGE_MISSING", "BRUSH_ENCROACHMENT")
SEVERITY_CLASSES = ("LOW", "MODERATE", "HIGH", "CRITICAL")
EXPOSURE_CLASSES = ("LOW", "MEDIUM", "HIGH")
REPORT_STATUSES = ("SUBMITTED", "TRIAGED", "SCHEDULED", "DEFERRED", "ESCALATED",
                   "RESOLVED", "VOIDED")
DISPOSITIONS = ("SCHEDULE", "DEFER", "ESCALATE")


def _age_days(report):
    created = store.created_dt(report)
    if created is None:
        return 0
    delta = (store.now() - created).total_seconds()
    if delta < 0:
        return 0
    return int(math.floor(delta / 86400.0))


def _score(report, segment, variant):
    return calc.priority_score(
        report["severity_class"],
        report["exposure_class"],
        report["traffic_class_snapshot"],
        age_days=_age_days(report),
        wet=(segment["posture"] == "WET_RESTRICTED"),
        variant=variant,
    )


@bp.post("/condition-reports")
@require("Volunteer", "CrewLeader")
def create_report():
    data = v.body()
    trail_segment_id = v.req_id(data, "trail_segment_id")
    reported_by_volunteer_id = v.req_id(data, "reported_by_volunteer_id")
    hazard_type = v.req_enum(data, "hazard_type", HAZARD_TYPES)
    severity_class = v.req_enum(data, "severity_class", SEVERITY_CLASSES)
    description = v.req_str(data, "description", allow_empty=True)

    domain.get_segment(trail_segment_id)
    domain.get_volunteer(reported_by_volunteer_id)

    report = new_entity({
        "trail_segment_id": trail_segment_id,
        "reported_by_volunteer_id": reported_by_volunteer_id,
        "hazard_type": hazard_type,
        "severity_class": severity_class,
        "description": description,
        "exposure_class": None,
        "traffic_class_snapshot": None,
        "priority_score": 0,
        "priority_variant": None,
        "status": "SUBMITTED",
        "linked_work_party_id": None,
        "defer_until_date": None,
        "resolved_at": None,
    })
    store.reports[report["id"]] = report
    return created(domain.s_report(report))


@bp.get("/condition-reports/<entity_id>")
@require(*ALL_ROLES)
def read_report(entity_id):
    return ok(domain.s_report(domain.get_report(entity_id)))


@bp.get("/condition-reports")
@require(*ALL_ROLES)
def list_reports():
    trail_segment_id = request.args.get("trail_segment_id")
    reported_by_volunteer_id = request.args.get("reported_by_volunteer_id")
    linked_work_party_id = request.args.get("linked_work_party_id")
    status = request.args.get("status")
    if status is not None and status not in REPORT_STATUSES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'status' is not a declared member.")
    rows = store.ordered(list(store.reports.values()))
    if trail_segment_id is not None:
        rows = [r for r in rows if r["trail_segment_id"] == trail_segment_id]
    if reported_by_volunteer_id is not None:
        rows = [r for r in rows if r["reported_by_volunteer_id"] == reported_by_volunteer_id]
    if linked_work_party_id is not None:
        rows = [r for r in rows if r.get("linked_work_party_id") == linked_work_party_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, domain.s_report)


@bp.post("/condition-reports/<entity_id>/triage")
@require("StewardshipCoordinator")
def triage_report(entity_id):
    report = domain.get_report(entity_id)
    data = v.body()
    exposure_class = v.req_enum(data, "exposure_class", EXPOSURE_CLASSES)
    severity_override = v.opt_enum(data, "severity_override", SEVERITY_CLASSES)

    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED report may be triaged.")

    segment = domain.get_segment(report["trail_segment_id"])
    if severity_override is not None:
        report["severity_class"] = severity_override
    report["exposure_class"] = exposure_class
    report["traffic_class_snapshot"] = segment["traffic_class"]
    report["priority_score"] = _score(report, segment, "INITIAL_TRIAGE")
    report["priority_variant"] = "INITIAL_TRIAGE"
    report["status"] = "TRIAGED"
    touch(report)

    domain.settle_segment(segment, recompute_hazard=True)
    return ok(domain.s_report(report))


@bp.post("/condition-reports/<entity_id>/disposition")
@require("StewardshipCoordinator")
def disposition_report(entity_id):
    report = domain.get_report(entity_id)
    data = v.body()
    disposition = v.req_enum(data, "disposition", DISPOSITIONS)
    linked_work_party_id = None
    defer_until_date = None
    if disposition == "SCHEDULE":
        linked_work_party_id = v.req_id(data, "linked_work_party_id")
    elif disposition == "DEFER":
        defer_until_date = v.req_date(data, "defer_until_date")

    party = None
    if linked_work_party_id is not None:
        party = domain.get_party(linked_work_party_id)

    if report["status"] != "TRIAGED":
        fail("ERR_INVALID_STATE", "Only a TRIAGED report may be dispositioned.")

    segment = domain.get_segment(report["trail_segment_id"])

    if disposition == "SCHEDULE":
        if party["trail_segment_id"] != report["trail_segment_id"]:
            fail("ERR_INVALID_REQUEST",
                 "The linked work party is on a different trail segment.")
        if party["schedule_status"] not in ("PLANNED", "CONFIRMED"):
            fail("ERR_INVALID_STATE",
                 "The linked work party must be PLANNED or CONFIRMED.")
    elif disposition == "DEFER":
        if defer_until_date <= store.clock_date():
            fail("ERR_INVALID_REQUEST",
                 "defer_until_date must be strictly after the logical clock date.")

    score = _score(report, segment, "REASSESSED")

    if disposition == "DEFER" and score >= calc.ESCALATION_THRESHOLD:
        fail("ERR_PRIORITY_TOO_HIGH_TO_DEFER", "The report is too urgent to defer.")
    if disposition == "ESCALATE" and score < calc.ESCALATION_THRESHOLD:
        fail("ERR_PRIORITY_TOO_LOW_TO_ESCALATE", "The report is not urgent enough to escalate.")

    report["priority_score"] = score
    report["priority_variant"] = "REASSESSED"
    if disposition == "SCHEDULE":
        report["status"] = "SCHEDULED"
        report["linked_work_party_id"] = linked_work_party_id
    elif disposition == "DEFER":
        report["status"] = "DEFERRED"
        report["defer_until_date"] = store.fmt_date(defer_until_date)
    else:
        report["status"] = "ESCALATED"
    touch(report)

    if party is not None:
        touch(party)

    domain.settle_segment(segment, recompute_hazard=True)
    return ok(domain.s_report(report))


@bp.post("/condition-reports/<entity_id>/resolve")
@require("StewardshipCoordinator", "SafetyOfficer")
def resolve_report(entity_id):
    report = domain.get_report(entity_id)
    data = v.body()
    v.opt_str(data, "resolution_note")

    if report["status"] not in ("SCHEDULED", "DEFERRED", "ESCALATED"):
        fail("ERR_INVALID_STATE", "Only a dispositioned report may be resolved.")

    linked_party = None
    if report["status"] == "SCHEDULED":
        linked_party = store.parties.get(report.get("linked_work_party_id"))
        if linked_party is None or linked_party["schedule_status"] != "COMPLETED":
            fail("ERR_LINKED_PARTY_NOT_COMPLETE", "The linked work party is not COMPLETED.")
    elif report["status"] == "DEFERRED":
        defer_until = store.parse_date(report.get("defer_until_date"))
        if defer_until is not None and store.clock_date() < defer_until:
            fail("ERR_DEFER_DATE_NOT_REACHED", "The deferral date has not been reached.")
    else:
        cleared = role() == "SafetyOfficer"
        if not cleared:
            for order in store.orders.values():
                if (order.get("condition_report_id") == report["id"]
                        and order["status"] in ("APPROVED", "DELIVERED")):
                    cleared = True
                    break
        if not cleared:
            fail("ERR_ESCALATION_NOT_CLEARED", "The escalation has not been cleared.")

    report["status"] = "RESOLVED"
    report["resolved_at"] = store.now_iso()
    touch(report)

    if linked_party is not None:
        touch(linked_party)

    segment = domain.get_segment(report["trail_segment_id"])
    domain.settle_segment(segment, recompute_hazard=True)
    return ok(domain.s_report(report))


@bp.post("/condition-reports/<entity_id>/void")
@require("StewardshipCoordinator")
def void_report(entity_id):
    report = domain.get_report(entity_id)
    data = v.body()
    v.req_str(data, "reason")

    if report["status"] not in ("SUBMITTED", "TRIAGED"):
        fail("ERR_INVALID_STATE", "Only a SUBMITTED or TRIAGED report may be voided.")

    report["status"] = "VOIDED"
    touch(report)

    segment = domain.get_segment(report["trail_segment_id"])
    domain.settle_segment(segment, recompute_hazard=True)
    return ok(domain.s_report(report))
