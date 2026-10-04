"""Report endpoints: submit (INTERIM/FINAL), list, and the review loop
(ACCEPT / REQUEST_REVISION / RESUBMIT)."""

from flask import Blueprint, request

import domain
import envelope
import serialize
from auth import auth, require_roles, check_owner
from constants import (
    ROLE_APPLICANT,
    ROLE_PROGRAM_OFFICER,
    ROLE_HOST_COMMISSION,
    ROLE_PLATFORM_ADMIN,
)
from errors import ApiError
from store import STORE, stamp_new, bump, now, now_iso
from timeutil import parse_iso
from validate import (
    body,
    check_unknown,
    req,
    as_text,
    as_enum,
    pagination,
    page_slice,
    V,
)

bp = Blueprint("reports", __name__)

REPORT_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_PROGRAM_OFFICER, ROLE_HOST_COMMISSION, ROLE_APPLICANT)
REPORT_TYPES = ("INTERIM", "FINAL")
REPORT_ACTIONS = ("ACCEPT", "REQUEST_REVISION", "RESUBMIT")


@bp.post("/exchange/grants/<gid>/reports")
def create_report(gid):
    user, role = auth()
    require_roles(role, [ROLE_APPLICANT])
    grant = STORE.grants.get(gid)
    if grant is None:
        raise ApiError("ERR_GRANT_NOT_FOUND", 404, "No grant with the given id")
    check_owner(role, user, domain.applicant_of_grant(grant))
    payload = body()
    report_type = as_enum(req(payload, "report_type"), "report_type", REPORT_TYPES)
    clock = now()
    # Priority 8: a FINAL report is accepted only once the clock has reached
    # end_date, or when the grant is already COMPLETED / TERMINATED_EARLY.
    if report_type == "FINAL" and grant["status"] not in ("COMPLETED", "TERMINATED_EARLY"):
        if grant["end_date"] is None or clock < parse_iso(grant["end_date"]):
            raise ApiError(
                "ERR_REPORT_WINDOW_INVALID",
                409,
                "FINAL report submitted before the grant end_date",
            )
    check_unknown(payload, {"report_type", "content"})
    content = as_text(req(payload, "content"), "content")
    # Priority 9: one report per (grant, report_type).
    for r in STORE.reports.values():
        if r["grant_id"] == gid and r["report_type"] == report_type:
            raise ApiError(
                "ERR_DUPLICATE_REPORT",
                409,
                "A report of this type already exists for this grant",
            )
    # Priority 10: reports file only while the grant is ACTIVE or SUSPENDED.
    if grant["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(
            "ERR_GRANT_NOT_ACTIVE",
            409,
            "Report submission requires the grant to be ACTIVE or SUSPENDED",
        )
    # Lateness: submitted_at strictly after the applicable due date.
    due = parse_iso(
        grant["interim_report_due_date"]
        if report_type == "INTERIM"
        else grant["final_report_due_date"]
    )
    late = clock > due
    report = {
        "grant_id": gid,
        "report_type": report_type,
        "content": content,
        "status": "SUBMITTED",
        "submitted_at": now_iso(),
        "late": late,
        "revision_note": None,
    }
    stamp_new(report)
    STORE.reports[report["id"]] = report
    if late:
        # A late first submission adds one compliance strike, exactly once.
        grant["compliance_strikes"] += 1
        bump(grant)
    return envelope.ok(serialize.report_out(report), 201)


@bp.get("/exchange/grants/<gid>/reports")
def list_reports(gid):
    user, role = auth()
    require_roles(role, REPORT_READ_ROLES)
    grant = STORE.grants.get(gid)
    if grant is None:
        raise ApiError("ERR_GRANT_NOT_FOUND", 404, "No grant with the given id")
    check_owner(role, user, domain.applicant_of_grant(grant))
    limit, offset = pagination()
    items = [r for r in STORE.reports.values() if r["grant_id"] == gid]
    wanted = request.args.get("report_type")
    if wanted is not None:
        items = [r for r in items if r["report_type"] == wanted]
    page, total = page_slice(items, limit, offset)
    return envelope.ok_list([serialize.report_out(r) for r in page], total, limit, offset)


@bp.post("/exchange/reports/<rid>/transition")
def report_transition(rid):
    user, role = auth()
    require_roles(role, [ROLE_PROGRAM_OFFICER, ROLE_APPLICANT])
    payload = body()
    action = payload.get("action")
    # Priority 2: action-family role binding for known actions.
    if isinstance(action, str):
        if action in ("ACCEPT", "REQUEST_REVISION"):
            if role != ROLE_PROGRAM_OFFICER:
                raise ApiError("ERR_UNAUTHORIZED", 403, "%s is a ProgramOfficer action" % action)
        elif action == "RESUBMIT":
            if role != ROLE_APPLICANT:
                raise ApiError("ERR_UNAUTHORIZED", 403, "RESUBMIT is an Applicant action")

    # Priority 3: path existence precedes every other domain check (PRD 2.9).
    report = STORE.reports.get(rid)
    if report is None:
        raise ApiError("ERR_REPORT_NOT_FOUND", 404, "No report with the given id")
    check_owner(role, user, domain.applicant_of_report(report))

    if action is None:
        raise V("Missing required field: action")
    check_unknown(payload, {"action", "revision_note", "content"})
    if action not in REPORT_ACTIONS:
        raise V("Unknown action for report transition: %r" % action)
    if action == "ACCEPT":
        if report["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Only a SUBMITTED report can be accepted")
        report["status"] = "ACCEPTED"
    elif action == "REQUEST_REVISION":
        if report["status"] != "SUBMITTED":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Only a SUBMITTED report can be sent back for revision"
            )
        report["status"] = "NEEDS_REVISION"
        note = payload.get("revision_note")
        if note is not None:
            report["revision_note"] = as_text(note, "revision_note")
    else:  # RESUBMIT
        if report["status"] != "NEEDS_REVISION":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Only a NEEDS_REVISION report can be resubmitted"
            )
        report["status"] = "SUBMITTED"
        new_content = payload.get("content")
        if new_content is not None:
            report["content"] = as_text(new_content, "content")
        # submitted_at never moves: lateness is fixed at first submission.
    bump(report)
    return envelope.ok(serialize.report_out(report))
