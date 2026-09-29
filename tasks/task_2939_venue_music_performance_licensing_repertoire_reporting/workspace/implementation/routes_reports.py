"""Setlist reporting and the repertoire gap cascade (PRD 3.8)."""

from flask import Blueprint

import access
import db
import serializers
import services
from core import (
    AFFILIATIONS,
    REJECTION_REASONS,
    REPORT_DISPOSITIONS,
    REPORT_STATUSES,
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_OPERATOR,
    USE_TYPES,
    Ladder,
    P_AUTHORISATION,
    P_BODY_REFERENCE,
    P_DEPARTURE_STATE,
    P_ENTRY_IN_PERIOD,
    P_INTERVAL,
    P_LICENSE_ACTIVE,
    P_REPORT_OVERLAP,
    P_REQUEST_SHAPE,
    authenticate,
    conflict,
    fk_candidate,
    invalid_interval,
    invalid_request,
    not_found,
    paginate,
    query_flag,
    query_str,
    query_enum,
    read_body,
    read_pagination,
    require_owned_venue,
    respond_list,
    respond_object,
    validate_fields,
)

bp = Blueprint("reports", __name__)

REPORT_CREATE_SPEC = [
    ("license_id", "str", {"required": True}),
    ("period_start", "instant", {"required": True}),
    ("period_end", "instant", {"required": True}),
]

ENTRY_SPEC = [
    ("work_title", "str", {"required": True, "min": 1, "max": 200}),
    ("writer_name", "str", {"required": True, "min": 1, "max": 120}),
    ("society_affiliation", "enum", {"required": True, "values": AFFILIATIONS}),
    ("performance_datetime", "instant", {"required": True}),
    ("use_type", "enum", {"required": True, "values": USE_TYPES}),
    ("duration_seconds", "int", {"required": True, "min": 1}),
]

REPORT_REVIEW_SPEC = [
    ("disposition", "enum", {"required": True, "values": REPORT_DISPOSITIONS}),
    ("rejection_reason", "enum", {"nullable": True, "values": REJECTION_REASONS}),
]

OVERLAP_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED")


def period_overlap(license_id, period_start, period_end, exclude_id=None):
    """PRD 2.12 rule 12: REJECTED periods are excluded from the comparison."""
    for other in db.reports_of_license(license_id):
        if other["id"] == exclude_id or other["status"] not in OVERLAP_STATUSES:
            continue
        if period_start < other["period_end"] and other["period_start"] < period_end:
            return other
    return None


