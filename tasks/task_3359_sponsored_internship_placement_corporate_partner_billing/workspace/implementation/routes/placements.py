"""Placement matching and placement reads (PRD 3.4)."""

from flask import Blueprint

import db
import middleware
import response
import validators
from errors import (
    ERR_CAPACITY_EXCEEDED,
    ERR_NOT_ELIGIBLE_FOR_MATCH,
    ERR_PARTNER_SUSPENDED,
    ERR_STUDENT_ALREADY_PLACED,
    ApiError,
)
from routes.common import must_get, must_get_body
from services import billing_svc, placement_svc, student_svc

DEFAULT_MAX_INTERVIEW_ROUNDS = 3
DEFAULT_HOURS_PER_WEEK = 20
PLACEMENT_STATES = (
    "MATCHED",
    "INTERVIEW_SCHEDULED",
    "INTERVIEWED",
    "OFFERED",
    "ACCEPTED",
    "ACTIVE",
    "COMPLETED",
    "TERMINATED",
)

bp = Blueprint("placements", __name__)


def _body_fk(data, field, table):
    raw = data.get(field)
    if not isinstance(raw, str) or not raw.strip():
        validators.fail("field '%s' is required" % field)
    return must_get_body(table, raw.strip(), field)


@bp.post("/placements")
def create_placement():
    middleware.require(("ProgramStaff",))
    data = validators.body()

    agreement = _body_fk(data, "agreement_id", "agreements")
    student = _body_fk(data, "student_id", "students")
    max_rounds = validators.as_int(
        data, "max_interview_rounds", required=False, default=DEFAULT_MAX_INTERVIEW_ROUNDS
    )

    if not (
        student["application_state"] == "ENROLLED"
        and student.get("current_phase") in ("INTERNSHIP", "COMPLETED")
    ):
        raise ApiError(
            ERR_NOT_ELIGIBLE_FOR_MATCH,
            "student %s is not eligible for matching" % student["id"],
            409,
        )

    partner = billing_svc.partner_of_agreement(agreement)
    if partner is None or partner["status"] != "ACTIVE":
        raise ApiError(
            ERR_PARTNER_SUSPENDED,
            "the sponsoring partner is not ACTIVE",
            402,
        )

    if placement_svc.slot_count_reached(agreement):
        raise ApiError(
            ERR_CAPACITY_EXCEEDED,
            "agreement %s has no free placement slot" % agreement["id"],
            409,
        )

    if student_svc.has_active_placement(student["id"]):
        raise ApiError(
            ERR_STUDENT_ALREADY_PLACED,
            "student %s already holds a placement at ACCEPTED or ACTIVE" % student["id"],
            409,
        )

    row = db.make_row(
        agreement_id=agreement["id"],
        student_id=student["id"],
        state="MATCHED",
        interview_attempt=0,
        max_interview_rounds=max_rounds,
        start_date=None,
        end_date=None,
        hours_per_week=DEFAULT_HOURS_PER_WEEK,
        placement_fee_cents=None,
        project_scope=agreement["project_scope"],
        supervisor_name=partner["legal_name"] if partner else None,
        outcome=None,
        satisfaction_score=None,
    )
    db.insert("placements", row)
    return response.success(row, status=201)


@bp.get("/placements/<placement_id>")
def read_placement(placement_id):
    middleware.require(("ProgramStaff", "Partner", "Student"))
    placement = must_get("placements", placement_id, "placement")
    return response.success(placement)


@bp.get("/placements")
def list_placements():
    middleware.require(("ProgramStaff", "Partner", "Student"))
    student_id = validators.request_arg("student_id")
    agreement_id = validators.request_arg("agreement_id")
    state = validators.request_arg("state")

    rows = db.all_rows("placements")
    if student_id:
        rows = [p for p in rows if p["student_id"] == student_id]
    if agreement_id:
        rows = [p for p in rows if p["agreement_id"] == agreement_id]
    if state:
        rows = [p for p in rows if p["state"] == state]
    return response.list_response(rows, key=response.by_created_at)


@bp.get("/placements/<placement_id>/interviews")
def list_placement_interviews(placement_id):
    middleware.require(("ProgramStaff", "Partner"))
    must_get("placements", placement_id, "placement")
    rows = placement_svc.rounds_of(placement_id)
    return response.list_response(rows, key=lambda r: (r["round_number"], r["_seq"]))


@bp.get("/placements/<placement_id>/satisfaction-records")
def list_placement_satisfaction(placement_id):
    middleware.require(("ProgramStaff", "Partner"))
    must_get("placements", placement_id, "placement")
    rows = placement_svc.satisfaction_of(placement_id)
    newest_first = sorted(rows, key=lambda s: (s["submitted_at"], s["_seq"]), reverse=True)
    return response.list_response(newest_first)
