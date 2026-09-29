"""Instructors: registration, certification and revocation (cascade C)."""
from flask import Blueprint, g

import ops
import serial
from core import base_row, fail, now, store, touch
from routes.common import (
    created,
    listing,
    ok,
    path_row,
    require_roles,
    unique_or_conflict,
)
from validate import body, code_list, query_bool, query_enum, req_bool, req_instant, req_str

bp = Blueprint("instructors", __name__)

CERT_STATUSES = ("UNCERTIFIED", "CERTIFIED", "EXPIRED", "REVOKED")
READ_ONE_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian",
                  "AcademyInstructor", "FieldTrainingOfficer")
LIST_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian")


@bp.post("/instructors")
def create_instructor():
    require_roles("AcademyDirector")
    payload = body()
    badge_number = req_str(payload, "badge_number", min_len=1, max_len=16)
    full_name = req_str(payload, "full_name", min_len=1, max_len=120)

    unique_or_conflict("instructors", "badge_number", badge_number)

    row = base_row()
    row.update({
        "badge_number": badge_number,
        "full_name": full_name,
        "certification_status": "UNCERTIFIED",
        "certification_expires_at": None,
        "authorized_topic_codes": [],
        "fto_certified": False,
        "revocation_reason": None,
    })
    store.instructors[row["id"]] = row
    return created(serial.instructor_json(row))


@bp.get("/instructors/<instructor_id>")
def read_instructor(instructor_id):
    require_roles(*READ_ONE_ROLES)
    row = path_row("instructors", instructor_id)
    return ok(serial.instructor_json(row))


@bp.get("/instructors")
def list_instructors():
    require_roles(*LIST_ROLES)
    certification_status = query_enum("certification_status", CERT_STATUSES)
    fto_certified = query_bool("fto_certified")

    def predicate(row):
        if certification_status is not None and row["certification_status"] != certification_status:
            return False
        if fto_certified is not None and row["fto_certified"] != fto_certified:
            return False
        return True

    return listing("instructors", serial.instructor_json, predicate)


@bp.post("/instructors/<instructor_id>/certify")
def certify_instructor(instructor_id):
    require_roles("AcademyDirector")
    row = path_row("instructors", instructor_id)
    payload = body()
    expires_at = req_instant(payload, "certification_expires_at")
    topics = code_list(payload, "authorized_topic_codes")
    fto_certified = req_bool(payload, "fto_certified")

    if row["certification_status"] not in ("UNCERTIFIED", "EXPIRED"):
        fail("ERR_INVALID_STATE",
             "certification is not granted from %s" % row["certification_status"])
    if expires_at <= now():
        fail("ERR_INSTRUCTOR_CERT_EXPIRED",
             "certification_expires_at must be strictly after the current clock")

    row["certification_status"] = "CERTIFIED"
    row["certification_expires_at"] = expires_at
    row["authorized_topic_codes"] = topics
    row["fto_certified"] = fto_certified
    touch(row)
    return ok(serial.instructor_json(row))


@bp.post("/instructors/<instructor_id>/revoke-certification")
def revoke_certification(instructor_id):
    require_roles("AcademyDirector")
    row = path_row("instructors", instructor_id)
    payload = body()
    reason = req_str(payload, "reason", min_len=1, max_len=2000)

    if row["certification_status"] not in ("CERTIFIED", "EXPIRED"):
        fail("ERR_INVALID_STATE",
             "revocation is not declared from %s" % row["certification_status"])

    ops.cascade_c(row, reason)
    return ok(serial.instructor_json(row))
