from flask import Blueprint

import db
import services
from core import (actor, auth, body, fail, get_enum, get_int, get_str, now_instant, ok,
                  pagination, paginate, q_enum, sorted_rows)

bp = Blueprint("programs", __name__)

PROGRAM_TYPES = ("SSP_GREEN", "SSP_YELLOW", "SSP_RED", "STUDBOOK_ONLY")
PLAN_STATUSES = ("DRAFT", "PUBLISHED", "CYCLE_CLOSED")


@bp.post("/species-programs")
@auth("AccreditationAdmin")
def create_program():
    b = body()
    taxon = get_str(b, "taxon_name", required=True)
    program_type = get_enum(b, "program_type", PROGRAM_TYPES, required=True)
    target = get_int(b, "target_population_size", required=True, minimum=1)
    keeper = get_str(b, "studbook_keeper_name", required=True)

    rec = db.insert(db.programs, {
        "taxon_name": taxon,
        "program_type": program_type,
        "target_population_size": target,
        "studbook_keeper_name": keeper,
        "plan_status": "DRAFT",
        "current_plan_cycle": 1,
        "cycle_closed_on": None,
    })
    return ok(services.program_out(rec), 201)


@bp.post("/species-programs/<program_id>/publish-plan")
@auth("ProgramCoordinator")
def publish_plan(program_id):
    b = body()
    get_str(b, "publication_note")
    program = db.get_program(program_id)
    if actor() != program["id"]:
        fail("ERR_ACTOR_SCOPE_VIOLATION")
    if program["plan_status"] == "CYCLE_CLOSED":
        program["current_plan_cycle"] += 1
    program["plan_status"] = "PUBLISHED"
    program["cycle_closed_on"] = None
    db.touch(program)
    return ok(services.program_out(program))


@bp.get("/species-programs/<program_id>")
@auth()
def read_program(program_id):
    return ok(services.program_out(db.get_program(program_id)))


@bp.get("/species-programs")
@auth()
def list_programs():
    limit, offset = pagination()
    program_type = q_enum("program_type", PROGRAM_TYPES)
    plan_status = q_enum("plan_status", PLAN_STATUSES)
    rows = list(db.programs.values())
    if program_type is not None:
        rows = [r for r in rows if r["program_type"] == program_type]
    if plan_status is not None:
        rows = [r for r in rows if r["plan_status"] == plan_status]
    return paginate(sorted_rows(rows), limit, offset, services.program_out)
