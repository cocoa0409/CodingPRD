"""Teacher registry and employment review."""
from flask import request

import store
from envelope import ok, page_payload
from errors import bad_request, conflict, invalid_state, not_found
from security import actor, require_roles
from serializers import teacher_json
from validators import (
    as_enum,
    as_str,
    as_subject_list,
    json_body,
    pagination_args,
    require_present,
)

EMPLOYMENT_ACTIONS = ("VERIFY", "REINSTATE")


def _open_fraud_case_exists(teacher_id):
    return any(
        fc["teacher_id"] == teacher_id and fc["status"] == "OPEN"
        for fc in store.fraud_cases.values()
    )


def register(app):
    @app.route("/giving/teachers", methods=["POST"])
    def create_teacher():
        data = json_body()
        full_name = as_str(require_present(data, "full_name"), "full_name")
        email = as_str(require_present(data, "email"), "email")
        school_id = as_str(require_present(data, "school_id"), "school_id")
        subjects_taught = []
        if "subjects_taught" in data and data["subjects_taught"] is not None:
            subjects_taught = as_subject_list(data["subjects_taught"], "subjects_taught")
        _, role = actor()
        require_roles(role, ("Anonymous",))
        if school_id not in store.schools:
            raise not_found("School not found")
        if any(t["email"] == email for t in store.teachers.values()):
            raise bad_request("email must be unique across teachers")
        rec = store.base_record()
        rec.update({
            "school_id": school_id,
            "full_name": full_name,
            "email": email,
            "subjects_taught": subjects_taught,
            "employment_status": "PENDING_VERIFICATION",
        })
        store.teachers[rec["id"]] = rec
        return ok(teacher_json(rec), 201)

    @app.route("/giving/teachers/<teacher_id>", methods=["GET"])
    def get_teacher(teacher_id):
        _, role = actor()
        require_roles(role, ("PlatformAdmin", "Reviewer", "Teacher"))
        teacher = store.teachers.get(teacher_id)
        if teacher is None:
            raise not_found("Teacher not found")
        return ok(teacher_json(teacher), 200)

    @app.route("/giving/teachers", methods=["GET"])
    def list_teachers():
        _, role = actor()
        require_roles(role, ("PlatformAdmin", "Reviewer"))
        school_id = request.args.get("school_id")
        employment_status = request.args.get("employment_status")
        rows = list(store.teachers.values())
        if school_id is not None:
            rows = [t for t in rows if t["school_id"] == school_id]
        if employment_status is not None:
            rows = [t for t in rows if t["employment_status"] == employment_status]
        rows.sort(key=lambda t: (t["created_at"], t["_seq"]))
        limit, offset = pagination_args()
        page, meta = page_payload([teacher_json(t) for t in rows], limit, offset)
        return ok(page, 200, pagination=meta)

    @app.route("/giving/teachers/<teacher_id>/employment-review", methods=["POST"])
    def employment_review(teacher_id):
        data = json_body()
        action = as_enum(require_present(data, "action"), "action", EMPLOYMENT_ACTIONS)
        _, role = actor()
        require_roles(role, ("PlatformAdmin",))
        teacher = store.teachers.get(teacher_id)
        if teacher is None:
            raise not_found("Teacher not found")
        if action == "VERIFY":
            if teacher["employment_status"] != "PENDING_VERIFICATION":
                raise invalid_state("Only a PENDING_VERIFICATION teacher can be verified")
        else:  # REINSTATE
            if teacher["employment_status"] != "SUSPENDED":
                raise invalid_state("Only a SUSPENDED teacher can be reinstated")
            if _open_fraud_case_exists(teacher_id):
                raise conflict(
                    "ERR_FRAUD_CASE_ALREADY_OPEN",
                    "An OPEN fraud case already exists for this teacher",
                )
        teacher["employment_status"] = "VERIFIED"
        store.touch(teacher)
        return ok(teacher_json(teacher), 200)
