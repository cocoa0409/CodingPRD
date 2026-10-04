"""Compliance domain: ComplianceAttestations (with lazy OVERDUE derivation)
and AuditReports (PRD section 3.9)."""
from datetime import date

from flask import Blueprint, g, request

from auth import ROLES, require_roles
from clock import CLOCK, render_date, render_ts, render_ts3
from envelope import ok
from errors import fail
from participants import has_unresolved_enforcement
from store import DB, add_record, touch
from validation import (
    get_body,
    list_response,
    require_date,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("compliance", __name__)

ATTESTATION_STATES = ("PENDING", "SUBMITTED", "ACCEPTED", "REJECTED", "OVERDUE")
AUDIT_STATES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def maybe_flip_overdue(attestation):
    """OVERDUE is derived lazily: any read/write of the attestation while it
    is PENDING and the logical date is after due_date flips it, and the flip
    is persisted."""
    if attestation["status"] == "PENDING" and CLOCK.today() > attestation["due_date"]:
        attestation["status"] = "OVERDUE"


def serialize_attestation(a):
    maybe_flip_overdue(a)
    return {
        "id": a["id"],
        "participant_id": a["participant_id"],
        "period_year": a["period_year"],
        "due_date": render_date(a["due_date"]),
        "submitted_at": render_ts(a["submitted_at"]),
        "late_submission": a["late_submission"],
        "attestation_text": a["attestation_text"],
        "status": a["status"],
        "created_at": render_ts3(a["created_at"]),
        "updated_at": render_ts3(a["updated_at"]),
        "version": a["version"],
    }


def serialize_audit(a):
    return {
        "id": a["id"],
        "participant_id": a["participant_id"],
        "start_date": render_date(a["start_date"]),
        "end_date": render_date(a["end_date"]),
        "findings_count": a["findings_count"],
        "created_by_user_id": a["created_by_user_id"],
        "completed_by_user_id": a["completed_by_user_id"],
        "status": a["status"],
        "created_at": render_ts3(a["created_at"]),
        "updated_at": render_ts3(a["updated_at"]),
        "version": a["version"],
    }


# ---------------------------------------------------------------------------
# Compliance attestations
# ---------------------------------------------------------------------------


@bp.post("/attestations")
@require_roles("PlatformAdmin")
def create_attestation():
    body = get_body()
    participant_id = require_str(body, "participant_id")
    period_year = require_int(body, "period_year")
    try:
        due_date = date(period_year + 1, 3, 1)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "period_year is out of range")
    if participant_id not in DB.participants:
        fail("ERR_NOT_FOUND", "Participant %s not found" % participant_id)
    for a in DB.compliance_attestations.values():
        if a["participant_id"] == participant_id and a["period_year"] == period_year:
            fail(
                "ERR_DUPLICATE_RESOURCE",
                "An attestation already exists for this participant and year",
            )
    rec = add_record(
        "compliance_attestations",
        {
            "participant_id": participant_id,
            "period_year": period_year,
            # due_date is March 1 of the year following period_year.
            "due_date": due_date,
            "submitted_at": None,
            "late_submission": False,
            "attestation_text": None,
            "status": "PENDING",
        },
    )
    return ok(serialize_attestation(rec), 201)


@bp.get("/attestations/<attestation_id>")
@require_roles(*ROLES)
def get_attestation(attestation_id):
    a = DB.compliance_attestations.get(attestation_id)
    if a is None:
        fail("ERR_NOT_FOUND", "Attestation %s not found" % attestation_id)
    return ok(serialize_attestation(a))


@bp.get("/attestations")
@require_roles(*ROLES)
def list_attestations():
    # Lazy OVERDUE derivation runs on reads, including list reads, before the
    # status filter is applied.
    for a in DB.compliance_attestations.values():
        maybe_flip_overdue(a)
    filters = []
    participant_id = request.args.get("participant_id")
    if participant_id is not None:
        filters.append(("participant_id", participant_id))
    status = request.args.get("status")
    if status is not None:
        filters.append(("status", status))
    return list_response(
        DB.compliance_attestations.values(), serialize_attestation, filters
    )


