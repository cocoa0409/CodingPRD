"""Entry endpoints: creation (entry-requirement validation), reads, scoring."""

from flask import Blueprint, g, request

import constants as C
from errors import err
from helpers import (
    apply_filters,
    bad,
    body,
    check_enum_field,
    check_int_field,
    created_key,
    is_int,
    paginate,
    require_present,
    require_roles,
    resp_object,
)
from serializers import ser_entry
from store import base_record, clock_now, db, iso_z, touch

bp = Blueprint("entries", __name__)


@bp.route("/api/entries", methods=["POST"])
@require_roles(C.ROLE_STUDENT)
def create_entry():
    b = body()
    # Priority 3, ownership: the acting student's X-User-ID must equal the
    # payload's student_id.
    if b.get("student_id") is not None and g.user_id != b["student_id"]:
        err("ERR_FORBIDDEN_OWNERSHIP", "students may only create their own entries")
    # Priority 4, body-referenced ids must exist.
    if b.get("student_id") is not None and b["student_id"] not in db["students"]:
        bad("referenced student_id does not exist")
    if b.get("cycle_id") is not None and b["cycle_id"] not in db["cycles"]:
        bad("referenced cycle_id does not exist")
    require_present(b, "student_id", "cycle_id")
    student = db["students"][b["student_id"]]
    cycle = db["cycles"][b["cycle_id"]]
    # Priority 6, posture gate.
    if cycle["status"] != "ENTRY_OPEN":
        err("ERR_CYCLE_NOT_ACCEPTING_ENTRIES", "cycle is not accepting entries")
    # Priority 7, one entry per (student_id, cycle_id).
    for e in db["entries"].values():
        if e["student_id"] == b["student_id"] and e["cycle_id"] == b["cycle_id"]:
            err("ERR_DUPLICATE_ENTRY", "an entry already exists for this student and cycle")
    # Priority 7, entry requirements. An exam_year_of_hs that is not a valid
    # enum member is a priority-10 field-shape error, not an eligibility one,
    # so only well-formed values participate here.
    if (
        student["citizenship_status"] == "OTHER"
        or student["enrollment_status"] == "NOT_ENROLLED"
        or student["graduation_year"] != cycle["target_graduation_year"]
        or (b.get("exam_year_of_hs") in C.EXAM_YEARS and b["exam_year_of_hs"] != "THIRD_YEAR")
    ):
        err("ERR_ENTRY_INELIGIBLE", "entry requirements not met")
    # Priority 10, field shape.
    require_present(b, "exam_year_of_hs")
    check_enum_field(b, "exam_year_of_hs", C.EXAM_YEARS)
    rec = base_record()
    rec.update(
        {
            "student_id": b["student_id"],
            "cycle_id": b["cycle_id"],
            "exam_year_of_hs": b["exam_year_of_hs"],
            "reading_score": None,
            "writing_score": None,
            "math_score": None,
            "selection_index": None,
            "status": "SUBMITTED",
            "scored_at": None,
        }
    )
    db["entries"][rec["id"]] = rec
    return resp_object(ser_entry(rec), code=201)


@bp.route("/api/entries/<entry_id>", methods=["GET"])
@require_roles(C.ROLE_PROGRAM_ADMIN, C.ROLE_STUDENT, C.ROLE_SCHOOL_OFFICIAL)
def get_entry(entry_id):
    rec = db["entries"].get(entry_id)
    if rec is None:
        err("ERR_NOT_FOUND", "entry not found")
    if g.user_role == C.ROLE_STUDENT and g.user_id != rec["student_id"]:
        err("ERR_FORBIDDEN_OWNERSHIP", "students may only read their own entries")
    return resp_object(ser_entry(rec))


@bp.route("/api/entries", methods=["GET"])
@require_roles(C.ROLE_PROGRAM_ADMIN, C.ROLE_SCHOOL_OFFICIAL)
def list_entries():
    records = sorted(db["entries"].values(), key=created_key)
    records = apply_filters(
        records,
        [
            ("cycle_id", request.args.get("cycle_id")),
            ("student_id", request.args.get("student_id")),
            ("status", request.args.get("status")),
        ],
    )
    return paginate(records, ser_entry)


@bp.route("/api/entries/<entry_id>/score", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def score_entry(entry_id):
    rec = db["entries"].get(entry_id)
    if rec is None:
        err("ERR_NOT_FOUND", "entry not found")
    # Priority 6, posture gate: scoring only in ENTRY_CLOSED.
    cycle = db["cycles"][rec["cycle_id"]]
    if cycle["status"] != "ENTRY_CLOSED":
        err("ERR_CYCLE_NOT_CLOSED_FOR_SCORING", "cycle is not closed for scoring")
    # Priority 6, entity state: only SUBMITTED entries may be scored.
    if rec["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "entry is not SUBMITTED")
    # Priority 10, field shape: integer section scores 8..38.
    b = body()
    require_present(b, "reading_score", "writing_score", "math_score")
    for f in ("reading_score", "writing_score", "math_score"):
        check_int_field(b, f, minimum=C.SECTION_MIN, maximum=C.SECTION_MAX)
    rec["reading_score"] = b["reading_score"]
    rec["writing_score"] = b["writing_score"]
    rec["math_score"] = b["math_score"]
    # The server always recomputes; client-supplied selection_index is ignored.
    rec["selection_index"] = (
        b["reading_score"] + b["writing_score"] + b["math_score"]
    ) * C.SECTION_WEIGHT
    rec["scored_at"] = iso_z(clock_now())
    rec["status"] = "SCORED"
    touch(rec)
    return resp_object(ser_entry(rec))
