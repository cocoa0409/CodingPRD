"""Course catalog endpoints: create, list, get."""
from flask import Blueprint, request

from db import new_id, stamp_new, store
from errors import ApiError
from middleware import READERS, auth_context, require_role
from response import ok_list, ok_obj, page_of, pagination_args
from services.serializers import course_out
from validators import body, req_enum, req_num, req_str

bp = Blueprint("courses", __name__)

GRADE_BANDS = {"ELEMENTARY", "MIDDLE", "HIGH", "ALL"}


@bp.post("/sis/courses")
def create_course():
    _uid, role = auth_context()
    data = body()
    district_id = req_str(data, "district_id")
    course_code = req_str(data, "course_code")
    title = req_str(data, "title")
    credit_hours = req_num(data, "credit_hours")
    grade_band = req_enum(data, "grade_band", GRADE_BANDS)
    state_course_code = req_str(data, "state_course_code")
    if credit_hours <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "credit_hours must be > 0")
    require_role(role, {"Registrar"})
    district = store["districts"].get(district_id)
    if not district:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "district_id does not reference an existing district")
    for c in store["courses"].values():
        if c["district_id"] == district_id and c["course_code"] == course_code:
            raise ApiError("ERR_DUPLICATE_COURSE_CODE", 409,
                           "course_code already used in the district")
    c = {"id": new_id(), "district_id": district_id,
         "course_code": course_code, "title": title,
         "credit_hours": credit_hours, "grade_band": grade_band,
         "state_course_code": state_course_code}
    stamp_new(c)
    store["courses"][c["id"]] = c
    return ok_obj(course_out(c), 201)


@bp.get("/sis/courses")
def list_courses():
    _uid, role = auth_context()
    require_role(role, READERS)
    limit, offset = pagination_args()
    district_id = request.args.get("district_id")
    items = [c for c in store["courses"].values()
             if district_id is None or c["district_id"] == district_id]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    total = len(items)
    page = page_of(items, limit, offset)
    return ok_list([course_out(c) for c in page], total, limit, offset)


@bp.get("/sis/courses/<cid>")
def get_course(cid):
    _uid, role = auth_context()
    require_role(role, READERS)
    c = store["courses"].get(cid)
    if not c:
        raise ApiError("ERR_COURSE_NOT_FOUND", 404,
                       "No course with the given id")
    return ok_obj(course_out(c))
