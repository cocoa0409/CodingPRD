"""Verification engagement endpoints (PRD 3.7, 2.11)."""
from datetime import timedelta

from flask import Blueprint

import calc
import store
import validation as v
from auth import (OFFICER, PRO_ADMIN, REGULATOR, VERIFIER, endpoint, must,
                  new_row, require_assigned_verifier, touch, user_id)
from envelope import ok_entity, ok_list
from errors import fail
from routes.common import enum_filter, listing, str_filter

bp = Blueprint("engagements", __name__)

ALL = [REGULATOR, OFFICER, PRO_ADMIN, VERIFIER]
OPEN_ENGAGEMENTS = ("ASSIGNED", "IN_PROGRESS")


def windows_intersect(start, end, other_start, other_end):
    """Closed windows, the existing one widened by the two-day buffer."""
    widened_start = other_start - timedelta(days=calc.VERIFIER_BUFFER_DAYS)
    widened_end = other_end + timedelta(days=calc.VERIFIER_BUFFER_DAYS)
    return start <= widened_end and widened_start <= end


def previous_verifier(registration_id):
    """Verifier who opined on the registration's immediately preceding FINALIZED report."""
    finalized = [
        r
        for r in calc.reports_of(registration_id)
        if r["submission_status"] == "FINALIZED"
    ]
    if not finalized:
        return None
    report = finalized[-1]
    opined = [
        e
        for e in calc.engagements_of(report["id"])
        if e["status"] == "OPINION_ISSUED" and e["opinion"] is not None
    ]
    if not opined:
        return None
    return opined[-1]["verifier_user_id"]


@bp.post("/epr/verification-engagements")
@endpoint([REGULATOR])
def create_engagement():
    body = v.body()
    report_id = v.req_str(body, "packaging_report_id")
    verifier = v.req_str(body, "verifier_user_id")
    start = v.req_date(body, "fieldwork_start")
    end = v.req_date(body, "fieldwork_end")
    report = must("reports", report_id)
    if verifier == report["submitted_by_user_id"] or verifier == user_id():
        fail("ERR_SEGREGATION_OF_DUTIES")
    if previous_verifier(report["registration_id"]) == verifier:
        fail("ERR_VERIFIER_ROTATION_REQUIRED")
    # The one-engagement-per-report rule is answered before the report's own
    # position: an open engagement always means the report already sits in
    # UNDER_VERIFICATION, so checking the position first would make
    # ERR_ENGAGEMENT_ALREADY_OPEN unreachable (PRD 2.10 priority 5).
    for other in calc.engagements_of(report["id"]):
        if other["status"] in OPEN_ENGAGEMENTS:
            fail("ERR_ENGAGEMENT_ALREADY_OPEN")
    if report["submission_status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED report may be assigned a verifier.")
    overlapping = 0
    for other in store.by_created(store.values("engagements")):
        if other["verifier_user_id"] != verifier:
            continue
        if other["status"] not in OPEN_ENGAGEMENTS:
            continue
        if windows_intersect(start, end, other["_fieldwork_start"], other["_fieldwork_end"]):
            overlapping += 1
    if overlapping >= calc.VERIFIER_MAX_CONCURRENT_ENGAGEMENTS:
        fail("ERR_VERIFIER_CAPACITY_EXCEEDED")
    if end <= start:
        fail("ERR_INVALID_FIELDWORK_WINDOW")
    row = new_row(
        "engagements",
        {
            "packaging_report_id": report["id"],
            "verifier_user_id": verifier,
            "assigned_by_user_id": user_id(),
            "fieldwork_start": start.isoformat(),
            "fieldwork_end": end.isoformat(),
            "status": "ASSIGNED",
            "opinion": None,
            "findings_note": None,
            "round_index": int(report["correction_round"]) + 1,
            "opinion_issued_at": None,
            "_fieldwork_start": start,
            "_fieldwork_end": end,
        },
    )
    report["submission_status"] = "UNDER_VERIFICATION"
    touch(report)
    return ok_entity(row, 201)


