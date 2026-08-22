"""Punch list, warranty coverage and the callback service."""
from flask import Blueprint

from errors import AppError
from store import db, base_row, now, bump, ordered
from util import (
    authorize, check_staff_identity, parse_body, ok, ok_list, paginate, qfilter,
    req_str, opt_str, opt_id, req_enum, add_days,
)
from routes.common import fetch, own_project, own_subcontractor
from services.constants import (
    DEFECT_PHASES, DEFECT_SEVERITIES, DEFECT_CATEGORIES, DEFECT_RESPONSE_DAYS,
)
from services.calc import warranty_coverage

bp = Blueprint("defects", __name__)

DEFECT_READ_ROLES = ["PlatformAdmin", "ProjectManager", "Controller", "Client",
                     "Subcontractor"]
TRIAGE_DECISIONS = ("ASSIGN", "DENY")
CLIENT_REVIEW_DECISIONS = ("VERIFY", "REJECT", "WAIVE")


@bp.post("/defect-tickets")
def create_defect_ticket():
    user_id, role = authorize(["Client", "ProjectManager"])
    body = parse_body()
    project_id = req_str(body, "project_id")
    phase = req_enum(body, "phase", DEFECT_PHASES)
    room = req_str(body, "room")
    description = req_str(body, "description")
    severity = req_enum(body, "severity", DEFECT_SEVERITIES)
    category = req_enum(body, "category", DEFECT_CATEGORIES)
    source_schedule_task_id = opt_id(body, "source_schedule_task_id")

    # ladder step 6
    project = db.projects.get(project_id)
    if project is None:
        raise AppError("ERR_PROJECT_NOT_FOUND")
    if source_schedule_task_id is not None and source_schedule_task_id not in db.schedule_tasks:
        raise AppError("ERR_SCHEDULE_TASK_NOT_FOUND")

    check_staff_identity(user_id, role)
    own_project(project, user_id, role)

    row = base_row()
    row.update({
        "project_id": project_id,
        "responsible_subcontractor_id": None,
        "source_schedule_task_id": source_schedule_task_id,
        "phase": phase,
        "room": room,
        "description": description,
        "severity": severity,
        "category": category,
        "reported_at": now(),
        "coverage_anchor": "NONE",
        "coverage_end_at": None,
        "coverage_result": "NOT_APPLICABLE",
        "status": "OPEN",
        "rework_count": 0,
        "response_due_at": None,
        "completion_note": None,
        "assigned_at": None,
        "resolved_at": None,
    })
    anchor, coverage_end_at, result = warranty_coverage(row, project)
    row["coverage_anchor"] = anchor
    row["coverage_end_at"] = coverage_end_at
    row["coverage_result"] = result

    db.defect_tickets[row["id"]] = row
    return ok(row, 201)


@bp.get("/defect-tickets/<ticket_id>")
def get_defect_ticket(ticket_id):
    user_id, role = authorize(DEFECT_READ_ROLES)
    ticket = fetch("defect_tickets", ticket_id)
    check_staff_identity(user_id, role)
    return ok(ticket, 200)


