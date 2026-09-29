"""Transcript translation: units to credit hours (PRD 3.9)."""
from flask import Blueprint, request

import db as store
from db import db, new_row, touch
from errors import ApiError
from middleware import (ROLE_PLATFORM_ADMIN, ROLE_REGISTRAR, ROLE_STUDENT,
                        check_student_ownership, require)
from response import json_body, created_response, object_response, paginated
from services import calc, derive, lookup, serialize, shape

bp = Blueprint("transcripts", __name__)

PURPOSES = ("TRANSFER", "INTERNAL", "STUDENT_COPY")
READ_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN, ROLE_STUDENT)
LIST_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN)


def _arg(name):
    raw = request.args.get(name, None)
    if raw is None:
        return None
    text = raw.strip()
    return text if text else None


@bp.route("/transcript-records", methods=["POST"])
def create_transcript():
    caller = require(ROLE_REGISTRAR, ROLE_STUDENT)
    body = json_body()
    claimed = shape.raw_id(body, "student_id")
    if claimed is not None:
        check_student_ownership(caller, claimed)
    student = lookup.student(shape.req_id(body, "student_id"))
    purpose = shape.req_enum(body, "purpose", PURPOSES)
    for prior in lookup.transcripts_of(student["id"]):
        if prior["status"] == "DRAFT":
            prior["status"] = "VOIDED"
            prior["voided_reason"] = "SUPERSEDED"
            touch(prior)
    program = lookup.program_of_student(student)
    row = new_row()
    row.update({
        "student_id": student["id"],
        "purpose": purpose,
        "status": "DRAFT",
        "issued_at_utc": None,
        "voided_reason": None,
    })
    row.update(calc.transcript_figures(student, program))
    db.transcripts[row["id"]] = row
    return created_response(serialize.transcript(row))


@bp.route("/transcript-records/<tid>", methods=["GET"])
def read_transcript(tid):
    caller = require(*READ_ROLES)
    row = lookup.transcript(tid)
    check_student_ownership(caller, row["student_id"])
    return object_response(serialize.transcript(row))


@bp.route("/transcript-records", methods=["GET"])
def list_transcripts():
    require(*LIST_ROLES)
    student_id = _arg("student_id")
    status = _arg("status")
    purpose = _arg("purpose")
    rows = []
    for row in db.transcripts.values():
        if student_id is not None and row["student_id"] != student_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if purpose is not None and row["purpose"] != purpose:
            continue
        rows.append(row)
    return paginated(store.by_created(rows, descending=True),
                     serialize.transcript)


@bp.route("/transcript-records/<tid>/issue", methods=["POST"])
def issue_transcript(tid):
    require(ROLE_REGISTRAR)
    row = lookup.transcript(tid)
    if row["status"] == "VOIDED":
        raise ApiError("ERR_TRANSCRIPT_VOIDED")
    if row["status"] != "DRAFT":
        raise ApiError("ERR_TRANSCRIPT_ALREADY_ISSUED")
    if derive.student_has_live_case(row["student_id"]):
        raise ApiError("ERR_TRANSCRIPT_INTEGRITY_PENDING")
    row["status"] = "ISSUED"
    row["issued_at_utc"] = db.now()
    touch(row)
    return object_response(serialize.transcript(row))
