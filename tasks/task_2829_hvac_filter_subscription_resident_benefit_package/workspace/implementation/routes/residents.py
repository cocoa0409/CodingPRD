"""Resident registration (PRD 3.2)."""
from flask import Blueprint

import envelope
import guards
import validate
import views
from errors import fail
from store import base_record, db

bp = Blueprint("residents", __name__)


@bp.post("/residents")
def create_resident():
    guards.auth(["ProgramOperator", "PropertyManager"])
    body = validate.json_body()
    full_name = validate.req_string(body, "full_name", 1, 120)
    email = validate.req_string(body, "email", 1)
    if "@" not in email:
        fail("ERR_INVALID_REQUEST", "email must contain '@'")
    household_size = validate.req_int(body, "household_size", 1, 12)
    has_pets = validate.req_bool(body, "has_pets")
    smoker = validate.req_bool(body, "smoker")
    allergy = validate.req_bool(body, "allergy_flag")
    for existing in db.residents.values():
        if existing["email"] == email:
            fail("ERR_INVALID_REQUEST", "email must be globally unique")

    rec = base_record()
    rec["full_name"] = full_name
    rec["email"] = email
    rec["household_size"] = household_size
    rec["has_pets"] = has_pets
    rec["smoker"] = smoker
    rec["allergy_flag"] = allergy
    rec["status"] = "PROSPECT"
    db.residents[rec["id"]] = rec
    return envelope.object_response(views.resident_view(rec), 201)


@bp.get("/residents/<resident_id>")
def read_resident(resident_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager", "Resident"])
    rec = guards.get_resident(resident_id)
    guards.own_resident(uid, role, rec)
    return envelope.object_response(views.resident_view(rec))
