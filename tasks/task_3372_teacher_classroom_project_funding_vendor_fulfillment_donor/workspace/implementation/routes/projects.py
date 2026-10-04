"""Project lifecycle: create/list/read, item adds, submit, review, and the
thank-you package."""
from datetime import timedelta

from flask import request

import store
from envelope import ok, page_payload
from errors import bad_request, conflict, forbidden, invalid_state, not_found, stale, unprocessable
from security import actor, require_roles
from serializers import project_item_json, project_json, thank_you_package_json
from services import funding as funding_service
from services import pricing
from validators import (
    GRADE_BANDS,
    SUBJECTS,
    as_enum,
    as_int,
    as_str,
    json_body,
    pagination_args,
    require_present,
)

READ_ROLES = ("PlatformAdmin", "Reviewer", "Teacher", "Donor", "Vendor")
ITEM_READ_ROLES = ("PlatformAdmin", "Reviewer", "Teacher", "Donor")
ACTIVE_PIPELINE = ("DRAFT", "IN_REVIEW", "VETTING", "RETURNED", "FUNDING", "FUNDED")
EDITABLE_STATES = ("DRAFT", "RETURNED")


def _get_project(project_id):
    project = store.projects.get(project_id)
    if project is None:
        raise not_found("Project not found")
    return project


def _get_teacher(teacher_id):
    teacher = store.teachers.get(teacher_id)
    if teacher is None:
        raise not_found("Teacher not found")
    return teacher


def _employment_gate(teacher):
    """Priority 6 (pending) is evaluated before priority 7 (suspended)."""
    if teacher["employment_status"] == "PENDING_VERIFICATION":
        raise conflict("ERR_TEACHER_NOT_VERIFIED", "Teacher employment is pending verification")
    if teacher["employment_status"] == "SUSPENDED":
        raise conflict("ERR_TEACHER_SUSPENDED", "Teacher is suspended")


def _return_project(project):
    """Back to RETURNED: the pinned face lifts; provisional recomputes live."""
    project["status"] = "RETURNED"
    project["pinned_items_total_cents"] = None
    project["pinned_shipping_total_cents"] = None
    project["goal_cents"] = None
    for item in pricing.items_of(project["id"]):
        if item["pinned_unit_price_cents"] is not None:
            item["pinned_unit_price_cents"] = None
            store.touch(item)


