"""Child roster (PRD section 3.1)."""
from flask import Blueprint

from db import base_row, clock_date, db
from middleware import endpoint
from response import object_response
from routes.common import matches, paged
from services import derive, rules
from validation import (
    CHILD_STATUS,
    bad,
    body,
    opt_bool,
    opt_date,
    opt_lang,
    present,
    q_bool,
    q_enum,
    q_str,
    req_date,
    req_str,
)

bp = Blueprint("children", __name__)

READ_ROLES = (
    "ChildFindCoordinator",
    "EvaluationChair",
    "Evaluator",
    "PlacementAdministrator",
    "Parent",
    "DistrictAdmin",
)
LIST_ROLES = (
    "ChildFindCoordinator",
    "EvaluationChair",
    "PlacementAdministrator",
    "DistrictAdmin",
)


@bp.post("/children")
@endpoint("ChildFindCoordinator", "DistrictAdmin")
def create_child():
    data = body()
    first_name = req_str(data, "first_name", max_len=80)
    last_name = req_str(data, "last_name", max_len=80)
    date_of_birth = req_date(data, "date_of_birth")
    guardian_full_name = req_str(data, "guardian_full_name")
    district_of_residence = req_str(data, "district_of_residence", max_len=20)
    primary_language_code = opt_lang(data, "primary_language_code", "en")
    part_c_enrolled = opt_bool(data, "part_c_enrolled", False)
    part_c_exit_date = opt_date(data, "part_c_exit_date")

    if date_of_birth >= clock_date():
        bad("Field 'date_of_birth' must be strictly before the current logical clock date")
    if part_c_enrolled and part_c_exit_date is None:
        bad("Field 'part_c_exit_date' is required when part_c_enrolled is true")

    row = base_row()
    row.update(
        {
            "first_name": first_name,
            "last_name": last_name,
            "date_of_birth": date_of_birth,
            "guardian_full_name": guardian_full_name,
            "district_of_residence": district_of_residence,
            "primary_language_code": primary_language_code,
            "part_c_enrolled": part_c_enrolled,
            "part_c_exit_date": part_c_exit_date,
        }
    )
    db.children[row["id"]] = row
    return object_response(derive.child_out(row), 201)


@bp.get("/children/<child_id>")
@endpoint(*READ_ROLES)
def get_child(child_id):
    row = rules.fetch("children", child_id)
    rules.require_guardian(row["id"])
    return object_response(derive.child_out(row))


@bp.get("/children")
@endpoint(*LIST_ROLES)
def list_children():
    district = q_str("district_of_residence")
    language = q_str("primary_language_code")
    part_c = q_bool("part_c_enrolled")
    status = q_enum("status", CHILD_STATUS)
    rows = [
        r
        for r in db.children.values()
        if matches(r, "district_of_residence", district)
        and matches(r, "primary_language_code", language)
        and (part_c is None or r["part_c_enrolled"] == part_c)
        and (status is None or derive.child_status(r["id"]) == status)
    ]
    return paged(rows, derive.child_out)
