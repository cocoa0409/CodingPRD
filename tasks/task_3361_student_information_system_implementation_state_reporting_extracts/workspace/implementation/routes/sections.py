"""Section endpoints: create/list/get, roster list, commit, cancel,
assign-teacher, roster-adds, roster-drops."""
from flask import Blueprint, request

from db import new_id, next_seq, now_iso, stamp_new, store, touch
from errors import ApiError
from middleware import READERS, auth_context, require_role
from response import ok_list, ok_obj, page_of, pagination_args
from services.serializers import enrollment_out, section_out
from validators import body, req_int, req_str

bp = Blueprint("sections", __name__)

ROSTERABLE = ("DRAFT", "COMMITTED")
BUFFER_MIN = 10  # ten-minute turnover buffer between conflicting sections


def _get_section_or_404(sid):
    s = store["sections"].get(sid)
    if not s:
        raise ApiError("ERR_SECTION_NOT_FOUND", 404,
                       "No section with the given id")
    return s


@bp.post("/sis/sections")
def create_section():
    _uid, role = auth_context()
    data = body()
    course_id = req_str(data, "course_id")
    school_year_id = req_str(data, "school_year_id")
    term_label = req_str(data, "term_label")
    room = req_str(data, "room")
    period_start_min = req_int(data, "period_start_min")
    period_end_min = req_int(data, "period_end_min")
    capacity = req_int(data, "capacity")
    # teacher_ref optional; explicit null unassigns/keeps unassigned.
    teacher_ref = data.get("teacher_ref")
    if teacher_ref is not None and not isinstance(teacher_ref, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "teacher_ref must be a string or null")
    if capacity <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "capacity must be > 0")
    require_role(role, {"Registrar"})
    course = store["courses"].get(course_id)
    if not course:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "course_id does not reference an existing course")
    year = store["school_years"].get(school_year_id)
    if not year:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "school_year_id does not reference an existing school year")
    if course["district_id"] != year["district_id"]:
        raise ApiError("ERR_DISTRICT_MISMATCH", 422,
                       "course and school year belong to different districts")
    if not (period_end_min > period_start_min):
        raise ApiError("ERR_INVALID_DATE_RANGE", 422,
                       "period_end_min must be after period_start_min")
    s = {"id": new_id(), "course_id": course_id,
         "school_year_id": school_year_id, "teacher_ref": teacher_ref,
         "term_label": term_label, "room": room,
         "period_start_min": period_start_min,
         "period_end_min": period_end_min, "capacity": capacity,
         "roster_count": 0, "status": "DRAFT"}
    stamp_new(s)
    store["sections"][s["id"]] = s
    return ok_obj(section_out(s), 201)


@bp.get("/sis/sections")
def list_sections():
    _uid, role = auth_context()
    require_role(role, READERS)
    limit, offset = pagination_args()
    school_year_id = request.args.get("school_year_id")
    course_id = request.args.get("course_id")
    teacher_ref = request.args.get("teacher_ref")
    room = request.args.get("room")
    status = request.args.get("status")
    items = [s for s in store["sections"].values()
             if (school_year_id is None or s["school_year_id"] == school_year_id)
             and (course_id is None or s["course_id"] == course_id)
             and (teacher_ref is None or s["teacher_ref"] == teacher_ref)
             and (room is None or s["room"] == room)
             and (status is None or s["status"] == status)]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(items)
    page = page_of(items, limit, offset)
    return ok_list([section_out(s) for s in page], total, limit, offset)


@bp.get("/sis/sections/<sid>")
def get_section(sid):
    _uid, role = auth_context()
    require_role(role, READERS)
    return ok_obj(section_out(_get_section_or_404(sid)))


@bp.get("/sis/sections/<sid>/roster")
def get_roster(sid):
    _uid, role = auth_context()
    require_role(role, {"DistrictAdmin", "Registrar"})
    _get_section_or_404(sid)
    limit, offset = pagination_args()
    enrollments = [store["enrollments"][k[1]]
                   for k, v in store["roster_links"].items()
                   if k[0] == sid and v["active"] and k[1] in store["enrollments"]]
    enrollments.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(enrollments)
    page = page_of(enrollments, limit, offset)
    return ok_list([enrollment_out(e) for e in page], total, limit, offset)


