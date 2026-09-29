"""Satisfactory-academic-progress checkpoints (PRD 3.8)."""
from flask import Blueprint, request

import db as store
from db import db, new_row, touch
from errors import ApiError
from middleware import (ROLE_FACULTY_MENTOR, ROLE_FINANCIAL_AID_OFFICER,
                        ROLE_PLATFORM_ADMIN, ROLE_REGISTRAR, ROLE_STUDENT,
                        require)
from response import json_body, created_response, object_response, paginated
from services import calc, cascade, lookup, serialize, shape

bp = Blueprint("progress", __name__)

REVIEW_READ_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN,
                     ROLE_FINANCIAL_AID_OFFICER, ROLE_FACULTY_MENTOR,
                     ROLE_STUDENT)
REVIEW_LIST_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN,
                     ROLE_FINANCIAL_AID_OFFICER, ROLE_FACULTY_MENTOR)


def _arg(name):
    raw = request.args.get(name, None)
    if raw is None:
        return None
    text = raw.strip()
    return text if text else None


@bp.route("/sap-reviews", methods=["POST"])
def create_sap_review():
    caller = require(ROLE_REGISTRAR)
    body = json_body()
    student = lookup.student(shape.req_id(body, "student_id"))
    term = lookup.term(shape.req_id(body, "term_id"))
    if student["sap_status"] == "DISMISSED":
        raise ApiError("ERR_SAP_ALREADY_DISMISSED")
    program = lookup.program_of_student(student)
    figures = calc.sap_review_figures(student, term, program)
    row = new_row(with_common=False)
    row.update({
        "student_id": student["id"],
        "term_id": term["id"],
        "evaluated_at_utc": db.now(),
        "reviewed_by_user_id": caller.user_id,
    })
    row.update(figures)
    db.sap_reviews[row["id"]] = row
    new_status = figures["new_sap_status"]
    if new_status != student["sap_status"]:
        student["sap_status"] = new_status
        touch(student)
    if new_status == "DISMISSED":
        for award in lookup.disbursements_of_student(student["id"]):
            if award["status"] in ("SCHEDULED", "HELD"):
                cascade.cancel_award(award)
    return created_response(serialize.sap_review(row))


@bp.route("/sap-reviews/<rid>", methods=["GET"])
def read_sap_review(rid):
    require(*REVIEW_READ_ROLES)
    return object_response(serialize.sap_review(lookup.sap_review(rid)))


@bp.route("/sap-reviews", methods=["GET"])
def list_sap_reviews():
    require(*REVIEW_LIST_ROLES)
    student_id = _arg("student_id")
    term_id = _arg("term_id")
    pace_band = _arg("pace_band")
    rows = []
    for row in db.sap_reviews.values():
        if student_id is not None and row["student_id"] != student_id:
            continue
        if term_id is not None and row["term_id"] != term_id:
            continue
        if pace_band is not None and row["pace_band"] != pace_band:
            continue
        rows.append(row)
    return paginated(store.by_created(rows), serialize.sap_review)
