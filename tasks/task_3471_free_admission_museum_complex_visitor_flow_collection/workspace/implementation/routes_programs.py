"""Docents and weekly education programs (PRD 3.3), including the gallery
setup-buffer schedule conflict and the program-cancel cascade."""

from flask import Blueprint

import calc
import constants
import db
import serializers
import util
from envelope import listing, success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("programs", __name__)

DOCENT_READ_ROLES = ["PlatformAdmin", "ProgramCoordinator", "Docent"]
PROGRAM_READ_ROLES = ["PlatformAdmin", "ProgramCoordinator", "Docent", "Public"]


# --- Docents ---
@bp.post("/campus/docents")
def create_docent():
    _uid, role = auth()
    require_role(role, ["ProgramCoordinator"])
    b = util.body()
    full_name = util.req_str(b, "full_name")
    certification = util.req_enum(b, "certification_level", constants.CERTIFICATION_RANK.keys())
    active = util.opt_bool(b, "active", True)
    d = db.new_entity(
        {"full_name": full_name, "certification_level": certification, "active": active}
    )
    db.STORE["docents"][d["id"]] = d
    return success(serializers.docent(d), 201)


@bp.get("/campus/docents/<did>")
def get_docent(did):
    _uid, role = auth()
    require_role(role, DOCENT_READ_ROLES)
    d = get_or_404("docents", did, "Docent")
    return success(serializers.docent(d))


# --- Education programs ---
@bp.post("/campus/museums/<mid>/education-programs")
def create_program(mid):
    _uid, role = auth()
    require_role(role, ["ProgramCoordinator"])
    museum = get_or_404("museums", mid, "Museum")  # (3) path existence
    b = util.body()
    # (9) request shape
    title = util.req_str(b, "title")
    gallery_code = util.req_str(b, "gallery_code")
    day_of_week = util.req_enum(b, "day_of_week", constants.DAY_CODES)
    start_minute = util.req_int(b, "start_minute", minimum=0, maximum=1439)
    end_minute = util.req_int(b, "end_minute", minimum=0, maximum=1439)
    if end_minute <= start_minute:
        fail("ERR_INVALID_REQUEST", "end_minute must be strictly greater than start_minute")
    student_capacity = util.req_int(b, "student_capacity", minimum=1)
    docent_ratio = util.req_int(b, "docent_ratio", minimum=1)
    max_group_size = util.req_int(b, "max_group_size", minimum=1)
    required_cert = util.req_enum(
        b, "required_docent_certification", constants.CERTIFICATION_RANK.keys()
    )
    # (11) gallery buffer-expanded schedule overlap
    if calc.gallery_conflict(
        museum["id"], gallery_code, day_of_week, start_minute, end_minute
    ):
        fail(
            "ERR_GALLERY_SCHEDULE_CONFLICT",
            "The gallery is occupied by another scheduled program in the setup-buffer window",
        )
    p = db.new_entity(
        {
            "museum_id": museum["id"],
            "title": title,
            "gallery_code": gallery_code,
            "day_of_week": day_of_week,
            "start_minute": start_minute,
            "end_minute": end_minute,
            "student_capacity": student_capacity,
            "docent_ratio": docent_ratio,
            "max_group_size": max_group_size,
            "required_docent_certification": required_cert,
            "status": "SCHEDULED",
        }
    )
    db.STORE["education_programs"][p["id"]] = p
    return success(serializers.education_program(p), 201)


@bp.get("/campus/education-programs")
def list_programs():
    _uid, role = auth()
    require_role(role, PROGRAM_READ_ROLES)
    limit, offset = util.pagination()
    f_museum = util.request.args.get("museum_id")
    rows = []
    for p in db.all_sorted("education_programs"):
        if f_museum is not None and p["museum_id"] != f_museum:
            continue
        rows.append(p)
    page = rows[offset : offset + limit]
    return listing([serializers.education_program(p) for p in page], limit, offset, len(rows))


@bp.get("/campus/education-programs/<pid>")
def get_program(pid):
    _uid, role = auth()
    require_role(role, PROGRAM_READ_ROLES)
    p = get_or_404("education_programs", pid, "EducationProgram")
    return success(serializers.education_program(p))


@bp.post("/campus/education-programs/<pid>/cancel")
def cancel_program(pid):
    _uid, role = auth()
    require_role(role, ["ProgramCoordinator"])
    p = get_or_404("education_programs", pid, "EducationProgram")
    if p["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "Only a SCHEDULED program can be cancelled")
    p["status"] = "CANCELLED"
    # Cascade link 1: CONFIRMED and WAITLISTED reservations -> CANCELLED.
    for r in db.STORE["school_reservations"].values():
        if r["program_id"] == p["id"] and r["status"] in ("CONFIRMED", "WAITLISTED"):
            r["status"] = "CANCELLED"
            db.touch(r)
    # Conditional cascade: ASSIGNED assignments -> RELEASED; CONFIRMED
    # assignments are deliberately left untouched as a matter of record.
    for a in db.STORE["docent_assignments"].values():
        if a["program_id"] == p["id"] and a["status"] == "ASSIGNED":
            a["status"] = "RELEASED"
            db.touch(a)
    db.touch(p)
    return success(serializers.education_program(p))
