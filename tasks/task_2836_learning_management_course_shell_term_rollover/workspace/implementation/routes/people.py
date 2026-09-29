"""People -- PRD 3.3 (the SIS person feed and its two compliance switches)."""

from decimal import Decimal

from flask import Blueprint

import lookup
from db import db, mark, new_record, set_field
from middleware import (INSTRUCTOR, LMS_ADMIN, REGISTRAR, as_bool, as_dt,
                        as_enum, as_str, body)
from routes.common import (apply_filters, bool_arg, created, guard, listing, ok)
from util import q2

bp = Blueprint("people", __name__)

AFFILIATIONS = ("STUDENT", "FACULTY", "STAFF")


@bp.post("/people")
def create_person():
    guard(REGISTRAR)
    payload = body()
    sis_person_id = as_str(payload, "sis_person_id", required=True)
    full_name = as_str(payload, "full_name", required=True)
    affiliation = as_enum(payload, "primary_affiliation", AFFILIATIONS, required=True)
    ferpa_block = as_bool(payload, "ferpa_block", default=False)
    access_revoked_at = as_dt(payload, "access_revoked_at")

    person = new_record(
        _kind="person",
        sis_person_id=sis_person_id,
        full_name=full_name,
        primary_affiliation=affiliation,
        ferpa_block=ferpa_block,
        access_revoked_at=access_revoked_at,
        sandbox_storage_charge_usd=q2(Decimal(0)),
    )
    db.people[person["id"]] = person
    return created(person)


@bp.get("/people")
def list_people():
    guard(REGISTRAR, LMS_ADMIN)
    records = apply_filters(db.people.values(), {
        "sis_person_id": "sis_person_id",
        "primary_affiliation": "primary_affiliation",
    })
    ferpa = bool_arg("ferpa_block")
    if ferpa is not None:
        records = [r for r in records if r["ferpa_block"] == ferpa]
    return listing(records)


@bp.get("/people/<person_id>")
def read_person(person_id):
    guard(REGISTRAR, LMS_ADMIN, INSTRUCTOR)
    return ok(lookup.person(person_id))


@bp.patch("/people/<person_id>")
def update_person(person_id):
    guard(REGISTRAR)
    person = lookup.person(person_id)
    payload = body()
    full_name = as_str(payload, "full_name")
    ferpa_block = as_bool(payload, "ferpa_block")
    access_revoked_at = as_dt(payload, "access_revoked_at")
    if full_name is not None:
        set_field(person, "full_name", full_name)
    if ferpa_block is not None:
        set_field(person, "ferpa_block", ferpa_block)
    if "access_revoked_at" in payload and payload["access_revoked_at"] is None:
        set_field(person, "access_revoked_at", None)
    elif access_revoked_at is not None:
        set_field(person, "access_revoked_at", access_revoked_at)
    mark(person)
    return ok(person)