@bp.post("/attestations/<attestation_id>/transition")
@require_roles("PlatformAdmin", "ParticipantOfficer")
def transition_attestation(attestation_id):
    a = DB.compliance_attestations.get(attestation_id)
    if a is None:
        fail("ERR_NOT_FOUND", "Attestation %s not found" % attestation_id)
    maybe_flip_overdue(a)
    body = get_body()
    to_state = require_enum(body, "to_state", ATTESTATION_STATES)

    if to_state == "SUBMITTED":
        if g.user_role != "ParticipantOfficer":
            fail("ERR_FORBIDDEN", "Only the participant's officer may submit")
        if a["participant_id"] != g.user_id:
            fail("ERR_FORBIDDEN", "Attestation belongs to another participant")
        attestation_text = require_str(body, "attestation_text")
        if a["status"] not in ("PENDING", "OVERDUE", "REJECTED"):
            fail("ERR_INVALID_STATE", "Cannot submit from %s" % a["status"])
        a["status"] = "SUBMITTED"
        a["attestation_text"] = attestation_text
        a["submitted_at"] = CLOCK.now()
        a["late_submission"] = CLOCK.today() > a["due_date"]
    elif to_state in ("ACCEPTED", "REJECTED"):
        if g.user_role != "PlatformAdmin":
            fail("ERR_FORBIDDEN", "Only a PlatformAdmin may accept or reject")
        if a["status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE", "Attestation is not SUBMITTED")
        if to_state == "ACCEPTED":
            # Gates in the documented order: unresolved enforcement first.
            if has_unresolved_enforcement(a["participant_id"]):
                fail(
                    "ERR_UNRESOLVED_ENFORCEMENT",
                    "Participant has enforcement actions in ISSUED or CONTESTED",
                )
            year_start = date(a["period_year"], 1, 1)
            has_qualifying_audit = any(
                au["participant_id"] == a["participant_id"]
                and au["status"] == "COMPLETED"
                and au["end_date"] >= year_start
                for au in DB.audit_reports.values()
            )
            if not has_qualifying_audit:
                fail(
                    "ERR_AUDIT_REQUIRED",
                    "No COMPLETED audit with end_date on or after %s" % year_start,
                )
            a["status"] = "ACCEPTED"
        else:
            a["status"] = "REJECTED"
    else:  # PENDING / OVERDUE are never legal target states
        fail("ERR_INVALID_STATE", "Cannot transition to %s" % to_state)

    touch(a)
    return ok(serialize_attestation(a))


# ---------------------------------------------------------------------------
# Audit reports
# ---------------------------------------------------------------------------


@bp.post("/audits")
@require_roles("Auditor")
def create_audit():
    body = get_body()
    participant_id = require_str(body, "participant_id")
    start_date = require_date(body, "start_date")
    end_date = require_date(body, "end_date")
    if end_date < start_date:
        fail("ERR_INVALID_REQUEST", "end_date must be >= start_date")
    if participant_id not in DB.participants:
        fail("ERR_NOT_FOUND", "Participant %s not found" % participant_id)
    # Closed-interval [start_date, end_date] overlap with another SCHEDULED or
    # IN_PROGRESS audit of the same participant; a shared boundary date IS an
    # overlap because both ends are inclusive.
    for au in DB.audit_reports.values():
        if au["participant_id"] != participant_id:
            continue
        if au["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if start_date <= au["end_date"] and au["start_date"] <= end_date:
            fail(
                "ERR_AUDIT_WINDOW_OVERLAP",
                "Engagement window overlaps another open audit of this participant",
            )
    rec = add_record(
        "audit_reports",
        {
            "participant_id": participant_id,
            "start_date": start_date,
            "end_date": end_date,
            "findings_count": None,
            "created_by_user_id": g.user_id,
            "completed_by_user_id": None,
            "status": "SCHEDULED",
        },
    )
    return ok(serialize_audit(rec), 201)


@bp.get("/audits/<audit_id>")
@require_roles(*ROLES)
def get_audit(audit_id):
    a = DB.audit_reports.get(audit_id)
    if a is None:
        fail("ERR_NOT_FOUND", "Audit report %s not found" % audit_id)
    return ok(serialize_audit(a))


@bp.get("/audits")
@require_roles(*ROLES)
def list_audits():
    filters = []
    participant_id = request.args.get("participant_id")
    if participant_id is not None:
        filters.append(("participant_id", participant_id))
    status = request.args.get("status")
    if status is not None:
        filters.append(("status", status))
    return list_response(DB.audit_reports.values(), serialize_audit, filters)


@bp.post("/audits/<audit_id>/transition")
@require_roles("Auditor")
def transition_audit(audit_id):
    a = DB.audit_reports.get(audit_id)
    if a is None:
        fail("ERR_NOT_FOUND", "Audit report %s not found" % audit_id)
    body = get_body()
    to_state = require_enum(body, "to_state", AUDIT_STATES)

    if to_state == "IN_PROGRESS":
        if a["status"] != "SCHEDULED":
            fail("ERR_INVALID_STATE", "Cannot transition %s to IN_PROGRESS" % a["status"])
        if CLOCK.today() < a["start_date"]:
            fail("ERR_AUDIT_NOT_STARTED", "Audit start_date has not been reached")
        a["status"] = "IN_PROGRESS"
    elif to_state == "COMPLETED":
        findings_count = require_int(body, "findings_count")
        if findings_count < 0:
            fail("ERR_INVALID_REQUEST", "findings_count must be >= 0")
        if a["status"] != "IN_PROGRESS":
            fail("ERR_INVALID_STATE", "Cannot transition %s to COMPLETED" % a["status"])
        # Segregation of duties: the creating auditor may not complete the
        # engagement.
        if a["created_by_user_id"] == g.user_id:
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "The creating auditor may not complete this audit",
            )
        if CLOCK.today() < a["start_date"]:
            fail("ERR_AUDIT_NOT_STARTED", "Audit start_date has not been reached")
        a["status"] = "COMPLETED"
        a["findings_count"] = findings_count
        a["completed_by_user_id"] = g.user_id
    elif to_state == "CANCELLED":
        if a["status"] != "SCHEDULED":
            fail("ERR_INVALID_STATE", "Cannot transition %s to CANCELLED" % a["status"])
        a["status"] = "CANCELLED"
    else:  # SCHEDULED is never a legal target state
        fail("ERR_INVALID_STATE", "Cannot transition to SCHEDULED")

    touch(a)
    return ok(serialize_audit(a))
