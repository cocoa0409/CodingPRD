"""Cooperating teacher and university supervisor endpoints (PRD 3.4)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import clock
import derive
import envelope
import shapes
import store
import views
from auth import endpoint
from errors import ApiError

bp = Blueprint("bench", __name__)

TEACHER_READERS = ["SupervisionLead", "PlacementCoordinator", "ProgramAdmin"]
SUPERVISOR_READERS = ["SupervisionLead", "PlacementCoordinator", "ProgramAdmin",
                      "UniversitySupervisorUser"]


# --- cooperating teachers --------------------------------------------------

@bp.post("/epp/cooperating-teachers")
@endpoint(["SupervisionLead"])
def create_teacher():
    body = shapes.body_of(request)
    district_id = shapes.req_str(body, "district_id", 1, None)
    full_name = shapes.req_str(body, "full_name", 1, 120)
    site_name = shapes.req_str(body, "site_name", 1, 120)
    site_grid_x = shapes.req_int(body, "site_grid_x", -500, 500)
    site_grid_y = shapes.req_int(body, "site_grid_y", -500, 500)
    subject = shapes.req_enum(body, "subject_endorsement", shapes.SUBJECTS)
    grade_band = shapes.req_enum(body, "grade_band", shapes.GRADE_BANDS)
    years = shapes.req_int(body, "years_experience", 0, 50)
    consecutive = shapes.opt_int(body, "consecutive_terms_hosted", 0, 20, 0)
    max_concurrent = shapes.opt_int(body, "max_concurrent_candidates", 1, 3, 1)

    district = store.get_district(district_id)

    row = store.new_row({
        "district_id": district["id"],
        "full_name": full_name,
        "site_name": site_name,
        "site_grid_x": site_grid_x,
        "site_grid_y": site_grid_y,
        "subject_endorsement": subject,
        "grade_band": grade_band,
        "years_experience": years,
        "consecutive_terms_hosted": consecutive,
        "max_concurrent_candidates": max_concurrent,
        "qualification_status": "PENDING_TRAINING",
        "training_completed_on": None,
        "training_expires_on": None,
        "active_placement_count": 0,
        "disqualification_reason": None,
    })
    store.TEACHERS[row["id"]] = row
    return envelope.created(views.dump(row, views.TEACHER))


@bp.get("/epp/cooperating-teachers/<teacher_id>")
@endpoint(TEACHER_READERS)
def read_teacher(teacher_id):
    row = store.get_teacher(teacher_id)
    derive.expire_teacher_training(row)
    derive.derive_teacher_counters(row)
    return envelope.ok(views.dump(row, views.TEACHER))


@bp.get("/epp/cooperating-teachers")
@endpoint(TEACHER_READERS)
def list_teachers():
    page, page_size = shapes.pagination(request.args)
    district_id = request.args.get("district_id") or None
    subject = shapes.query_enum(request.args, "subject_endorsement",
                                shapes.SUBJECTS)
    grade_band = shapes.query_enum(request.args, "grade_band",
                                   shapes.GRADE_BANDS)
    status = shapes.query_enum(request.args, "qualification_status",
                               shapes.QUALIFICATION_STATUSES)
    rows = []
    for row in store.all_of(store.TEACHERS):
        if district_id is not None and row["district_id"] != district_id:
            continue
        if subject is not None and row["subject_endorsement"] != subject:
            continue
        if grade_band is not None and row["grade_band"] != grade_band:
            continue
        if status is not None and row["qualification_status"] != status:
            continue
        rows.append(row)
    sliced, total = shapes.paginate(rows, page, page_size)
    return envelope.listing(views.dump_all(sliced, views.TEACHER),
                            page, page_size, total)


@bp.post("/epp/cooperating-teachers/<teacher_id>/training-completion")
@endpoint(["SupervisionLead"])
def record_training(teacher_id):
    row = store.get_teacher(teacher_id)
    body = shapes.body_of(request)
    completed_on = shapes.req_date(body, "training_completed_on")
    if completed_on > clock.today():
        raise shapes.bad("training_completed_on may not be in the future.")
    if row["qualification_status"] == "DISQUALIFIED":
        raise ApiError("ERR_TEACHER_DISQUALIFIED",
                       "A disqualified teacher cannot be re-qualified.")
    row["training_completed_on"] = completed_on
    row["training_expires_on"] = completed_on + timedelta(
        days=calc.TRAINING_VALID_DAYS)
    row["qualification_status"] = "QUALIFIED"
    store.touch(row)
    derive.expire_teacher_training(row)
    derive.derive_teacher_counters(row)
    return envelope.ok(views.dump(row, views.TEACHER))


@bp.post("/epp/cooperating-teachers/<teacher_id>/disqualify")
@endpoint(["SupervisionLead", "ProgramAdmin"])
def disqualify_teacher(teacher_id):
    row = store.get_teacher(teacher_id)
    body = shapes.body_of(request)
    reason = shapes.req_str(body, "disqualification_reason", 1, None)
    if row["qualification_status"] == "DISQUALIFIED":
        raise ApiError("ERR_TEACHER_DISQUALIFIED",
                       "The teacher is already disqualified.")
    row["qualification_status"] = "DISQUALIFIED"
    row["disqualification_reason"] = reason
    store.touch(row)
    derive.derive_teacher_counters(row)
    return envelope.ok(views.dump(row, views.TEACHER))


# --- university supervisors ------------------------------------------------

@bp.post("/epp/university-supervisors")
@endpoint(["SupervisionLead"])
def create_supervisor():
    body = shapes.body_of(request)
    full_name = shapes.req_str(body, "full_name", 1, 120)
    employment_type = shapes.req_enum(body, "employment_type",
                                      shapes.EMPLOYMENT_TYPES)
    primary_subject = shapes.req_enum(body, "primary_subject", shapes.SUBJECTS)
    covered = shapes.req_enum_list(body, "covered_grade_bands",
                                   shapes.GRADE_BANDS, 1, 4)
    home_x = shapes.req_int(body, "home_grid_x", -500, 500)
    home_y = shapes.req_int(body, "home_grid_y", -500, 500)
    max_travel = shapes.opt_int(body, "max_travel_miles", 1, 400, 60)
    override = shapes.opt_int(body, "max_caseload_points_override", 1, 40, None)
    accepting = shapes.opt_bool(body, "accepting_new_placements", True)

    row = store.new_row({
        "full_name": full_name,
        "employment_type": employment_type,
        "primary_subject": primary_subject,
        "covered_grade_bands": covered,
        "home_grid_x": home_x,
        "home_grid_y": home_y,
        "max_travel_miles": max_travel,
        "max_caseload_points_override": override,
        "max_caseload_points": calc.max_caseload_points(employment_type,
                                                        override),
        "caseload_points": 0,
        "accepting_new_placements": accepting,
    })
    store.SUPERVISORS[row["id"]] = row
    return envelope.created(views.dump(row, views.SUPERVISOR))


@bp.get("/epp/university-supervisors/<supervisor_id>")
@endpoint(SUPERVISOR_READERS)
def read_supervisor(supervisor_id):
    row = store.get_supervisor(supervisor_id)
    derive.derive_supervisor(row)
    return envelope.ok(views.dump(row, views.SUPERVISOR))


@bp.get("/epp/university-supervisors")
@endpoint(["SupervisionLead", "PlacementCoordinator", "ProgramAdmin"])
def list_supervisors():
    page, page_size = shapes.pagination(request.args)
    subject = shapes.query_enum(request.args, "primary_subject",
                                shapes.SUBJECTS)
    employment = shapes.query_enum(request.args, "employment_type",
                                   shapes.EMPLOYMENT_TYPES)
    accepting = shapes.query_bool(request.args, "accepting_new_placements")
    rows = []
    for row in store.all_of(store.SUPERVISORS):
        if subject is not None and row["primary_subject"] != subject:
            continue
        if employment is not None and row["employment_type"] != employment:
            continue
        if (accepting is not None
                and row["accepting_new_placements"] != accepting):
            continue
        rows.append(row)
    sliced, total = shapes.paginate(rows, page, page_size)
    return envelope.listing(views.dump_all(sliced, views.SUPERVISOR),
                            page, page_size, total)


@bp.patch("/epp/university-supervisors/<supervisor_id>")
@endpoint(["SupervisionLead"])
def adjust_supervisor(supervisor_id):
    row = store.get_supervisor(supervisor_id)
    body = shapes.body_of(request)
    if "max_caseload_points_override" in body:
        row["max_caseload_points_override"] = shapes.opt_int(
            body, "max_caseload_points_override", 1, 40, None)
    if shapes.present(body, "max_travel_miles"):
        row["max_travel_miles"] = shapes.req_int(body, "max_travel_miles",
                                                 1, 400)
    accepting = None
    if shapes.present(body, "accepting_new_placements"):
        accepting = shapes.req_bool(body, "accepting_new_placements")

    derive.derive_supervisor(row)
    if accepting is not None:
        row["accepting_new_placements"] = accepting
    store.touch(row)
    return envelope.ok(views.dump(row, views.SUPERVISOR))