@bp.get("/epr/verification-engagements/<eid>")
@endpoint(ALL)
def get_engagement(eid):
    return ok_entity(must("engagements", eid))


@bp.get("/epr/verification-engagements")
@endpoint(ALL)
def list_engagements():
    report_id = str_filter("packaging_report_id")
    verifier = str_filter("verifier_user_id")
    status = enum_filter("status", v.ENGAGEMENT_STATUSES)
    opinion = enum_filter("opinion", v.OPINIONS)
    rows = store.values("engagements")
    if report_id is not None:
        rows = [r for r in rows if r["packaging_report_id"] == report_id]
    if verifier is not None:
        rows = [r for r in rows if r["verifier_user_id"] == verifier]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if opinion is not None:
        rows = [r for r in rows if r["opinion"] == opinion]
    window, limit, offset, total = listing(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/epr/verification-engagements/<eid>/start")
@endpoint([VERIFIER])
def start_fieldwork(eid):
    v.body(required=False)
    engagement = must("engagements", eid)
    report = store.get("reports", engagement["packaging_report_id"])
    if engagement["status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE", "The engagement is not in ASSIGNED.")
    if report["submission_status"] != "UNDER_VERIFICATION":
        fail("ERR_REPORT_NOT_UNDER_VERIFICATION")
    require_assigned_verifier(engagement)
    engagement["status"] = "IN_PROGRESS"
    touch(engagement)
    return ok_entity(engagement)


@bp.post("/epr/verification-engagements/<eid>/issue-opinion")
@endpoint([VERIFIER])
def issue_opinion(eid):
    body = v.body()
    opinion = v.req_enum(body, "opinion", v.OPINIONS)
    note = v.opt_str(body, "findings_note", allow_empty=True)
    engagement = must("engagements", eid)
    report = store.get("reports", engagement["packaging_report_id"])
    if engagement["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "The engagement is not in IN_PROGRESS.")
    if report["submission_status"] != "UNDER_VERIFICATION":
        fail("ERR_REPORT_NOT_UNDER_VERIFICATION")
    acting = user_id()
    if acting == report["submitted_by_user_id"] or acting == engagement["assigned_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    require_assigned_verifier(engagement)
    if opinion in ("QUALIFIED", "ADVERSE") and (note is None or note.strip() == ""):
        fail("ERR_FINDINGS_NOTE_REQUIRED")
    engagement["status"] = "OPINION_ISSUED"
    engagement["opinion"] = opinion
    engagement["findings_note"] = note
    engagement["opinion_issued_at"] = store.fmt_instant(store.clock())
    touch(engagement)
    registration = store.get("registrations", report["registration_id"])
    if opinion == "UNQUALIFIED":
        report["submission_status"] = "VERIFIED"
        touch(report)
        return ok_entity(engagement)
    # QUALIFIED / ADVERSE: the six-hop correction cascade of PRD 3.7.
    period = store.get("reporting_periods", report["reporting_period_id"])
    due = calc.correction_deadline(period)
    report["submission_status"] = "CORRECTION_REQUIRED"
    report["correction_due_at"] = store.fmt_instant(due)
    report["_correction_due_at"] = due
    if report["fee_status"] in ("PROVISIONAL", "FINAL", "INVOICED"):
        report["fee_status"] = "VOIDED"
    touch(report)
    calc.recompute_ytd(registration)
    for invoice in calc.invoices_of(report["id"]):
        if invoice["status"] == "ISSUED":
            invoice["status"] = "VOID"
            invoice["void_reason"] = "REPORT_CORRECTION_REQUIRED"
            touch(invoice)
    producer = store.get("producers", registration["producer_id"])
    calc.recompute_producer_balance(producer)
    calc.set_posture(registration)
    return ok_entity(engagement)