def register(app):
    @app.route("/giving/projects", methods=["POST"])
    def create_project():
        data = json_body()
        title = as_str(require_present(data, "title"), "title")
        description = as_str(require_present(data, "description"), "description")
        subject = as_enum(require_present(data, "subject"), "subject", SUBJECTS)
        grade_band = as_enum(require_present(data, "grade_band"), "grade_band", GRADE_BANDS)
        window_days = as_int(require_present(data, "funding_window_days"), "funding_window_days")
        if not (30 <= window_days <= 180):
            raise bad_request("funding_window_days must be between 30 and 180 inclusive")
        user_id, role = actor()
        require_roles(role, ("Teacher",))
        teacher = _get_teacher(user_id)
        _employment_gate(teacher)
        for p in store.projects.values():
            if p["teacher_id"] == user_id and p["status"] in ACTIVE_PIPELINE:
                raise conflict(
                    "ERR_ACTIVE_PROJECT_EXISTS",
                    "Teacher already has an active pipeline project",
                )
        if funding_service.thank_you_debt(user_id):
            raise conflict(
                "ERR_THANK_YOU_OUTSTANDING",
                "Teacher owes a thank-you package on a fulfilled project",
            )
        rec = store.base_record()
        rec.update({
            "teacher_id": user_id,
            "school_id": teacher["school_id"],
            "title": title,
            "description": description,
            "subject": subject,
            "grade_band": grade_band,
            "funding_window_days": window_days,
            "status": "DRAFT",
            "pinned_items_total_cents": None,
            "pinned_shipping_total_cents": None,
            "goal_cents": None,
            "funding_started_at": None,
            "funding_deadline": None,
            "screened_by_id": None,
            "vetted_by_id": None,
        })
        store.projects[rec["id"]] = rec
        return ok(project_json(rec), 201)

    @app.route("/giving/projects", methods=["GET"])
    def list_projects():
        _, role = actor()
        require_roles(role, READ_ROLES)
        teacher_id = request.args.get("teacher_id")
        school_id = request.args.get("school_id")
        status = request.args.get("status")
        subject = request.args.get("subject")
        state_code = request.args.get("state_code")
        rows = list(store.projects.values())
        if teacher_id is not None:
            rows = [p for p in rows if p["teacher_id"] == teacher_id]
        if school_id is not None:
            rows = [p for p in rows if p["school_id"] == school_id]
        if status is not None:
            rows = [p for p in rows if p["status"] == status]
        if subject is not None:
            rows = [p for p in rows if p["subject"] == subject]
        if state_code is not None:
            rows = [
                p for p in rows
                if p["school_id"] in store.schools
                and store.schools[p["school_id"]]["state_code"] == state_code
            ]
        rows.sort(key=lambda p: (p["created_at"], p["_seq"]))
        limit, offset = pagination_args()
        page, meta = page_payload([project_json(p) for p in rows], limit, offset)
        return ok(page, 200, pagination=meta)

    @app.route("/giving/projects/<project_id>", methods=["GET"])
    def get_project(project_id):
        _, role = actor()
        require_roles(role, READ_ROLES)
        return ok(project_json(_get_project(project_id)), 200)

    @app.route("/giving/projects/<project_id>/items", methods=["POST"])
    def add_item(project_id):
        data = json_body()
        catalog_item_id = as_str(require_present(data, "catalog_item_id"), "catalog_item_id")
        quantity = as_int(require_present(data, "quantity"), "quantity")
        if quantity < 1:
            raise bad_request("quantity must be at least 1")
        expected = as_int(
            require_present(data, "expected_project_version"), "expected_project_version"
        )
        user_id, role = actor()
        require_roles(role, ("Teacher",))
        project = _get_project(project_id)
        if project["teacher_id"] != user_id:
            raise forbidden("A teacher may only edit their own project")
        if expected != project["version"]:
            raise stale("expected_project_version does not match the project version")
        if project["status"] not in EDITABLE_STATES:
            raise invalid_state("Project items are editable only in DRAFT or RETURNED")
        teacher = _get_teacher(user_id)
        if teacher["employment_status"] == "SUSPENDED":
            raise conflict("ERR_TEACHER_SUSPENDED", "Teacher is suspended")
        if any(
            it["project_id"] == project_id and it["catalog_item_id"] == catalog_item_id
            for it in store.project_items.values()
        ):
            raise conflict(
                "ERR_DUPLICATE_CATALOG_ITEM", "Project already contains this catalog item"
            )
        item = store.catalog_items.get(catalog_item_id)
        if item is None or item["status"] != "ACTIVE":
            raise unprocessable("ERR_CATALOG_ITEM_UNAVAILABLE", "Catalog item is unavailable")
        cap = item["max_quantity_per_project"]
        cap = 99 if cap is None else min(cap, 99)
        if quantity > cap:
            raise unprocessable(
                "ERR_CATALOG_ITEM_UNAVAILABLE", "quantity exceeds the per-project cap"
            )
        rec = store.base_record()
        rec.update({
            "project_id": project_id,
            "catalog_item_id": catalog_item_id,
            "quantity": quantity,
            "pinned_unit_price_cents": None,
        })
        store.project_items[rec["id"]] = rec
        store.touch(project)
        return ok(project_item_json(rec), 201)

    @app.route("/giving/project-items/<item_id>", methods=["GET"])
    def get_project_item(item_id):
        _, role = actor()
        require_roles(role, ITEM_READ_ROLES)
        item = store.project_items.get(item_id)
        if item is None:
            raise not_found("Project item not found")
        return ok(project_item_json(item), 200)

    @app.route("/giving/project-items", methods=["GET"])
    def list_project_items():
        _, role = actor()
        require_roles(role, ITEM_READ_ROLES)
        project_id = request.args.get("project_id")
        catalog_item_id = request.args.get("catalog_item_id")
        rows = list(store.project_items.values())
        if project_id is not None:
            rows = [it for it in rows if it["project_id"] == project_id]
        if catalog_item_id is not None:
            rows = [it for it in rows if it["catalog_item_id"] == catalog_item_id]
        rows.sort(key=lambda it: (it["created_at"], it["_seq"]))
        limit, offset = pagination_args()
        page, meta = page_payload([project_item_json(it) for it in rows], limit, offset)
        return ok(page, 200, pagination=meta)

    @app.route("/giving/projects/<project_id>/submit", methods=["POST"])
    def submit_project(project_id):
        data = json_body()
        expected = as_int(
            require_present(data, "expected_project_version"), "expected_project_version"
        )
        user_id, role = actor()
        require_roles(role, ("Teacher",))
        project = _get_project(project_id)
        if project["teacher_id"] != user_id:
            raise forbidden("A teacher may only submit their own project")
        if expected != project["version"]:
            raise stale("expected_project_version does not match the project version")
        if project["status"] not in EDITABLE_STATES:
            raise invalid_state("Only a DRAFT or RETURNED project can be submitted")
        teacher = _get_teacher(user_id)
        _employment_gate(teacher)
        items = pricing.items_of(project_id)
        if not items:
            raise unprocessable("ERR_NO_ITEMS", "Project has no items")
        # Pin prices at the submit instant and freeze the goal.
        items_total = 0
        for it in items:
            ci = store.catalog_items[it["catalog_item_id"]]
            items_total += ci["unit_price_cents"] * it["quantity"]
        shipping_total = 0
        for pairs in pricing.vendor_groups(project_id).values():
            shipping_total += pricing.shipping_quote(pricing.shipping_lines(pairs))
        goal = items_total + shipping_total
        if not (pricing.GOAL_MIN_CENTS <= goal <= pricing.GOAL_MAX_CENTS):
            raise unprocessable(
                "ERR_GOAL_OUT_OF_RANGE", "Computed goal_cents is outside [10000, 200000]"
            )
        was_returned = project["status"] == "RETURNED"
        for it in items:
            it["pinned_unit_price_cents"] = store.catalog_items[it["catalog_item_id"]][
                "unit_price_cents"
            ]
            store.touch(it)
        project["pinned_items_total_cents"] = items_total
        project["pinned_shipping_total_cents"] = shipping_total
        project["goal_cents"] = goal
        project["status"] = "IN_REVIEW"
        if was_returned:
            project["screened_by_id"] = None
            project["vetted_by_id"] = None
        store.touch(project)
        return ok(project_json(project), 200)

    @app.route("/giving/projects/<project_id>/review", methods=["POST"])
    def review_project(project_id):
        data = json_body()
        stage = as_enum(require_present(data, "stage"), "stage", ("SCREEN", "VET"))
        outcome = as_enum(
            require_present(data, "outcome"), "outcome", ("APPROVE", "RETURN", "REJECT")
        )
        if outcome == "REJECT" and stage != "VET":
            raise bad_request("REJECT is permitted only at the VET stage")
        user_id, role = actor()
        require_roles(role, ("Reviewer",))
        project = _get_project(project_id)
        if stage == "SCREEN":
            if project["status"] != "IN_REVIEW":
                raise invalid_state("SCREEN applies only to an IN_REVIEW project")
        else:
            if project["status"] != "VETTING":
                raise invalid_state("VET applies only to a VETTING project")
            if project["screened_by_id"] == user_id:
                raise conflict(
                    "ERR_SEGREGATION_OF_DUTIES",
                    "The reviewer who screened a project may not vet it",
                )
        now = store.logical_now()
        if stage == "SCREEN" and outcome == "APPROVE":
            project["status"] = "VETTING"
            project["screened_by_id"] = user_id
        elif stage == "SCREEN" and outcome == "RETURN":
            _return_project(project)
        elif stage == "VET" and outcome == "APPROVE":
            project["status"] = "FUNDING"
            project["vetted_by_id"] = user_id
            project["funding_started_at"] = now
            project["funding_deadline"] = now + timedelta(days=project["funding_window_days"])
        elif stage == "VET" and outcome == "RETURN":
            _return_project(project)
        else:  # VET + REJECT
            project["status"] = "REJECTED"
        store.touch(project)
        return ok(project_json(project), 200)

    @app.route("/giving/projects/<project_id>/thank-you-package", methods=["POST"])
    def submit_thank_you_package(project_id):
        data = json_body()
        note = as_str(require_present(data, "thank_you_note"), "thank_you_note")
        report = as_str(require_present(data, "impact_report"), "impact_report")
        if len(note) < 20:
            raise bad_request("thank_you_note must be at least 20 characters")
        if len(report) < 40:
            raise bad_request("impact_report must be at least 40 characters")
        user_id, role = actor()
        require_roles(role, ("Teacher",))
        project = _get_project(project_id)
        if project["teacher_id"] != user_id:
            raise forbidden("Only the project's owning teacher may submit the package")
        if project["status"] != "FULFILLED":
            raise invalid_state("Thank-you package submits only while the project is FULFILLED")
        package = next(
            (p for p in store.thank_you_packages.values() if p["project_id"] == project_id),
            None,
        )
        if package is None or package["status"] != "PENDING":
            raise invalid_state("No PENDING thank-you package for this project")
        teacher = _get_teacher(user_id)
        if teacher["employment_status"] == "SUSPENDED":
            raise conflict("ERR_TEACHER_SUSPENDED", "Teacher is suspended")
        package["status"] = "SUBMITTED"
        package["thank_you_note"] = note
        package["impact_report"] = report
        package["submitted_at"] = store.logical_now()
        project["status"] = "CLOSED"
        store.touch(project)
        return ok(thank_you_package_json(package), 200)

    @app.route("/giving/projects/<project_id>/thank-you-package", methods=["GET"])
    def get_thank_you_package(project_id):
        _, role = actor()
        require_roles(role, ("PlatformAdmin", "Reviewer", "Teacher"))
        _get_project(project_id)
        packages = [
            p for p in store.thank_you_packages.values() if p["project_id"] == project_id
        ]
        packages.sort(key=lambda p: (p["created_at"], p["_seq"]))
        limit, offset = pagination_args()
        page, meta = page_payload(
            [thank_you_package_json(p) for p in packages], limit, offset
        )
        return ok(page, 200, pagination=meta)
