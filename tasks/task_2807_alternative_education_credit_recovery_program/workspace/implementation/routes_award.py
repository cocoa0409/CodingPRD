"""Posted transcript rows and the void that reverses them (PRD 3.8)."""
from flask import Blueprint

import derive
import validate as v
from auth import endpoint, scope_school
from envelope import ok, ok_list
from errors import ApiError
from helpers import eq, get_award, q
from services import void_award
from store import ordered, store

bp = Blueprint("awards", __name__)


def _school_scope(ctx, award):
    student = store.students.get(award["student_id"])
    if student is not None:
        scope_school(ctx, student["home_school_id"])


@bp.get("/credit-awards/<credit_award_id>")
@endpoint("Registrar", "DistrictAdmin", "HomeSchoolCounselor")
def read_award(ctx, credit_award_id):
    row = get_award(credit_award_id)
    _school_scope(ctx, row)
    return ok(derive.ser_award(row))


@bp.get("/credit-awards")
@endpoint("Registrar", "DistrictAdmin", "HomeSchoolCounselor")
def list_awards(ctx):
    rows = ordered(store.awards.values())
    if ctx.role == "HomeSchoolCounselor":
        rows = [r for r in rows
                if store.students[r["student_id"]]["home_school_id"] == ctx.uid]
    rows = eq(rows, "student_id", q("student_id"))
    rows = eq(rows, "course_enrollment_id", q("course_enrollment_id"))
    rows = eq(rows, "prior_course_record_id", q("prior_course_record_id"))
    rows = eq(rows, "status", q("status"))
    return ok_list(rows, derive.ser_award)


@bp.post("/credit-awards/<credit_award_id>/void")
@endpoint("Registrar")
def void_credit_award(ctx, credit_award_id):
    award = get_award(credit_award_id)
    b = v.body()
    reason = v.req_str(b, "void_reason", 1, None)
    if award["status"] != "POSTED":
        raise ApiError("ERR_AWARD_STATE_INVALID", "only a POSTED award may be voided")
    void_award(award, reason)
    return ok(derive.ser_award(award))
