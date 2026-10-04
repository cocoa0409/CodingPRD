"""Docent assignments (PRD 3.3): create with eligibility gates, list, read,
and docent self-confirm (which triggers waitlist promotion)."""

from flask import Blueprint

import calc
import constants
import db
import serializers
import util
from envelope import listing, success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("docent_assignments", __name__)

ASSIGNMENT_READ_ROLES = ["PlatformAdmin", "ProgramCoordinator", "Docent"]


@bp.post("/campus/education-programs/<pid>/docent-assignments")
def create_assignment(pid):
    _uid, role = auth()
    require_role(role, ["ProgramCoordinator"])
    program = get_or_404("education_programs", pid, "EducationProgram")  # (3)
    b = util.body()
    # (4) body FK existence
    docent_id = b.get("docent_id")
    docent = None
    if docent_id is not None:
        docent = get_or_404("docents", docent_id, "Docent")
    # State gate: assigning against a cancelled program is rejected.
    if program["status"] != "SCHEDULED":
        fail("ERR_PROGRAM_NOT_SCHEDULED", "The program is not SCHEDULED")
    # (9) request shape
    if docent_id is None:
        fail("ERR_INVALID_REQUEST", "Missing required field: docent_id")
    service_date = util.req_date(b, "service_date")
    # The service date must fall on the program's weekly recurrence day.
    if util.weekday_code(util.parse_date(service_date)) != program["day_of_week"]:
        fail(
            "ERR_PROGRAM_DAY_MISMATCH",
            "service_date does not fall on the program's day_of_week",
        )
    # (12) docent eligibility: certification meets the requirement, docent is
    # active, and the docent is not already assigned to another SCHEDULED
    # program on the same service date.
    if (
        constants.CERTIFICATION_RANK[docent["certification_level"]]
        < constants.CERTIFICATION_RANK[program["required_docent_certification"]]
    ):
        fail("ERR_DOCENT_NOT_CERTIFIED", "Docent certification is below the program requirement")
    if not docent["active"]:
        fail("ERR_DOCENT_NOT_CERTIFIED", "Docent is not active")
    for a in db.STORE["docent_assignments"].values():
        if (
            a["docent_id"] == docent["id"]
            and a["service_date"] == service_date
            and a["program_id"] != program["id"]
            and a["status"] in ("ASSIGNED", "CONFIRMED")
        ):
            other = db.STORE["education_programs"].get(a["program_id"])
            if other is not None and other["status"] == "SCHEDULED":
                fail(
                    "ERR_DOCENT_NOT_CERTIFIED",
                    "Docent is already assigned to another scheduled program on that date",
                )
    a = db.new_entity(
        {
            "program_id": program["id"],
            "docent_id": docent["id"],
            "service_date": service_date,
            "status": "ASSIGNED",
        }
    )
    db.STORE["docent_assignments"][a["id"]] = a
    return success(serializers.docent_assignment(a), 201)


@bp.get("/campus/docent-assignments")
def list_assignments():
    _uid, role = auth()
    require_role(role, ASSIGNMENT_READ_ROLES)
    limit, offset = util.pagination()
    f_program = util.request.args.get("program_id")
    f_docent = util.request.args.get("docent_id")
    rows = []
    for a in db.all_sorted("docent_assignments"):
        if f_program is not None and a["program_id"] != f_program:
            continue
        if f_docent is not None and a["docent_id"] != f_docent:
            continue
        rows.append(a)
    page = rows[offset : offset + limit]
    return listing([serializers.docent_assignment(a) for a in page], limit, offset, len(rows))


@bp.get("/campus/docent-assignments/<aid>")
def get_assignment(aid):
    _uid, role = auth()
    require_role(role, ASSIGNMENT_READ_ROLES)
    a = get_or_404("docent_assignments", aid, "DocentAssignment")
    return success(serializers.docent_assignment(a))


@bp.post("/campus/docent-assignments/<aid>/confirm")
def confirm_assignment(aid):
    uid, role = auth()
    require_role(role, ["Docent"])
    a = get_or_404("docent_assignments", aid, "DocentAssignment")
    # Ownership (PRD 2.1): a Docent confirms only their own assignment.
    if a["docent_id"] != uid:
        fail("ERR_UNAUTHORIZED_ROLE", "A docent may confirm only their own assignment")
    if a["status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE", "Only an ASSIGNED assignment can be confirmed")
    # Precondition: the program is still SCHEDULED (unreachable in practice:
    # cancelling a program releases its ASSIGNED assignments).
    program = db.STORE["education_programs"].get(a["program_id"])
    if program is None or program["status"] != "SCHEDULED":
        fail("ERR_PROGRAM_NOT_SCHEDULED", "The program is not SCHEDULED")
    a["status"] = "CONFIRMED"
    db.touch(a)
    # Confirmation re-evaluates the waitlist for (program, service_date).
    calc.promote_waitlist(a["program_id"], a["service_date"])
    return success(serializers.docent_assignment(a))
