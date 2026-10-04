"""Qualification routes (PRD 3.2)."""

from flask import Blueprint

from constants import ROLES
from routes import endpoint, json_body, query_params
from services import qualification
from services.lookup import get_qualification
from store import db

bp = Blueprint("qualifications", __name__)

COORDINATOR = ROLES[0]
HOMEOWNER = ROLES[2]
PROGRAM_ADMIN = ROLES[4]


@bp.post("/knock/qualifications")
@endpoint([COORDINATOR], status=201)
def create(actor):
    return qualification.create_qualification(json_body())


@bp.get("/knock/qualifications")
@endpoint([COORDINATOR, PROGRAM_ADMIN])
def list_qualifications(actor):
    params = query_params()
    records = db.all("qualifications")
    for field in ("homeowner_id", "departing_property_id", "new_property_id"):
        value = params.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return db.sorted_by_created(records), params


@bp.get("/knock/qualifications/<qualification_id>")
@endpoint([COORDINATOR, HOMEOWNER])
def read(actor, qualification_id):
    return get_qualification(qualification_id)


@bp.patch("/knock/qualifications/<qualification_id>")
@endpoint([COORDINATOR])
def revise(actor, qualification_id):
    return qualification.revise_qualification(qualification_id, json_body())


@bp.post("/knock/qualifications/<qualification_id>/approve")
@endpoint([COORDINATOR])
def approve(actor, qualification_id):
    return qualification.approve_qualification(qualification_id)


@bp.post("/knock/qualifications/<qualification_id>/deny")
@endpoint([COORDINATOR])
def deny(actor, qualification_id):
    return qualification.deny_qualification(qualification_id, json_body())