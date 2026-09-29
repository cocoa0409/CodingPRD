"""Teacher and privacy-analyst enrolment (PRD 3.2, 3.3)."""
from flask import Blueprint

from core import auth, envelope, logic, serialize, store, validate
from core.errors import ApiError
from core.validate import F

bp = Blueprint("people", __name__)


@bp.post("/teachers")
def enroll_teacher():
    auth.actor("PrivacyOfficeAdmin")
    data = validate.body([
        F("full_name", "str", lo=1, hi=120, nonblank=True),
        F("employee_number", "str", lo=1, hi=32, nonblank=True),
        F("school_code", "str", lo=1, hi=16, nonblank=True),
        F("grade_bands_taught", "int_array", item_lo=0, item_hi=12, min_items=1),
    ])
    # Outside the numbered ladder, checked straight after shape validation.
    for existing in store.teachers.values():
        if existing["employee_number"] == data["employee_number"]:
            raise ApiError("ERR_DUPLICATE_EMPLOYEE_NUMBER")

    row = store.new_row({
        "full_name": data["full_name"],
        "employee_number": data["employee_number"],
        "school_code": data["school_code"],
        "grade_bands_taught": data["grade_bands_taught"],
        "open_request_count": 0,
        "status": "ACTIVE",
    })
    store.teachers[row["id"]] = row
    return envelope.created(serialize.teacher(row))


@bp.get("/teachers/<teacher_id>")
def read_teacher(teacher_id):
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "Teacher")
    return envelope.ok(serialize.teacher(auth.need("teacher", teacher_id)))


@bp.post("/privacy-analysts")
def enroll_analyst():
    auth.actor("PrivacyOfficeAdmin")
    data = validate.body([
        F("full_name", "str", lo=1, hi=120, nonblank=True),
        F("credential_level", "enum", members=set(logic.CREDENTIAL_LEVELS)),
        F("review_capacity_minutes", "int", lo=15, hi=12000),
    ])
    row = store.new_row({
        "full_name": data["full_name"],
        "credential_level": data["credential_level"],
        "review_capacity_minutes": data["review_capacity_minutes"],
        "allocated_review_minutes": 0,
        "status": "ACTIVE",
    })
    store.analysts[row["id"]] = row
    return envelope.created(serialize.analyst(row))


@bp.get("/privacy-analysts/<analyst_id>")
def read_analyst(analyst_id):
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst")
    return envelope.ok(serialize.analyst(auth.need("analyst", analyst_id)))
