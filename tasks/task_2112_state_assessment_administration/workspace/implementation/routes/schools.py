"""Schools (PRD 3.1)."""

from flask import Blueprint, request

import serialize
from db import create, db, ordered
from errors import api_error
from middleware import ALL_ROLES, STATE_OFFICER, endpoint, json_body, resolve
from response import object_response, paginate
from validators import identifier_field, integer_field, string_field

bp = Blueprint("schools", __name__)

SCHOOL_CODE_PATTERN = r"[A-Z]{2}-[0-9]{2}"


@bp.post("/schools")
@endpoint(STATE_OFFICER)
def create_school(actor):
    body = json_body()
    district_id = identifier_field(body, "district_id")
    name = string_field(body, "name", min_length=1, max_length=120)
    school_code = string_field(body, "school_code", pattern=SCHOOL_CODE_PATTERN)
    max_concurrent_seats = integer_field(body, "max_concurrent_seats", minimum=1, maximum=500)

    # Check 6 — body reference resolution.
    resolve(db.districts, district_id, "ERR_DISTRICT_NOT_FOUND")

    # Check 21 — school codes are unique inside their own district.
    for existing in db.schools.values():
        if existing["district_id"] == district_id and existing["school_code"] == school_code:
            raise api_error("ERR_DUPLICATE_CODE", "school_code already exists in this district.")

    school = create(
        db.schools,
        {
            "district_id": district_id,
            "name": name,
            "school_code": school_code,
            "max_concurrent_seats": max_concurrent_seats,
        },
    )
    return object_response(serialize.school(school), 201)


@bp.get("/schools/<school_id>")
@endpoint(*ALL_ROLES)
def read_school(actor, school_id):
    school = resolve(db.schools, school_id, "ERR_SCHOOL_NOT_FOUND")
    return object_response(serialize.school(school))


@bp.get("/schools")
@endpoint(*ALL_ROLES)
def list_schools(actor):
    district_id = request.args.get("district_id")
    items = [
        school
        for school in db.schools.values()
        if district_id is None or school["district_id"] == district_id
    ]
    return paginate(ordered(items), serialize.school)
