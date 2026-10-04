"""Student routes."""
from flask import Blueprint, request
from store import store, fresh
from middleware import auth, json_body, require_fields, pagination_params, require_student_owner
from response import success_obj, success_list
from errors import not_found, invalid_request

bp = Blueprint("students", __name__)

ROLES_LIST = ["ProgramDirector", "Registrar", "CastingDirector", "PlacementOfficer", "FinanceOfficer"]


@bp.post("/students")
def create_student():
    auth(["Registrar"])
    body = json_body()
    require_fields(body, ["full_name", "email"])
    if not isinstance(body["email"], str) or not body["email"]:
        invalid_request("email must be a non-empty string")
    for s in store.students.values():
        if s["email"] == body["email"]:
            invalid_request("email must be unique")
    stu = fresh({
        "full_name": body["full_name"],
        "email": body["email"],
        "is_alumni": False,
        "is_industry_showcase_eligible": False,
        "standing": "GOOD",
        "completed_level_codes": [],
        "placement_credit_codes": [],
    })
    store.students[stu["id"]] = stu
    return success_obj(stu, 201)


@bp.get("/students")
def list_students():
    auth(ROLES_LIST)
    limit, offset = pagination_params()
    items = list(store.students.values())
    if request.args.get("is_alumni") is not None:
        val = request.args.get("is_alumni").lower() == "true"
        items = [x for x in items if x["is_alumni"] == val]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/students/<studentId>")
def get_student(studentId):
    user_id, role = auth(ROLES_LIST + ["Student"])
    stu = store.students.get(studentId)
    if not stu:
        not_found("student not found")
    if role == "Student":
        require_student_owner(user_id, role, studentId)
    return success_obj(stu)
