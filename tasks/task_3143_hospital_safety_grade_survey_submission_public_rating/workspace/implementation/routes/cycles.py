"""Release cycle, grade, review and correction routes."""

from flask import Blueprint

from db import store
from middleware import body_json, require_read, authorize
from routes.common import (
    filter_value,
    ok_list,
    ok_object,
)
from services import cycles as cycle_service
from services import scoring as scoring_service

bp = Blueprint("cycles", __name__, url_prefix="/hospital-safety-rating")


# --- Release cycles ---------------------------------------------------------

@bp.post("/release-cycles")
def create_cycle():
    authorize(["RatingAdmin"])
    cycle = cycle_service.create_release_cycle(body_json())
    return ok_object(cycle), 201


@bp.get("/release-cycles")
def list_cycles():
    require_read()
    cycle_service.sweep_cycle_states()
    rows = list(store.release_cycles.values())
    state = filter_value("state")
    version_id = filter_value("methodology_version_id")
    if state is not None:
        rows = [row for row in rows if row.get("state") == state]
    if version_id is not None:
        rows = [row for row in rows if row.get("methodology_version_id") == version_id]
    return ok_list(rows)


@bp.get("/release-cycles/<cycle_id>")
def read_cycle(cycle_id):
    require_read()
    cycle = cycle_service.get_release_cycle(cycle_id)
    cycle_service.derive_cycle_state(cycle)
    return ok_object(cycle)


@bp.post("/release-cycles/<cycle_id>/open-review")
def open_review(cycle_id):
    authorize(["RatingEngine"])
    cycle = cycle_service.get_release_cycle(cycle_id)
    updated = cycle_service.open_review(cycle)
    return ok_object(updated)


@bp.post("/release-cycles/<cycle_id>/publish")
def publish_cycle(cycle_id):
    authorize(["RatingEngine"])
    cycle = cycle_service.get_release_cycle(cycle_id)
    updated = cycle_service.publish_cycle(cycle)
    return ok_object(updated)


@bp.get("/release-cycles/<cycle_id>/grades")
def list_cycle_grades(cycle_id):
    require_read()
    cycle_service.get_release_cycle(cycle_id)
    rows = cycle_service.grades_of_cycle(cycle_id)
    hospital_id = filter_value("hospital_id")
    status = filter_value("status")
    if hospital_id is not None:
        rows = [row for row in rows if row.get("hospital_id") == hospital_id]
    if status is not None:
        rows = [row for row in rows if row.get("status") == status]
    return ok_list(rows)


# --- Grades -----------------------------------------------------------------

@bp.get("/grades")
def list_grades():
    require_read()
    rows = list(store.grades.values())
    for key in ("hospital_id", "release_cycle_id", "score_run_id", "status"):
        value = filter_value(key)
        if value is not None:
            rows = [row for row in rows if row.get(key) == value]
    return ok_list(rows)


@bp.get("/grades/<grade_id>")
def read_grade(grade_id):
    require_read()
    return ok_object(scoring_service.get_grade(grade_id))


@bp.get("/grades/<grade_id>/reviews")
def list_grade_reviews(grade_id):
    require_read()
    scoring_service.get_grade(grade_id)
    rows = cycle_service.reviews_of_grade(grade_id)
    status = filter_value("status")
    if status is not None:
        rows = [row for row in rows if row.get("status") == status]
    return ok_list(rows)


# --- Measure sets and score runs --------------------------------------------

@bp.get("/hospital-measure-sets")
def list_measure_sets():
    require_read()
    rows = list(store.hospital_measure_sets.values())
    for key in ("hospital_id", "methodology_version_id", "readiness_state"):
        value = filter_value(key)
        if value is not None:
            rows = [row for row in rows if row.get(key) == value]
    return ok_list(rows)


@bp.get("/hospital-measure-sets/<measure_set_id>")
def read_measure_set(measure_set_id):
    require_read()
    return ok_object(scoring_service.get_measure_set(measure_set_id))


@bp.get("/hospital-measure-sets/<measure_set_id>/score-runs")
def list_measure_set_runs(measure_set_id):
    require_read()
    scoring_service.get_measure_set(measure_set_id)
    rows = [row for row in store.score_runs.values() if row.get("measure_set_id") == measure_set_id]
    score_state = filter_value("score_state")
    if score_state is not None:
        rows = [row for row in rows if row.get("score_state") == score_state]
    return ok_list(rows)


@bp.get("/score-runs")
def list_score_runs():
    require_read()
    rows = list(store.score_runs.values())
    for key in ("hospital_id", "methodology_version_id", "measure_set_id", "score_state"):
        value = filter_value(key)
        if value is not None:
            rows = [row for row in rows if row.get(key) == value]
    return ok_list(rows)


@bp.get("/score-runs/<run_id>")
def read_score_run(run_id):
    require_read()
    return ok_object(scoring_service.get_score_run(run_id))


@bp.get("/score-runs/<run_id>/grades")
def list_run_grades(run_id):
    require_read()
    scoring_service.get_score_run(run_id)
    rows = [row for row in store.grades.values() if row.get("score_run_id") == run_id]
    status = filter_value("status")
    if status is not None:
        rows = [row for row in rows if row.get("status") == status]
    return ok_list(rows)


# --- Hospital reviews and corrections ---------------------------------------

@bp.get("/hospital-reviews")
def list_reviews():
    require_read()
    rows = list(store.hospital_reviews.values())
    for key in ("hospital_id", "grade_id", "release_cycle_id", "status"):
        value = filter_value(key)
        if value is not None:
            rows = [row for row in rows if row.get(key) == value]
    return ok_list(rows)


@bp.get("/hospital-reviews/<review_id>")
def read_review(review_id):
    require_read()
    return ok_object(cycle_service.get_review(review_id))


@bp.get("/hospital-reviews/<review_id>/corrections")
def list_corrections(review_id):
    require_read()
    cycle_service.get_review(review_id)
    rows = cycle_service.corrections_of_review(review_id)
    status = filter_value("status")
    if status is not None:
        rows = [row for row in rows if row.get("status") == status]
    return ok_list(rows)


@bp.get("/correction-requests")
def list_correction_requests():
    require_read()
    rows = list(store.correction_requests.values())
    for key in ("hospital_id", "hospital_review_id", "status"):
        value = filter_value(key)
        if value is not None:
            rows = [row for row in rows if row.get(key) == value]
    return ok_list(rows)


@bp.get("/correction-requests/<correction_id>")
def read_correction_request(correction_id):
    require_read()
    from errors import ERR_CORRECTION_NOT_FOUND, ApiError
    correction = store.correction_requests.get(correction_id)
    if correction is None:
        raise ApiError(ERR_CORRECTION_NOT_FOUND)
    return ok_object(correction)


# --- Reanalysis top-level reads ---------------------------------------------

@bp.get("/reanalysis-requests")
def list_reanalysis_requests():
    require_read()
    rows = list(store.reanalysis_requests.values())
    for key in ("hospital_id", "survey_id", "status"):
        value = filter_value(key)
        if value is not None:
            rows = [row for row in rows if row.get(key) == value]
    return ok_list(rows)


@bp.get("/reanalysis-requests/<request_id>")
def read_reanalysis_request(request_id):
    require_read()
    from services.reanalysis import get_reanalysis_request
    return ok_object(get_reanalysis_request(request_id))