@bp.post("/licensing/performance-reports")
def create_report():
    user_id, role = authenticate([ROLE_OPERATOR, ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    body = read_body()
    state = {}

    @ladder.check(P_AUTHORISATION)
    def _ownership():
        license_id = fk_candidate(body, "license_id")
        license_row = db.license_row(license_id) if license_id else None
        if license_row is not None:
            require_owned_venue(role, user_id, license_row["venue_id"])

    @ladder.check(P_BODY_REFERENCE)
    def _body_refs():
        license_id = fk_candidate(body, "license_id")
        if license_id is not None and db.license_row(license_id) is None:
            raise not_found(access.ERR_LICENSE)

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body, REPORT_CREATE_SPEC)

    @ladder.check(P_LICENSE_ACTIVE)
    def _active():
        license_row = db.license_row(state["fields"]["license_id"])
        if license_row["coverage_status"] != "ACTIVE":
            raise conflict(
                "ERR_LICENSE_NOT_ACTIVE", "Only an ACTIVE licence may open a reporting period."
            )

    @ladder.check(P_INTERVAL)
    def _interval():
        if state["fields"]["period_start"] >= state["fields"]["period_end"]:
            raise invalid_interval("period_start must be strictly before period_end.")

    @ladder.check(P_REPORT_OVERLAP)
    def _overlap():
        fields = state["fields"]
        if period_overlap(fields["license_id"], fields["period_start"], fields["period_end"]):
            raise conflict(
                "ERR_REPORT_PERIOD_OVERLAP",
                "Another live report of this licence already covers that period.",
            )

    ladder.run()
    fields = state["fields"]
    row = db.new_row(
        "reports",
        {
            "license_id": fields["license_id"],
            "period_start": fields["period_start"],
            "period_end": fields["period_end"],
            "status": "DRAFT",
            "reported_entry_count": 0,
            "matched_entry_count": 0,
            "uncovered_entry_count": 0,
            "unmatched_share_pct_h": 0,
            "uncovered_share_pct_h": 0,
            "gap_exposure_cents": 0,
            "rejection_reason": None,
            "review_round": 0,
        },
    )
    return respond_object(serializers.report_json(row), 201)


@bp.post("/licensing/performance-reports/<report_id>/setlist-entries")
def create_entry(report_id):
    user_id, role = authenticate([ROLE_OPERATOR, ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    report = access.fetch("reports", report_id, access.ERR_REPORT)
    body = read_body()
    state = {}

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body, ENTRY_SPEC)

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if report["status"] not in ("DRAFT", "REJECTED"):
            raise conflict(
                "ERR_REPORT_STATE_INVALID",
                "Entries may only be appended to a DRAFT or REJECTED report.",
            )

    @ladder.check(P_ENTRY_IN_PERIOD)
    def _in_period():
        instant = state["fields"]["performance_datetime"]
        if not (report["period_start"] <= instant < report["period_end"]):
            raise conflict(
                "ERR_ENTRY_OUTSIDE_PERIOD",
                "performance_datetime must fall inside the report's half-open period.",
            )

    ladder.run()
    fields = state["fields"]
    was_rejected = report["status"] == "REJECTED"
    entry = db.new_thin_row(
        "entries",
        {
            "performance_report_id": report["id"],
            "work_title": fields["work_title"],
            "writer_name": fields["writer_name"],
            "society_affiliation": fields["society_affiliation"],
            "performance_datetime": fields["performance_datetime"],
            "use_type": fields["use_type"],
            "duration_seconds": fields["duration_seconds"],
            "is_matched": False,
            "matched_work_id": None,
            "is_covered": False,
        },
    )
    # reported_entry_count keeps counting everything attached, including the
    # entry that reopens a rejected report (PRD 3.8).
    report["reported_entry_count"] += 1
    if was_rejected:
        services.reopen_report(report)
    else:
        db.touch(report)
    return respond_object(serializers.entry_json(entry), 201)


@bp.post("/licensing/performance-reports/<report_id>/submit")
def submit_report(report_id):
    user_id, role = authenticate([ROLE_OPERATOR, ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    report = access.fetch("reports", report_id, access.ERR_REPORT)
    license_row = db.license_row(report["license_id"])

    @ladder.check(P_LICENSE_ACTIVE)
    def _active():
        if license_row["coverage_status"] != "ACTIVE":
            raise conflict(
                "ERR_LICENSE_NOT_ACTIVE", "Only a report of an ACTIVE licence may be submitted."
            )

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if report["status"] != "DRAFT":
            raise conflict("ERR_REPORT_STATE_INVALID", "Only a DRAFT report may be submitted.")

    @ladder.check(P_REPORT_OVERLAP)
    def _overlap():
        if period_overlap(
            report["license_id"],
            report["period_start"],
            report["period_end"],
            exclude_id=report["id"],
        ):
            raise conflict(
                "ERR_REPORT_PERIOD_OVERLAP",
                "Another live report of this licence already covers that period.",
            )

    ladder.run()
    services.submit_report(report)
    return respond_object(serializers.report_json(report))


@bp.post("/licensing/performance-reports/<report_id>/review")
def review_report(report_id):
    user_id, role = authenticate([ROLE_ADMIN, ROLE_AUDITOR])
    ladder = Ladder(user_id, role)
    report = access.fetch("reports", report_id, access.ERR_REPORT, narrow=False)
    state = {}
    body = read_body()

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        fields = validate_fields(body, REPORT_REVIEW_SPEC)
        if fields["disposition"] == "REJECT" and fields.get("rejection_reason") is None:
            raise invalid_request("REJECT requires a rejection_reason.")
        state["fields"] = fields

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if report["status"] != "SUBMITTED":
            raise conflict("ERR_REPORT_STATE_INVALID", "Only a SUBMITTED report may be reviewed.")

    ladder.run()
    license_row = db.license_row(report["license_id"])
    venue = db.venue(license_row["venue_id"])
    if state["fields"]["disposition"] == "ACCEPT":
        report["status"] = "ACCEPTED"
        db.touch(report)
        license_row["accepted_report_count"] += 1
        db.touch(license_row)
    else:
        report["status"] = "REJECTED"
        report["rejection_reason"] = state["fields"]["rejection_reason"]
        report["review_round"] += 1
        db.touch(report)
    # A REJECTED report leaves the reportable candidate set entirely, so the
    # score falls back to the next most recent SUBMITTED/ACCEPTED report.
    services.recompute_venue(venue, gap_risk=True)
    return respond_object(serializers.report_json(report))


@bp.get("/licensing/performance-reports/<report_id>/setlist-entries")
def list_entries_of_report(report_id):
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
    report = access.fetch("reports", report_id, access.ERR_REPORT)
    limit, offset = read_pagination()
    rows = db.entries_of_report(report["id"])
    page, total = paginate(rows, limit, offset)
    return respond_list([serializers.entry_json(row) for row in page], limit, offset, total)


@bp.get("/licensing/performance-reports")
def list_reports():
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
    limit, offset = read_pagination()
    license_id = query_str("license_id")
    status = query_enum("status", REPORT_STATUSES)
    rows = []
    for row in access.narrow_rows("reports", db.ordered("reports")):
        if license_id is not None and row["license_id"] != license_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return respond_list([serializers.report_json(row) for row in page], limit, offset, total)


@bp.get("/licensing/performance-reports/<report_id>")
def read_report(report_id):
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
    row = access.fetch("reports", report_id, access.ERR_REPORT)
    return respond_object(serializers.report_json(row))


@bp.get("/licensing/setlist-entries")
def list_entries():
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
    limit, offset = read_pagination()
    report_id = query_str("performance_report_id")
    matched_work_id = query_str("matched_work_id")
    is_matched = query_flag("is_matched")
    is_covered = query_flag("is_covered")
    rows = []
    for row in access.narrow_rows("entries", db.ordered("entries")):
        if report_id is not None and row["performance_report_id"] != report_id:
            continue
        if matched_work_id is not None and row["matched_work_id"] != matched_work_id:
            continue
        if is_matched is not None and row["is_matched"] != is_matched:
            continue
        if is_covered is not None and row["is_covered"] != is_covered:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return respond_list([serializers.entry_json(row) for row in page], limit, offset, total)


@bp.get("/licensing/setlist-entries/<setlist_entry_id>")
def read_entry(setlist_entry_id):
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
    row = access.fetch("entries", setlist_entry_id, access.ERR_ENTRY)
    return respond_object(serializers.entry_json(row))
