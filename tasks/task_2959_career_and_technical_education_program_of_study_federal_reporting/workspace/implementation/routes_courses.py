"""Sequence-course and credential routes (PRD sec 3.1)."""
from flask import Blueprint

import calc
import resolve
import serialize
import services
import shape
from auth import endpoint
from envelope import created, listing, ok, page
from errors import ApiError
from store import (COURSE_STATUSES, CREDENTIAL_TIERS, ROLES, SEGMENTS, db, dec,
                   stamp_new, touch)

bp = Blueprint("courses", __name__)
DIRECTOR = ("CteDirector",)


def _check_prerequisite(course, prerequisite_id):
    """Priority 20 integrity, then priority 21 acyclicity."""
    if prerequisite_id is not None:
        parent = db.courses.get(prerequisite_id)
        if (parent is None
                or parent["pos_id"] != course["pos_id"]
                or parent["id"] == course["id"]
                or (course["segment"] == "SECONDARY"
                    and parent["segment"] == "POSTSECONDARY")
                or int(parent["position"]) >= int(course["position"])):
            raise ApiError("ERR_PREREQUISITE_INVALID",
                           "The named prerequisite course does not satisfy the "
                           "prerequisite integrity rules.")
    seen = {course["id"]}
    current_id = prerequisite_id
    while current_id is not None:
        if current_id in seen:
            raise ApiError("ERR_PREREQUISITE_CYCLE",
                           "The prerequisite chain revisits a course already on "
                           "the walk.")
        seen.add(current_id)
        parent = db.courses.get(current_id)
        if parent is None:
            return
        current_id = parent.get("prerequisite_course_id")


# ------------------------------------------------------------------ reads
@bp.get("/cte/sequence-courses/<course_id>")
@endpoint(ROLES)
def get_course(course_id):
    return ok(serialize.course(resolve.course(course_id)))


@bp.get("/cte/sequence-courses/<course_id>/dependents")
@endpoint(ROLES)
def list_dependents(course_id):
    limit, offset = shape.pagination()
    segment = shape.filter_enum("segment", SEGMENTS)
    status = shape.filter_enum("status", COURSE_STATUSES)
    resolve.course(course_id)
    rows = [c for c in db.courses.values()
            if c.get("prerequisite_course_id") == course_id]
    if segment is not None:
        rows = [r for r in rows if r["segment"] == segment]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["_seq"])
    window, total = page(rows, limit, offset)
    return listing([serialize.course(r) for r in window], limit, offset, total)


@bp.get("/cte/credentials/<credential_id>")
@endpoint(ROLES)
def get_credential(credential_id):
    return ok(serialize.credential(resolve.credential(credential_id)))


# ------------------------------------------------------------------ writes
@bp.post("/cte/programs-of-study/<pos_id>/sequence-courses")
@endpoint(DIRECTOR)
def create_course(pos_id):
    data = shape.body()
    code = shape.req_string(data, "code", min_len=1, max_len=24)
    title = shape.req_string(data, "title")
    segment = shape.req_enum(data, "segment", SEGMENTS)
    position = shape.req_int(data, "position", minimum=1, maximum=8)
    credit_hours = shape.req_num(data, "credit_hours", exclusive_min=0, places=2)
    articulated = shape.opt_num(data, "articulated_credit_hours", minimum=0,
                                places=2, default=dec("0.00"))
    if articulated > credit_hours:
        shape.bad("Field 'articulated_credit_hours' may not exceed 'credit_hours'.")
    articulation_verified = shape.opt_bool(data, "articulation_verified",
                                           default=False)
    status = shape.opt_enum(data, "status", COURSE_STATUSES, default="DRAFT")
    prerequisite_id = shape.opt_string(data, "prerequisite_course_id")

    program = resolve.program(pos_id)
    if prerequisite_id is not None:
        resolve.course(prerequisite_id)
    services.refresh_clna(program)

    course = {
        "id": None,
        "pos_id": pos_id,
        "code": code,
        "title": title,
        "segment": segment,
        "position": position,
        "credit_hours": credit_hours,
        "articulated_credit_hours": articulated,
        "articulation_verified": articulation_verified,
        "prerequisite_course_id": prerequisite_id,
        "status": status,
    }
    _check_prerequisite(course, prerequisite_id)
    for existing in db.courses.values():
        if existing["pos_id"] == pos_id and existing["code"] == code:
            raise ApiError("ERR_COURSE_CODE_DUPLICATE",
                           "Course code '%s' already exists on this program." % code)
    stamp_new(course)
    db.courses[course["id"]] = course
    calc.refresh_subtotals(program)
    touch(program)
    return created(serialize.course(course))


