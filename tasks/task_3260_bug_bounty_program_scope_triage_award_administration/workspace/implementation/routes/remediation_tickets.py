"""Remediation ticket endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_REPORT_NOT_VALIDATED,
)
from helpers import (
    base_entity, touch, get_body, require_fields, reject_unknown_fields,
    parse_pagination,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import ticket_out
from services import reputation as rep_svc

bp = Blueprint("remediation_tickets", __name__)

CREATE_FIELDS = {"report_id", "external_ref"}
TRANSITION_FIELDS = {"action"}
ACTIONS = {"START", "FIX", "REOPEN", "VERIFY", "WONT_FIX"}
NON_TERMINAL = {"OPEN", "IN_PROGRESS", "FIXED"}


def _get_ticket(tid):
    t = db.remediation_tickets.get(tid)
    if t is None:
        raise_err(ERR_NOT_FOUND, f"RemediationTicket {tid} not found")
    return t


@bp.route("/api/remediation-tickets", methods=["POST"])
def create_ticket():
    require_roles({"ProgramAdmin"})
    body = get_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    require_fields(body, ["report_id", "external_ref"])
    report = db.reports.get(body["report_id"])
    if report is None:
        raise_err(ERR_NOT_FOUND, f"Report {body['report_id']} not found")
    if report["status"] != "VALIDATED":
        raise_err(ERR_REPORT_NOT_VALIDATED, "Report is not VALIDATED")
    for t in db.remediation_tickets.values():
        if t["report_id"] == report["id"] and t["status"] in NON_TERMINAL:
            raise_err(ERR_INVALID_STATE, "A non-terminal ticket already exists")
    program = db.programs[report["program_id"]]
    now = clock.now()
    t = base_entity()
    t.update(
        {
            "report_id": report["id"],
            "external_ref": body["external_ref"],
            "status": "OPEN",
            "due_at": clock.iso(now + timedelta(days=program["resolution_sla_days"])),
            "verified_at": None,
        }
    )
    db.remediation_tickets[t["id"]] = t
    return success_object(ticket_out(t), 201)


@bp.route("/api/remediation-tickets/<remediation_ticket_id>", methods=["GET"])
def read_ticket(remediation_ticket_id):
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    return success_object(ticket_out(_get_ticket(remediation_ticket_id)))


@bp.route("/api/remediation-tickets", methods=["GET"])
def list_tickets():
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    limit, offset = parse_pagination(request.args)
    items = list(db.remediation_tickets.values())
    for f in ("report_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [t for t in items if str(t.get(f)) == val]
    items.sort(key=lambda t: t["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ticket_out(t) for t in page], limit, offset, total)


@bp.route("/api/remediation-tickets/<remediation_ticket_id>/transition", methods=["POST"])
def transition_ticket(remediation_ticket_id):
    require_roles({"ProgramAdmin"})
    t = _get_ticket(remediation_ticket_id)
    body = get_body()
    reject_unknown_fields(body, TRANSITION_FIELDS)
    require_fields(body, ["action"])
    action = body["action"]
    if action not in ACTIONS:
        raise_err(ERR_INVALID_REQUEST, "Invalid action")
    st = t["status"]

    if action == "START":
        if st != "OPEN":
            raise_err(ERR_INVALID_STATE, f"Cannot START ticket in {st}")
        t["status"] = "IN_PROGRESS"
    elif action == "FIX":
        if st != "IN_PROGRESS":
            raise_err(ERR_INVALID_STATE, f"Cannot FIX ticket in {st}")
        t["status"] = "FIXED"
    elif action == "REOPEN":
        if st != "FIXED":
            raise_err(ERR_INVALID_STATE, f"Cannot REOPEN ticket in {st}")
        t["status"] = "IN_PROGRESS"
    elif action == "WONT_FIX":
        if st not in ("OPEN", "IN_PROGRESS"):
            raise_err(ERR_INVALID_STATE, f"Cannot WONT_FIX ticket in {st}")
        t["status"] = "WONT_FIX"
    elif action == "VERIFY":
        if st != "FIXED":
            raise_err(ERR_INVALID_STATE, f"Cannot VERIFY ticket in {st}")
        report = db.reports[t["report_id"]]
        if report["status"] != "VALIDATED":
            raise_err(ERR_INVALID_STATE, "Linked report is not VALIDATED")
        now = clock.now()
        t["status"] = "VERIFIED"
        t["verified_at"] = clock.iso(now)
        # cascade hop 1: report VALIDATED -> RESOLVED
        report["status"] = "RESOLVED"
        report["resolved_at"] = clock.iso(now)
        touch(report)
        # cascade hop 2+3: reputation delta by severity; tier recompute
        researcher = db.researchers[report["researcher_id"]]
        rep_svc.apply_resolution_delta(researcher, report["severity_final"])
        touch(researcher)
    touch(t)
    return success_object(ticket_out(t))