@bp.get("/defect-tickets")
def list_defect_tickets():
    user_id, role = authorize(DEFECT_READ_ROLES)
    check_staff_identity(user_id, role)
    rows = ordered(db.defect_tickets.values())
    for name in ("project_id", "responsible_subcontractor_id", "source_schedule_task_id",
                 "phase", "status"):
        value = qfilter(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.post("/defect-tickets/<ticket_id>/triage")
def triage_defect_ticket(ticket_id):
    user_id, role = authorize(["ProjectManager"])
    ticket = fetch("defect_tickets", ticket_id)
    body = parse_body()
    decision = req_enum(body, "decision", TRIAGE_DECISIONS)
    responsible_subcontractor_id = opt_id(body, "responsible_subcontractor_id")

    if (decision == "ASSIGN" and responsible_subcontractor_id is None
            and ticket.get("responsible_subcontractor_id") is None):
        raise AppError("ERR_INVALID_REQUEST",
                       "responsible_subcontractor_id is required to assign a defect.")

    # ladder step 6
    if (responsible_subcontractor_id is not None
            and responsible_subcontractor_id not in db.subcontractors):
        raise AppError("ERR_SUBCONTRACTOR_NOT_FOUND")

    check_staff_identity(user_id, role)

    # ladder step 10
    if decision == "ASSIGN":
        if ticket["status"] not in ("OPEN", "REJECTED"):
            raise AppError("ERR_DEFECT_INVALID_STATE")
    else:
        if ticket["status"] != "OPEN":
            raise AppError("ERR_DEFECT_INVALID_STATE")

    if decision == "ASSIGN":
        # ladder step 18
        if ticket["phase"] == "WARRANTY" and ticket["coverage_result"] != "COVERED":
            raise AppError("ERR_DEFECT_NOT_COVERED")

        reworked = ticket["status"] == "REJECTED"
        if responsible_subcontractor_id is not None:
            ticket["responsible_subcontractor_id"] = responsible_subcontractor_id
        ticket["assigned_at"] = now()
        ticket["response_due_at"] = add_days(ticket["assigned_at"],
                                             DEFECT_RESPONSE_DAYS[ticket["severity"]])
        ticket["status"] = "ASSIGNED"
        if reworked:
            ticket["rework_count"] = (ticket.get("rework_count") or 0) + 1
        bump(ticket)
        return ok(ticket, 200)

    # DENY - ladder step 19
    if ticket["phase"] != "WARRANTY" or ticket["coverage_result"] not in (
            "OUT_OF_COVERAGE", "EXCLUDED"):
        raise AppError("ERR_DEFECT_PHASE_MISMATCH")

    ticket["status"] = "DENIED"
    ticket["resolved_at"] = now()
    bump(ticket)
    return ok(ticket, 200)


@bp.post("/defect-tickets/<ticket_id>/submit-for-review")
def submit_defect_for_review(ticket_id):
    user_id, role = authorize(["Subcontractor"])
    ticket = fetch("defect_tickets", ticket_id)
    body = parse_body()
    completion_note = opt_str(body, "completion_note")

    # ladder step 8
    own_subcontractor(ticket.get("responsible_subcontractor_id"), user_id, role)

    # ladder step 10
    if ticket["status"] != "ASSIGNED":
        raise AppError("ERR_DEFECT_INVALID_STATE")

    ticket["completion_note"] = completion_note
    ticket["status"] = "READY_FOR_REVIEW"
    bump(ticket)
    return ok(ticket, 200)


@bp.post("/defect-tickets/<ticket_id>/client-review")
def client_review_defect(ticket_id):
    user_id, role = authorize(["Client"])
    ticket = fetch("defect_tickets", ticket_id)
    body = parse_body()
    decision = req_enum(body, "decision", CLIENT_REVIEW_DECISIONS)

    project = db.projects.get(ticket["project_id"])
    own_project(project, user_id, role)

    # ladder step 10
    if decision == "WAIVE":
        if ticket["status"] != "OPEN":
            raise AppError("ERR_DEFECT_INVALID_STATE")
    else:
        if ticket["status"] != "READY_FOR_REVIEW":
            raise AppError("ERR_DEFECT_INVALID_STATE")

    if decision == "WAIVE":
        # ladder step 19
        if ticket["phase"] != "PUNCH" or ticket["severity"] != "COSMETIC":
            raise AppError("ERR_DEFECT_PHASE_MISMATCH")
        ticket["status"] = "WAIVED"
        ticket["resolved_at"] = now()
        bump(ticket)
        return ok(ticket, 200)

    if decision == "VERIFY":
        ticket["status"] = "VERIFIED"
        ticket["resolved_at"] = now()
        bump(ticket)
        return ok(ticket, 200)

    ticket["status"] = "REJECTED"
    bump(ticket)
    return ok(ticket, 200)
