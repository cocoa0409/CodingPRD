"""MWR programmes and surcharge-funded capital projects (PRD 3.9)."""

from flask import Blueprint

import calculations as calc
import constants as C
import derive
import lookups
import serialize
import validation as V
from db import db, new_record, touch
from envelope import array_response, object_response
from errors import ApiError

bp = Blueprint("governance", __name__)


# --------------------------------------------------------------------------
# MWR programmes
# --------------------------------------------------------------------------


@bp.post("/mwr-programs")
def create_program():
    V.authenticate(("MwrBoardOfficer",))
    body = V.raw_body()
    store_id = V.want_string(body, "store_id", required=True)
    name = V.want_string(body, "name", required=True, min_len=1, max_len=160)
    priority_rank = V.want_int(body, "priority_rank", required=True, minimum=1)
    funding_ceiling_cents = V.want_int(body, "funding_ceiling_cents", required=True, minimum=1)
    status = V.want_enum(body, "status", C.PROGRAM_STATUSES, required=False, default="ACTIVE")

    lookups.store(store_id)

    program = new_record()
    program.update({
        "store_id": store_id,
        "name": name,
        "priority_rank": priority_rank,
        "funding_ceiling_cents": funding_ceiling_cents,
        "status": status,
    })
    db.programs[program["id"]] = program
    return object_response(serialize.program_out(program), 201)


@bp.get("/mwr-programs/<program_id>")
def read_program(program_id):
    V.authenticate(("MwrBoardOfficer", "SurchargeFundController"))
    program = lookups.program(program_id)
    return object_response(serialize.program_out(program), 200)


# --------------------------------------------------------------------------
# capital projects
# --------------------------------------------------------------------------


@bp.post("/capital-projects")
def create_project():
    V.authenticate(("SurchargeFundController",))
    body = V.raw_body()
    store_id = V.want_string(body, "store_id", required=True)
    title = V.want_string(body, "title", required=True, min_len=1, max_len=160)
    requested_amount_cents = V.want_int(body, "requested_amount_cents", required=True, minimum=1)

    lookups.store(store_id)

    project = new_record()
    project.update({
        "store_id": store_id,
        "title": title,
        "requested_amount_cents": requested_amount_cents,
        "outlay_cents": None,
        "state": "DRAFT",
        "revision_count": 0,
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "closed_by_user_id": None,
    })
    # The tier is selected from the contingency-free request amount.
    project.update(calc.capital_contingency_obligation(requested_amount_cents))
    db.projects[project["id"]] = project
    return object_response(serialize.project_out(project), 201)


@bp.get("/capital-projects")
def list_projects():
    V.authenticate(("SurchargeFundController", "MwrBoardOfficer"))
    limit, offset = V.pagination()
    store_id = V.query_string("store_id")
    state = V.query_enum("state", C.PROJECT_STATES)
    rows = sorted(db.projects.values(), key=lambda p: (p["created_at"], p["_seq"]))
    if store_id is not None:
        rows = [r for r in rows if r["store_id"] == store_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.project_out(r) for r in page], limit, offset, total)


@bp.get("/capital-projects/<project_id>")
def read_project(project_id):
    V.authenticate(("SurchargeFundController", "MwrBoardOfficer"))
    project = lookups.project(project_id)
    return object_response(serialize.project_out(project), 200)


@bp.post("/capital-projects/<project_id>/submit")
def submit_project(project_id):
    caller = V.authenticate(("SurchargeFundController",))
    project = lookups.project(project_id)
    if project["state"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        raise ApiError("ERR_PROJECT_NOT_DRAFT")
    # Only a re-submission tallies against revision_count.
    if project["state"] == "RETURNED_FOR_REVISION":
        project["revision_count"] += 1
    project["state"] = "SUBMITTED"
    project["submitted_by_user_id"] = caller.user_id
    touch(project)
    return object_response(serialize.project_out(project), 200)


@bp.post("/capital-projects/<project_id>/decision")
def decide_project(project_id):
    caller = V.authenticate(("MwrBoardOfficer",))
    project = lookups.project(project_id)
    body = V.raw_body()
    decision = V.want_enum(body, "decision", C.PROJECT_DECISIONS, required=True)
    V.want_string(body, "note", required=False)
    if project["state"] != "SUBMITTED":
        raise ApiError("ERR_PROJECT_NOT_SUBMITTED")

    store = db.stores[project["store_id"]]
    project["decided_by_user_id"] = caller.user_id

    if decision == "APPROVE":
        carries = (
            derive.fund_posture(store["id"]) == "UNRESTRICTED"
            and project["obligation_cents"] <= derive.available_surcharge_cents(store["id"])
        )
        if carries:
            # Booking the obligation is the state move itself: the store's
            # surcharge_obligated_cents sums its APPROVED projects.
            project["state"] = "APPROVED"
            touch(project)
            touch(store)
        else:
            project["state"] = "AWAITING_FUNDS"
            touch(project)
    elif decision == "RETURN":
        project["state"] = "RETURNED_FOR_REVISION"
        project["submitted_by_user_id"] = None
        touch(project)
    else:  # REJECT
        project["state"] = "REJECTED"
        touch(project)

    return object_response(serialize.project_out(project), 200)


@bp.post("/capital-projects/<project_id>/close")
def close_project(project_id):
    caller = V.authenticate(("SurchargeFundController",))
    project = lookups.project(project_id)
    body = V.raw_body()
    outlay_cents = V.want_int(body, "outlay_cents", required=True, minimum=0)

    # Three gates in order: state, fiscal, segregation of duties.
    if project["state"] != "APPROVED":
        raise ApiError("ERR_PROJECT_NOT_APPROVED")
    if outlay_cents > project["obligation_cents"]:
        raise ApiError("ERR_OUTLAY_EXCEEDS_OBLIGATION")
    if caller.user_id == project["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    store = db.stores[project["store_id"]]
    project["state"] = "CLOSED"
    project["outlay_cents"] = outlay_cents
    project["closed_by_user_id"] = caller.user_id
    derive.append_ledger_entry(
        store, "SURCHARGE", "CAPITAL_OUTLAY", -outlay_cents, "CAPITAL_PROJECT", project["id"]
    )
    # Leaving APPROVED releases the WHOLE obligation, contingency included.
    touch(project)
    touch(store)
    return object_response(serialize.project_out(project), 200)
