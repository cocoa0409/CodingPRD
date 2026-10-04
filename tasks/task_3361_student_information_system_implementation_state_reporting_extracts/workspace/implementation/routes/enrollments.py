"""Enrollment endpoints: create/list/get, withdraw, reenter, and the nested
attendance-event sub-resources."""
from flask import Blueprint, request

from dates import whole_days
from db import new_id, next_seq, now_iso, stamp_new, store, touch
from errors import ApiError
from middleware import READERS, auth_context, require_role
from response import ok_list, ok_obj, page_of, pagination_args
from services.calc import (GRADES, create_enrollment_record,
                           get_published_spec, infer_exit_date,
                           recompute_enrollment)
from services.serializers import enrollment_out, event_out
from validators import body, opt_dt, opt_str, req_dt, req_enum, req_str

bp = Blueprint("enrollments", __name__)


def _get_enrollment_or_404(eid):
    e = store["enrollments"].get(eid)
    if not e:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404,
                       "No enrollment with the given id")
    return e


@bp.post("/sis/enrollments")
def create_enrollment():
    _uid, role = auth_context()
    data = body()
    student_id = req_str(data, "student_id")
    school_year_id = req_str(data, "school_year_id")
    grade_level = req_enum(data, "grade_level", set(GRADES))
    entry_date = req_dt(data, "entry_date")
    program_code = opt_str(data, "program_code", None)
    require_role(role, {"Registrar"})
    year = store["school_years"].get(school_year_id)
    if not year:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "school_year_id does not reference an existing school year")
    district = store["districts"].get(year["district_id"])
    if not district or district["status"] != "LIVE":
        raise ApiError("ERR_DISTRICT_NOT_LIVE", 409,
                       "Enrollment create requires district LIVE")
    if year["status"] != "OPEN":
        raise ApiError("ERR_YEAR_NOT_OPEN", 409,
                       "Enrollment create requires year OPEN")
    student = store["students"].get(student_id)
    if not student:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "student_id does not reference an existing student")
    if student["district_id"] != year["district_id"]:
        raise ApiError("ERR_DISTRICT_MISMATCH", 422,
                       "student and school year belong to different districts")
    if not (year["start_date"] <= entry_date < year["end_date"]):
        raise ApiError("ERR_ENTRY_OUTSIDE_YEAR", 422,
                       "entry_date must lie within [year.start_date, year.end_date)")
    state_program_code = None
    program_weight = 1.0
    if program_code is not None:
        spec = get_published_spec(district["state_code"])
        if not spec:
            raise ApiError("ERR_SPEC_NOT_PUBLISHED", 409,
                           "No PUBLISHED spec for the district's state")
        mapping = spec["program_code_map"].get(program_code)
        if mapping is None:
            raise ApiError("ERR_UNMAPPED_PROGRAM_CODE", 422,
                           "program_code absent from the PUBLISHED spec program_code_map")
        state_program_code = mapping.get("state_program_code")
        program_weight = mapping.get("weight_factor", 1.0)
    for e in store["enrollments"].values():
        if (e["student_id"] == student_id
                and e["school_year_id"] == school_year_id):
            raise ApiError("ERR_DUPLICATE_ENROLLMENT", 409,
                           "Student already has an enrollment (any lifecycle) in this school year")
    e = create_enrollment_record(student_id, year, grade_level, entry_date,
                                 program_code, state_program_code,
                                 program_weight)
    if student["status"] in ("PRE_REGISTERED", "INACTIVE"):
        student["status"] = "ENROLLED"
        touch(student)
    return ok_obj(enrollment_out(e), 201)


@bp.get("/sis/enrollments")
def list_enrollments():
    _uid, role = auth_context()
    require_role(role, READERS)
    limit, offset = pagination_args()
    student_id = request.args.get("student_id")
    school_year_id = request.args.get("school_year_id")
    lifecycle = request.args.get("lifecycle")
    absence_posture = request.args.get("absence_posture")
    items = [e for e in store["enrollments"].values()
             if (student_id is None or e["student_id"] == student_id)
             and (school_year_id is None or e["school_year_id"] == school_year_id)
             and (lifecycle is None or e["lifecycle"] == lifecycle)
             and (absence_posture is None or e["absence_posture"] == absence_posture)]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = page_of(items, limit, offset)
    return ok_list([enrollment_out(e) for e in page], total, limit, offset)


@bp.get("/sis/enrollments/<eid>")
def get_enrollment(eid):
    _uid, role = auth_context()
    require_role(role, READERS)
    return ok_obj(enrollment_out(_get_enrollment_or_404(eid)))


