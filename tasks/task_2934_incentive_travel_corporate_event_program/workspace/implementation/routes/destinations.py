"""Destination sourcing, site inspection and shortlisting (PRD 3.3)."""

from flask import Blueprint

import serialize
from auth import authorize
from calc import MAX_DESTINATION_RISK, MIN_INSPECTION_SCORE
from envelope import created, ok, paginate
from errors import fail
from gates import filtered, lookup, program_gate
from schema import body, f_id, f_int, f_str, raw_fk, validate
from store import db

bp = Blueprint("destinations", __name__)

READ_ROLES = ("ProgramDirector", "SourcingManager", "ContractApprover",
              "SalesOpsAnalyst", "TravelDesk")
SOURCING_STATUSES = ("DESIGN", "SOURCING")


@bp.post("/destinations")
def create_destination():
    authorize("SourcingManager")
    payload = body()

    program_id = raw_fk(payload, "program_id")
    if program_id is not None:
        lookup("program", program_id)

    data = validate(payload, [
        f_id("program_id"),
        f_str("city", max_len=120),
        f_str("country_code", min_len=2, max_len=2, exact_len=2, upper=True),
        f_int("per_person_cost_cents", minimum=0),
        f_int("risk_score", minimum=0, maximum=100),
        f_str("air_gateway_code", min_len=3, max_len=3, exact_len=3, upper=True),
    ])
    lookup("program", data["program_id"])

    row = {
        "program_id": data["program_id"],
        "city": data["city"],
        "country_code": data["country_code"],
        "per_person_cost_cents": data["per_person_cost_cents"],
        "risk_score": data["risk_score"],
        "air_gateway_code": data["air_gateway_code"],
        "status": "CANDIDATE",
        "inspection_status": "NOT_INSPECTED",
        "inspection_score": None,
        "inspected_by_user_id": None,
        "inspected_at": None,
    }
    db.stamp_new(row)
    db.destinations[row["id"]] = row
    return created(serialize.destination(row))


@bp.get("/destinations/<destination_id>")
def read_destination(destination_id):
    authorize(*READ_ROLES)
    return ok(serialize.destination(lookup("destination", destination_id)))


@bp.get("/destinations")
def list_destinations():
    authorize(*READ_ROLES)
    rows = filtered(db.ordered(db.destinations), [
        ("program_id", "program_id"),
        ("status", "status"),
        ("inspection_status", "inspection_status"),
    ])
    return paginate(rows, serialize.destination)


@bp.post("/destinations/<destination_id>/site-inspection")
def site_inspection(destination_id):
    actor = authorize("SourcingManager")
    destination = lookup("destination", destination_id)
    data = validate(body(), [f_int("inspection_score", minimum=0, maximum=100)])
    program_gate(db.programs.get(destination["program_id"]), SOURCING_STATUSES)

    if destination["status"] != "CANDIDATE" or destination["inspection_status"] != "NOT_INSPECTED":
        fail("ERR_DESTINATION_STATE_INVALID")

    destination["inspection_status"] = "INSPECTED"
    destination["inspection_score"] = data["inspection_score"]
    destination["inspected_by_user_id"] = actor.user_id
    destination["inspected_at"] = db.logical_now()
    db.touch(destination)
    return ok(serialize.destination(destination))


@bp.post("/destinations/<destination_id>/shortlist")
def shortlist(destination_id):
    authorize("SourcingManager")
    destination = lookup("destination", destination_id)
    body()
    program_gate(db.programs.get(destination["program_id"]), SOURCING_STATUSES)

    if destination["status"] != "CANDIDATE" or destination["inspection_status"] != "INSPECTED":
        fail("ERR_DESTINATION_STATE_INVALID")
    if destination["risk_score"] > MAX_DESTINATION_RISK:
        fail("ERR_DESTINATION_RISK_TOO_HIGH")
    if destination["inspection_score"] is None or destination["inspection_score"] < MIN_INSPECTION_SCORE:
        fail("ERR_INSPECTION_SCORE_BELOW_MINIMUM")

    destination["status"] = "SHORTLISTED"
    db.touch(destination)
    return ok(serialize.destination(destination))
