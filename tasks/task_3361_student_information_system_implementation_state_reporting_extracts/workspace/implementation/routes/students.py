"""Student endpoints: register, list (ARCHIVED hidden unless filtered), get."""
from flask import Blueprint, request

from db import new_id, stamp_new, store
from errors import ApiError
from middleware import READERS, auth_context, require_role
from response import ok_list, ok_obj, page_of, pagination_args
from services.calc import GRADES
from services.serializers import student_out
from validators import body, req_dt, req_enum, req_str

bp = Blueprint("students", __name__)


@bp.post("/sis/students")
def create_student():
    _uid, role = auth_context()
    data = body()
    district_id = req_str(data, "district_id")
    student_number = req_str(data, "student_number")
    first_name = req_str(data, "first_name")
    last_name = req_str(data, "last_name")
    birth_date = req_dt(data, "birth_date")
    entry_grade_level = req_enum(data, "entry_grade_level", set(GRADES))
    require_role(role, {"Registrar"})
    district = store["districts"].get(district_id)
    if not district:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "district_id does not reference an existing district")
    # student_number unique per district among non-ARCHIVED students.
    for s in store["students"].values():
        if (s["district_id"] == district_id
                and s["student_number"] == student_number
                and s["status"] != "ARCHIVED"):
            raise ApiError("ERR_DUPLICATE_STUDENT_NUMBER", 409,
                           "student_number already used by a non-ARCHIVED student of the district")
    s = {"id": new_id(), "district_id": district_id,
         "student_number": student_number, "first_name": first_name,
         "last_name": last_name, "birth_date": birth_date,
         "entry_grade_level": entry_grade_level, "status": "PRE_REGISTERED"}
    stamp_new(s)
    store["students"][s["id"]] = s
    return ok_obj(student_out(s), 201)


@bp.get("/sis/students")
def list_students():
    _uid, role = auth_context()
    require_role(role, READERS)
    limit, offset = pagination_args()
    district_id = request.args.get("district_id")
    status = request.args.get("status")
    items = []
    for s in store["students"].values():
        if district_id is not None and s["district_id"] != district_id:
            continue
        if status is None:
            # ARCHIVED students excluded unless status=ARCHIVED is passed.
            if s["status"] == "ARCHIVED":
                continue
        elif s["status"] != status:
            continue
        items.append(s)
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(items)
    page = page_of(items, limit, offset)
    return ok_list([student_out(s) for s in page], total, limit, offset)


@bp.get("/sis/students/<sid>")
def get_student(sid):
    _uid, role = auth_context()
    require_role(role, READERS)
    s = store["students"].get(sid)
    if not s:
        raise ApiError("ERR_STUDENT_NOT_FOUND", 404,
                       "No student with the given id")
    return ok_obj(student_out(s))