@bp.post("/sis/sections/<sid>/commit")
def commit_section(sid):
    _uid, role = auth_context()
    require_role(role, {"Registrar"})
    s = _get_section_or_404(sid)
    if s["status"] != "DRAFT":
        raise ApiError("ERR_SECTION_NOT_DRAFT", 409,
                       "Commit requires section DRAFT")
    year = store["school_years"].get(s["school_year_id"])
    if not year or year["status"] != "OPEN":
        raise ApiError("ERR_YEAR_NOT_OPEN", 409,
                       "Section commit requires school year OPEN")
    if s["teacher_ref"] is None:
        raise ApiError("ERR_TEACHER_REQUIRED", 422,
                       "Section commit requires a non-null teacher_ref")
    # Buffered-overlap: conflict with a COMMITTED section of the same year
    # sharing room or teacher unless >= 10 minutes separate the windows;
    # exact abutment is rejected.
    for other in store["sections"].values():
        if other["id"] == s["id"] or other["status"] != "COMMITTED":
            continue
        if other["school_year_id"] != s["school_year_id"]:
            continue
        shares = (other["room"] == s["room"]
                  or other["teacher_ref"] == s["teacher_ref"])
        if not shares:
            continue
        separated = (s["period_end_min"] + BUFFER_MIN <= other["period_start_min"]
                     or other["period_end_min"] + BUFFER_MIN <= s["period_start_min"])
        if not separated:
            raise ApiError("ERR_SECTION_TIME_OVERLAP", 409,
                           "Committed section shares room or teacher with a gap < 10 minutes")
    if s["roster_count"] > s["capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409,
                       "roster_count exceeds capacity")
    s["status"] = "COMMITTED"
    touch(s)
    return ok_obj(section_out(s))


@bp.post("/sis/sections/<sid>/cancel")
def cancel_section(sid):
    _uid, role = auth_context()
    require_role(role, {"Registrar"})
    s = _get_section_or_404(sid)
    if s["status"] not in ROSTERABLE:
        raise ApiError("ERR_SECTION_NOT_CANCELLABLE", 409,
                       "Cancel requires section DRAFT or COMMITTED")
    for key, link in store["roster_links"].items():
        if key[0] == sid and link["active"]:
            link["active"] = False
    s["roster_count"] = 0
    s["status"] = "CANCELLED"
    touch(s)
    return ok_obj(section_out(s))


@bp.post("/sis/sections/<sid>/assign-teacher")
def assign_teacher(sid):
    _uid, role = auth_context()
    data = body()
    if "teacher_ref" not in data:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Invalid or missing field: teacher_ref")
    teacher_ref = data["teacher_ref"]
    if teacher_ref is not None and not isinstance(teacher_ref, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "teacher_ref must be a string or null")
    require_role(role, {"Registrar"})
    s = _get_section_or_404(sid)
    if s["status"] not in ROSTERABLE:
        raise ApiError("ERR_SECTION_NOT_ROSTERABLE", 409,
                       "Assign-teacher requires section DRAFT or COMMITTED")
    s["teacher_ref"] = teacher_ref
    touch(s)
    return ok_obj(section_out(s))


@bp.post("/sis/sections/<sid>/roster-adds")
def roster_add(sid):
    _uid, role = auth_context()
    data = body()
    enrollment_id = req_str(data, "enrollment_id")
    require_role(role, {"Registrar"})
    s = _get_section_or_404(sid)
    if s["status"] not in ROSTERABLE:
        raise ApiError("ERR_SECTION_NOT_ROSTERABLE", 409,
                       "Roster-add requires section DRAFT or COMMITTED")
    e = store["enrollments"].get(enrollment_id)
    if not e:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "enrollment_id does not reference an existing enrollment")
    sec_year = store["school_years"].get(s["school_year_id"])
    enr_year = store["school_years"].get(e["school_year_id"])
    if (sec_year and enr_year
            and sec_year["district_id"] != enr_year["district_id"]):
        raise ApiError("ERR_DISTRICT_MISMATCH", 422,
                       "section and enrollment belong to different districts")
    if e["lifecycle"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", 409,
                       "Roster-add requires enrollment lifecycle ACTIVE")
    key = (sid, enrollment_id)
    link = store["roster_links"].get(key)
    if link and link["active"]:
        raise ApiError("ERR_DUPLICATE_ROSTER", 409,
                       "Enrollment already actively rostered in this section")
    # Capacity is checked last: a full section rejects, equality included.
    if s["roster_count"] >= s["capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409,
                       "roster_count >= capacity; the section is full")
    if link:
        link["active"] = True
        link["created_at"] = now_iso()
        link["_seq"] = next_seq()
    else:
        store["roster_links"][key] = {"active": True, "created_at": now_iso(),
                                      "_seq": next_seq()}
    s["roster_count"] += 1
    touch(s)
    return ok_obj(section_out(s), 201)


@bp.post("/sis/sections/<sid>/roster-drops")
def roster_drop(sid):
    _uid, role = auth_context()
    data = body()
    enrollment_id = req_str(data, "enrollment_id")
    require_role(role, {"Registrar"})
    s = _get_section_or_404(sid)
    if s["status"] not in ROSTERABLE:
        raise ApiError("ERR_SECTION_NOT_ROSTERABLE", 409,
                       "Roster-drop requires section DRAFT or COMMITTED")
    if enrollment_id not in store["enrollments"]:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "enrollment_id does not reference an existing enrollment")
    key = (sid, enrollment_id)
    link = store["roster_links"].get(key)
    if not link or not link["active"]:
        raise ApiError("ERR_ROSTER_NOT_FOUND", 404,
                       "No active roster link for the given enrollment in this section")
    link["active"] = False
    s["roster_count"] -= 1
    touch(s)
    return ok_obj(section_out(s))