@bp.post("/sis/enrollments/<eid>/withdraw")
def withdraw_enrollment(eid):
    _uid, role = auth_context()
    data = body()
    exit_date = opt_dt(data, "exit_date")
    require_role(role, {"Registrar"})
    e = _get_enrollment_or_404(eid)
    if e["lifecycle"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", 409,
                       "Withdraw requires enrollment lifecycle ACTIVE")
    year = store["school_years"][e["school_year_id"]]
    if exit_date is not None:
        if not (e["entry_date"] < exit_date <= year["end_date"]):
            raise ApiError("ERR_WITHDRAWAL_OUTSIDE_YEAR", 422,
                           "exit_date must satisfy entry_date < exit_date <= year.end_date")
    else:
        exit_date = infer_exit_date(e)
    # Fold the closing segment (half-open, intersected with the year window)
    # into prior_segment_days, then close the segment.
    seg_start = max(e["entry_date"], year["start_date"])
    seg_end = min(exit_date, year["end_date"])
    e["prior_segment_days"] += max(0, whole_days(seg_start, seg_end))
    e["exit_date"] = exit_date
    e["segment_closed"] = True
    e["lifecycle"] = "WITHDRAWN"
    recompute_enrollment(e)
    touch(e)
    student = store["students"].get(e["student_id"])
    if student and student["status"] == "ENROLLED":
        has_active = any(
            o["student_id"] == student["id"] and o["lifecycle"] == "ACTIVE"
            and o["id"] != e["id"]
            for o in store["enrollments"].values())
        if not has_active:
            student["status"] = "INACTIVE"
            touch(student)
    return ok_obj(enrollment_out(e))


@bp.post("/sis/enrollments/<eid>/reenter")
def reenter_enrollment(eid):
    _uid, role = auth_context()
    data = body()
    reentry_date = req_dt(data, "reentry_date")
    require_role(role, {"Registrar"})
    e = _get_enrollment_or_404(eid)
    if e["lifecycle"] != "WITHDRAWN":
        raise ApiError("ERR_ENROLLMENT_NOT_WITHDRAWN", 409,
                       "Reenter requires enrollment lifecycle WITHDRAWN")
    year = store["school_years"][e["school_year_id"]]
    if not (e["exit_date"] < reentry_date <= year["end_date"]):
        raise ApiError("ERR_REENTRY_OUTSIDE_YEAR", 422,
                       "reentry_date must satisfy exit_date < reentry_date <= year.end_date")
    e["entry_date"] = reentry_date
    e["exit_date"] = None
    e["segment_closed"] = False
    e["lifecycle"] = "ACTIVE"
    recompute_enrollment(e)
    touch(e)
    student = store["students"].get(e["student_id"])
    if student and student["status"] == "INACTIVE":
        student["status"] = "ENROLLED"
        touch(student)
    return ok_obj(enrollment_out(e))


@bp.post("/sis/enrollments/<eid>/attendance-events")
def post_attendance_event(eid):
    _uid, role = auth_context()
    require_role(role, {"Registrar"})
    # Nested route: the enrollment identifier is validated before any
    # event-level consideration, so a nonexistent enrollment surfaces
    # ERR_ENROLLMENT_NOT_FOUND before the body is examined (PRD section 2.8).
    e = _get_enrollment_or_404(eid)
    data = body()
    attendance_date = req_dt(data, "attendance_date")
    raw_code = req_str(data, "raw_code")
    # The date must lie inside the current segment [entry_date, exit or +inf).
    if attendance_date < e["entry_date"] or (
            e["exit_date"] is not None and attendance_date >= e["exit_date"]):
        raise ApiError("ERR_ATTENDANCE_OUTSIDE_ENROLLMENT", 422,
                       "attendance_date outside the enrollment's current segment")
    year = store["school_years"][e["school_year_id"]]
    district = store["districts"].get(year["district_id"])
    spec = get_published_spec(district["state_code"]) if district else None
    if not spec:
        raise ApiError("ERR_SPEC_NOT_PUBLISHED", 409,
                       "No PUBLISHED spec for the district's state")
    mapping = spec["attendance_code_map"].get(raw_code)
    if mapping is None:
        raise ApiError("ERR_UNMAPPED_ATTENDANCE_CODE", 422,
                       "raw_code absent from the PUBLISHED spec attendance_code_map")
    ev = {"id": new_id(), "enrollment_id": e["id"],
          "attendance_date": attendance_date, "raw_code": raw_code,
          "state_attendance_code": mapping.get("state_code"),
          "absence_weight": mapping.get("absence_weight"),
          "is_excused": mapping.get("is_excused"),
          "created_at": now_iso(), "_seq": next_seq()}
    store["attendance_events"][ev["id"]] = ev
    recompute_enrollment(e)
    touch(e)
    return ok_obj(event_out(ev), 201)


@bp.get("/sis/enrollments/<eid>/attendance-events")
def list_attendance_events(eid):
    _uid, role = auth_context()
    require_role(role, READERS)
    _get_enrollment_or_404(eid)
    limit, offset = pagination_args()
    items = [ev for ev in store["attendance_events"].values()
             if ev["enrollment_id"] == eid]
    # Pinned order: attendance_date ASC, ties broken by created_at ASC.
    items.sort(key=lambda ev: (ev["attendance_date"], ev["created_at"],
                               ev["_seq"]))
    total = len(items)
    page = page_of(items, limit, offset)
    return ok_list([event_out(ev) for ev in page], total, limit, offset)
