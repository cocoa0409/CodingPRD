"""Serious-incident reporting and its short clock (PRD §3.7)."""

from flask import Blueprint, request

import clock
import constants as K
import derive
import envelope
import helpers
import serialize
import store
import validate
from auth import authenticate, require_provider_owner
from errors import ApiError
from routes.complaints import new_complaint
from validate import F

bp = Blueprint("reports", __name__)

REPORT_READERS = (
    "AgencyAdmin",
    "Applicant",
    "LicensingSupervisor",
    "ComplaintIntakeSpecialist",
)

ABUSE_INCIDENT_TYPES = ("FATALITY", "SERIOUS_INJURY", "MISSING_CHILD")
INVESTIGATION_ONLY_TYPES = ("FATALITY", "MISSING_CHILD")


@bp.post("/licensing/serious-incident-reports")
def file_report():
    user_id, role = authenticate(("Applicant", "AgencyAdmin"))
    vals = validate.body(
        [
            F("provider_id", "string", required=True),
            F("incident_type", "enum", required=True, values=K.INCIDENT_TYPES),
            F("occurred_at", "instant", required=True),
            F("affected_child_age_group", "enum", required=True, values=K.AGE_GROUPS),
            F("narrative", "string", required=True, min_len=1, max_len=2000, not_blank=True),
        ]
    )
    provider = helpers.need("provider", vals["provider_id"])
    require_provider_owner(role, user_id, provider["id"])

    occurred = clock.parse_instant(vals["occurred_at"])
    reported = clock.now_dt()
    if occurred > reported:
        raise ApiError(
            "ERR_INCIDENT_OCCURRED_IN_FUTURE",
            "occurred_at may not be later than the current instant.",
        )
    deadline = clock.add_hours(occurred, K.INCIDENT_REPORT_WINDOW_HOURS[vals["incident_type"]])
    timeliness = "TIMELY" if reported <= deadline else "LATE_REPORT"

    target = None
    item = None
    if timeliness == "LATE_REPORT":
        candidates = [
            i
            for i in store.provider_inspections(provider["id"])
            if i["status"] == "FINALIZED"
        ]
        target = derive.latest_finalized(candidates)
        if target is not None:
            item = store.checklist_by_code(K.LATE_INCIDENT_CHECKLIST_CODE)
            if item is None:
                raise ApiError(
                    "ERR_CHECKLIST_ITEM_NOT_FOUND",
                    "The catalog has no checklist item with code %s."
                    % K.LATE_INCIDENT_CHECKLIST_CODE,
                )

    record = {
        "provider_id": provider["id"],
        "generated_complaint_id": None,
        "incident_type": vals["incident_type"],
        "occurred_at": clock.fmt(occurred),
        "reported_at": clock.fmt(reported),
        "affected_child_age_group": vals["affected_child_age_group"],
        "narrative": vals["narrative"],
        "reporting_deadline_at": clock.fmt(deadline),
        "reporting_timeliness": timeliness,
        "late_report_violation_created": False,
        "status": "REPORTED",
        "reviewed_at": None,
        "closed_at": None,
        "agency_note": None,
    }
    store.create(store.reports, record)

    if target is not None and item is not None:
        violation = derive.create_violation(
            target,
            item,
            vals["affected_child_age_group"],
            vals["narrative"],
            "CRITICAL",
            auto_generated=True,
            status="CORRECTION_PENDING",
            with_due_date=True,
        )
        violation["severity_override"] = "CRITICAL"
        record["late_report_violation_created"] = True
        derive.recompute_violation_count(target)
        derive.recompute_final_score(target)
        store.touch(target)
        derive.recompute_provider(provider)
        store.touch(provider)
    return envelope.created(serialize.report(record))


@bp.get("/licensing/serious-incident-reports")
def list_reports():
    authenticate(REPORT_READERS)
    limit, offset = envelope.pagination(request.args)
    status = validate.query_enum("status", K.INCIDENT_STATUSES)
    incident_type = validate.query_enum("incident_type", K.INCIDENT_TYPES)
    timeliness = validate.query_enum("reporting_timeliness", K.REPORTING_TIMELINESS)
    provider_id = validate.query_str("provider_id")
    complaint_id = validate.query_str("generated_complaint_id")
    rows = store.ordered(store.reports)
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if complaint_id is not None:
        rows = [r for r in rows if r.get("generated_complaint_id") == complaint_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if incident_type is not None:
        rows = [r for r in rows if r["incident_type"] == incident_type]
    if timeliness is not None:
        rows = [r for r in rows if r["reporting_timeliness"] == timeliness]
    return helpers.listing(rows, serialize.report, limit, offset)


@bp.get("/licensing/serious-incident-reports/<report_id>")
def read_report(report_id):
    authenticate(REPORT_READERS)
    record = helpers.need("report", report_id)
    return envelope.ok(serialize.report(record))


@bp.post("/licensing/serious-incident-reports/<report_id>/review")
def review_report(report_id):
    authenticate(("LicensingSupervisor",))
    vals = validate.body(
        [
            F("disposition", "enum", required=True, values=K.INCIDENT_DISPOSITIONS),
            F("agency_note", "string", min_len=1, max_len=2000, not_blank=True),
        ]
    )
    record = helpers.need("report", report_id)
    if record["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_INCIDENT_STATE", "The report is not REPORTED.")
    if vals["disposition"] == "MONITOR" and record["incident_type"] in INVESTIGATION_ONLY_TYPES:
        raise ApiError(
            "ERR_INCIDENT_REQUIRES_INVESTIGATION",
            "A %s report may never be merely monitored." % record["incident_type"],
        )
    record["reviewed_at"] = clock.now()
    if vals.get("agency_note") is not None:
        record["agency_note"] = vals["agency_note"]
    if vals["disposition"] == "MONITOR":
        record["status"] = "UNDER_REVIEW"
    else:
        record["status"] = "INVESTIGATION_OPENED"
        provider = store.providers[record["provider_id"]]
        category = (
            "ABUSE" if record["incident_type"] in ABUSE_INCIDENT_TYPES else "RECORDS"
        )
        complaint = new_complaint(
            provider,
            "AGENCY_INCIDENT",
            category,
            record["affected_child_age_group"],
            record["narrative"],
            True,
            None,
            False,
            "P1",
            "SCREENED_IN",
        )
        record["generated_complaint_id"] = complaint["id"]
    store.touch(record)
    return envelope.ok(serialize.report(record))


@bp.post("/licensing/serious-incident-reports/<report_id>/close")
def close_report(report_id):
    authenticate(("LicensingSupervisor",))
    vals = validate.body([F("agency_note", "string", min_len=1, max_len=2000, not_blank=True)])
    record = helpers.need("report", report_id)
    complaint_id = record.get("generated_complaint_id")
    if complaint_id is not None:
        complaint = store.complaints[complaint_id]
        if complaint["status"] not in ("CLOSED", "SCREENED_OUT"):
            raise ApiError(
                "ERR_INVALID_COMPLAINT_STATE",
                "The investigation this report opened is still running.",
            )
    if record["status"] not in ("UNDER_REVIEW", "INVESTIGATION_OPENED"):
        raise ApiError(
            "ERR_INVALID_INCIDENT_STATE",
            "Only a report under review or with an open investigation can be closed.",
        )
    record["status"] = "CLOSED"
    record["closed_at"] = clock.now()
    if vals.get("agency_note") is not None:
        record["agency_note"] = vals["agency_note"]
    store.touch(record)
    return envelope.ok(serialize.report(record))