@bp.patch("/cte/sequence-courses/<course_id>")
@endpoint(DIRECTOR)
def revise_course(course_id):
    data = shape.body()
    status = shape.opt_enum(data, "status", COURSE_STATUSES)
    credit_hours = shape.opt_num(data, "credit_hours", exclusive_min=0, places=2)
    articulated = shape.opt_num(data, "articulated_credit_hours", minimum=0, places=2)
    articulation_verified = shape.opt_bool(data, "articulation_verified")
    position = shape.opt_int(data, "position", minimum=1, maximum=8)
    if (credit_hours is not None and articulated is not None
            and articulated > credit_hours):
        shape.bad("Field 'articulated_credit_hours' may not exceed 'credit_hours'.")

    course = resolve.course(course_id)
    prerequisite_given = "prerequisite_course_id" in data
    prerequisite_id = data.get("prerequisite_course_id") if prerequisite_given \
        else course.get("prerequisite_course_id")
    if prerequisite_given and prerequisite_id is not None:
        if not isinstance(prerequisite_id, str):
            shape.bad("Field 'prerequisite_course_id' must be a string.")

    effective_credit = credit_hours if credit_hours is not None \
        else dec(course["credit_hours"])
    effective_articulated = articulated if articulated is not None \
        else dec(course["articulated_credit_hours"])
    if effective_articulated > effective_credit:
        shape.bad("Field 'articulated_credit_hours' may not exceed 'credit_hours'.")

    if prerequisite_given and prerequisite_id is not None:
        resolve.course(prerequisite_id)
    program = resolve.program(course["pos_id"])
    services.refresh_clna(program)

    probe = dict(course)
    if position is not None:
        probe["position"] = position
    probe["prerequisite_course_id"] = prerequisite_id
    _check_prerequisite(probe, prerequisite_id)

    if status is not None:
        course["status"] = status
    if credit_hours is not None:
        course["credit_hours"] = credit_hours
    if articulated is not None:
        course["articulated_credit_hours"] = articulated
    if articulation_verified is not None:
        course["articulation_verified"] = articulation_verified
    if position is not None:
        course["position"] = position
    if prerequisite_given:
        course["prerequisite_course_id"] = prerequisite_id
    touch(course)
    calc.refresh_subtotals(program)
    touch(program)
    return ok(serialize.course(course))


@bp.post("/cte/programs-of-study/<pos_id>/credentials")
@endpoint(DIRECTOR)
def create_credential(pos_id):
    data = shape.body()
    code = shape.req_string(data, "code", min_len=1, max_len=32)
    title = shape.req_string(data, "title")
    tier = shape.req_enum(data, "tier", CREDENTIAL_TIERS)
    exam_required = shape.opt_bool(data, "exam_required", default=True)
    program = resolve.program(pos_id)
    services.refresh_clna(program)
    for existing in db.credentials.values():
        if existing["pos_id"] == pos_id and existing["code"] == code:
            raise ApiError("ERR_CREDENTIAL_CODE_DUPLICATE",
                           "Credential code '%s' already exists on this program."
                           % code)
    credential = stamp_new({
        "pos_id": pos_id,
        "code": code,
        "title": title,
        "tier": tier,
        "exam_required": exam_required,
        "counts_toward_indicator": tier in ("STATE_RECOGNIZED", "NATIONAL"),
    })
    db.credentials[credential["id"]] = credential
    touch(program)
    return created(serialize.credential(credential))
