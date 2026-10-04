"""Bridge-advance and repair-advance routes (PRD 3.4, 3.8)."""

from flask import Blueprint

from constants import ROLES
from routes import endpoint, json_body, query_params
from services import advances
from services.lookup import get_bridge_advance, get_repair_advance
from store import db

bp = Blueprint("advances", __name__)

COORDINATOR = ROLES[0]
UNDERWRITER = ROLES[1]
HOMEOWNER = ROLES[2]


# --- Bridge advances -------------------------------------------------------

@bp.post("/knock/bridge-advances")
@endpoint([COORDINATOR], status=201)
def request_advance(actor):
    return advances.request_advance(json_body())


@bp.get("/knock/bridge-advances")
@endpoint([COORDINATOR, UNDERWRITER])
def list_advances(actor):
    params = query_params()
    records = db.all("bridge_advances")
    for field in ("bridge_program_id", "interim_loan_id", "status"):
        value = params.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return db.sorted_by_created(records), params


@bp.get("/knock/bridge-advances/<advance_id>")
@endpoint([COORDINATOR, UNDERWRITER, HOMEOWNER])
def read_advance(actor, advance_id):
    return get_bridge_advance(advance_id)


@bp.post("/knock/bridge-advances/<advance_id>/approve")
@endpoint([UNDERWRITER])
def approve_advance(actor, advance_id):
    return advances.approve_advance(advance_id)


@bp.post("/knock/bridge-advances/<advance_id>/reject")
@endpoint([UNDERWRITER])
def reject_advance(actor, advance_id):
    return advances.reject_advance(advance_id)


@bp.post("/knock/bridge-advances/<advance_id>/disburse")
@endpoint([COORDINATOR])
def disburse_advance(actor, advance_id):
    return advances.disburse_advance(advance_id)


# --- Repair advances -------------------------------------------------------

@bp.post("/knock/repair-advances")
@endpoint([COORDINATOR], status=201)
def request_repair(actor):
    return advances.request_repair_advance(json_body())


@bp.get("/knock/repair-advances")
@endpoint([COORDINATOR, UNDERWRITER])
def list_repairs(actor):
    params = query_params()
    records = db.all("repair_advances")
    for field in ("property_id", "bridge_program_id", "status"):
        value = params.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return db.sorted_by_created(records), params


@bp.get("/knock/repair-advances/<repair_id>")
@endpoint([COORDINATOR, UNDERWRITER])
def read_repair(actor, repair_id):
    return get_repair_advance(repair_id)


@bp.post("/knock/repair-advances/<repair_id>/approve")
@endpoint([UNDERWRITER])
def approve_repair(actor, repair_id):
    return advances.approve_repair_advance(repair_id)


@bp.post("/knock/repair-advances/<repair_id>/disburse")
@endpoint([COORDINATOR])
def disburse_repair(actor, repair_id):
    return advances.disburse_repair_advance(repair_id)