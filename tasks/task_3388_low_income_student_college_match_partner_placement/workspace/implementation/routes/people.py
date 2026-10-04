"""Counselor, CommunityPartner, and Student registration and reads."""
from flask import Blueprint

import serializers
import store
from auth import ALL_AUTHENTICATED, forbid, identity, require_roles
from errors import ApiError, ERR_EMAIL_TAKEN, ERR_NOT_FOUND
from response import ok_object, paginated
from validation import KIND_ENUM, KIND_STR, get_body, validate

bp = Blueprint("people", __name__)

STUDENT_SOURCES = ("SELF", "COUNSELOR", "COMMUNITY_PARTNER", "PREP_PROGRAM")


@bp.post("/counselors")
def create_counselor():
    body = get_body()
    values = validate(body, [
        ("full_name", KIND_STR, True, None, None),
        ("school_name", KIND_STR, True, None, None),
        ("state_code", KIND_STR, True, None, None),
    ])
    role, _ = identity()
    require_roles(role, ("ProgramAdmin",))
    counselor = store.create(store.counselors, {
        "full_name": values["full_name"],
        "school_name": values["school_name"],
        "state_code": values["state_code"],
    })
    return ok_object(serializers.counselor(counselor), 201)


@bp.get("/counselors/<counselor_id>")
def get_counselor(counselor_id):
    role, _ = identity()
    require_roles(role, ALL_AUTHENTICATED)
    counselor = store.counselors.get(counselor_id)
    if counselor is None:
        raise ApiError(ERR_NOT_FOUND, "counselor not found")
    return ok_object(serializers.counselor(counselor))


@bp.post("/community-partners")
def create_partner():
    body = get_body()
    values = validate(body, [
        ("org_name", KIND_STR, True, None, None),
        ("state_code", KIND_STR, True, None, None),
        ("contact_email", KIND_STR, True, None, None),
    ])
    role, _ = identity()
    require_roles(role, ("ProgramAdmin",))
    partner = store.create(store.partners, {
        "org_name": values["org_name"],
        "state_code": values["state_code"],
        "contact_email": values["contact_email"],
    })
    return ok_object(serializers.partner(partner), 201)


@bp.get("/community-partners/<partner_id>")
def get_partner(partner_id):
    role, _ = identity()
    require_roles(role, ALL_AUTHENTICATED)
    partner = store.partners.get(partner_id)
    if partner is None:
        raise ApiError(ERR_NOT_FOUND, "community partner not found")
    return ok_object(serializers.partner(partner))


@bp.post("/students")
def create_student():
    body = get_body()
    values = validate(body, [
        ("email", KIND_STR, True, None, None),
        ("full_name", KIND_STR, True, None, None),
        ("state_code", KIND_STR, True, None, None),
        ("source", KIND_ENUM, True, None, STUDENT_SOURCES),
    ])
    role, _ = identity()
    require_roles(role, ("Anonymous",))
    for existing in store.students.values():
        if existing["email"] == values["email"]:
            raise ApiError(ERR_EMAIL_TAKEN, "a student with this email already exists")
    student = store.create(store.students, {
        "email": values["email"],
        "full_name": values["full_name"],
        "state_code": values["state_code"],
        "source": values["source"],
        "student_stage": "PROSPECT",
    })
    return ok_object(serializers.student(student), 201)


@bp.get("/students/<student_id>")
def get_student(student_id):
    role, uid = identity()
    require_roles(role, ALL_AUTHENTICATED)
    student = store.students.get(student_id)
    if student is None:
        raise ApiError(ERR_NOT_FOUND, "student not found")
    if role == "Student" and uid != student["id"]:
        forbid("a student may only view their own record")
    return ok_object(serializers.student(student))


@bp.get("/students/<student_id>/prep-programs")
def student_prep_programs(student_id):
    role, uid = identity()
    require_roles(role, ("ProgramAdmin", "Student", "Counselor", "PartnerStaff"))
    student = store.students.get(student_id)
    if student is None:
        raise ApiError(ERR_NOT_FOUND, "student not found")
    if role == "Student" and uid != student["id"]:
        forbid("a student may only view their own prep programs")
    items = [p for p in store.prep_programs.values() if p["student_id"] == student["id"]]
    items.sort(key=lambda p: p["created_at"])
    return paginated(items, serializers.prep_program)
