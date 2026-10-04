"""Hospital routes."""

from flask import Blueprint

from db import store
from middleware import RATING_ADMIN, body_json, require_read, authorize
from routes.common import filter_value, ok_list, ok_object
from services import employers as employer_service
from services import methodology as methodology_service
from services import scoring as scoring_service
from services import surveys as survey_service
from services.hospitals import (
    create_hospital,
    get_hospital,
    update_hospital,
)

bp = Blueprint("hospitals", __name__, url_prefix="/hospital-safety-rating")


def _hospital_scope(hospital_id):
    """Every child collection checks the hospital first, left to right."""
    return get_hospital(hospital_id)


@bp.post("/hospitals")
def register_hospital():
    authorize([RATING_ADMIN])
    hospital = create_hospital(body_json())
    return ok_object(hospital), 201


@bp.get("/hospitals")
def list_hospitals():
    require_read()
    state_code = filter_value("state_code")
    teaching_status = filter_value("teaching_status")
    status = filter_value("status")
    rows = list(store.hospitals.values())
    if state_code is not None:
        rows = [row for row in rows if row.get("state_code") == state_code]
    if teaching_status is not None:
        rows = [row for row in rows if row.get("teaching_status") == teaching_status]
    if status is not None:
        rows = [row for row in rows if row.get("status") == status]
    return ok_list(rows)


@bp.get("/hospitals/<hospital_id>")
def read_hospital(hospital_id):
    require_read()
    hospital = _hospital_scope(hospital_id)
    # PRD §2.8: `disclosure_status` "is recomputed rather than set by clients",
    # and `submitted_source_document_count` accumulates over the hospital's
    # measures and adopted documents. Both are derived on the read surface so a
    # raw measure write is reflected without a second mutating call.
    from services.hospitals import recompute_source_document_count
    recompute_source_document_count(hospital)
    return ok_object(hospital)


@bp.put("/hospitals/<hospital_id>")
def modify_hospital(hospital_id):
    authorize([RATING_ADMIN])
    hospital = _hospital_scope(hospital_id)
    return ok_object(update_hospital(hospital, body_json()))


# --- Child collections ------------------------------------------------------

@bp.get("/hospitals/<hospital_id>/surveys")
def list_hospital_surveys(hospital_id):
    require_read()
    _hospital_scope(hospital_id)
    af_status = filter_value("af_status")
    version_id = filter_value("methodology_version_id")
    rows = [row for row in store.surveys.values() if row["hospital_id"] == hospital_id]
    if af_status is not None:
        rows = [row for row in rows if row.get("af_status") == af_status]
    if version_id is not None:
        rows = [row for row in rows if row.get("methodology_version_id") == version_id]
    return ok_list(rows)


@bp.get("/hospitals/<hospital_id>/grades")
def list_hospital_grades(hospital_id):
    require_read()
    _hospital_scope(hospital_id)
    status = filter_value("status")
    cycle_id = filter_value("release_cycle_id")
    rows = [row for row in store.grades.values() if row["hospital_id"] == hospital_id]
    if status is not None:
        rows = [row for row in rows if row.get("status") == status]
    if cycle_id is not None:
        rows = [row for row in rows if row.get("release_cycle_id") == cycle_id]
    return ok_list(rows, newest_first=True)


@bp.get("/hospitals/<hospital_id>/reviews")
def list_hospital_reviews(hospital_id):
    require_read()
    _hospital_scope(hospital_id)
    status = filter_value("status")
    cycle_id = filter_value("release_cycle_id")
    rows = [row for row in store.hospital_reviews.values() if row["hospital_id"] == hospital_id]
    if status is not None:
        rows = [row for row in rows if row.get("status") == status]
    if cycle_id is not None:
        rows = [row for row in rows if row.get("release_cycle_id") == cycle_id]
    return ok_list(rows)


@bp.get("/hospitals/<hospital_id>/reanalysis-requests")
def list_hospital_reanalysis(hospital_id):
    require_read()
    _hospital_scope(hospital_id)
    status = filter_value("status")
    survey_id = filter_value("survey_id")
    rows = [row for row in store.reanalysis_requests.values() if row["hospital_id"] == hospital_id]
    if status is not None:
        rows = [row for row in rows if row.get("status") == status]
    if survey_id is not None:
        rows = [row for row in rows if row.get("survey_id") == survey_id]
    return ok_list(rows)


# --- Methodology pinning ----------------------------------------------------

@bp.post("/hospitals/<hospital_id>/methodology-versions")
def pin_methodology(hospital_id):
    authorize([RATING_ADMIN])
    hospital = _hospital_scope(hospital_id)
    payload = body_json()
    version_id = payload.get("methodology_version_id")
    from errors import ERR_INVALID_REQUEST
    if not isinstance(version_id, str) or version_id.strip() == "":
        from errors import ApiError
        raise ApiError(ERR_INVALID_REQUEST)
    row = methodology_service.pin_version(hospital, version_id)
    return ok_object(row), 201


@bp.post("/hospitals/<hospital_id>/pending-methodology-changes")
def raise_pending_change(hospital_id):
    authorize([RATING_ADMIN, "HospitalRespondent"])
    hospital = _hospital_scope(hospital_id)
    change = methodology_service.create_pending_change(hospital, body_json())
    return ok_object(change), 201


# --- Survey track -----------------------------------------------------------

@bp.post("/hospitals/<hospital_id>/surveys")
def open_survey(hospital_id):
    user_id, _role = authorize(["HospitalRespondent"])
    hospital = _hospital_scope(hospital_id)
    survey = survey_service.create_survey(hospital, body_json(), user_id)
    return ok_object(survey), 201


@bp.post("/hospitals/<hospital_id>/survey-measures")
def record_measure(hospital_id):
    authorize(["HospitalRespondent"])
    hospital = _hospital_scope(hospital_id)
    row = survey_service.record_measure(hospital, body_json())
    return ok_object(row), 201


@bp.post("/hospitals/<hospital_id>/public-source-measures")
def record_public_source(hospital_id):
    authorize([RATING_ADMIN])
    hospital = _hospital_scope(hospital_id)
    row = survey_service.record_public_source_measure(hospital, body_json())
    return ok_object(row), 201


# --- Measure set and scoring ------------------------------------------------

@bp.post("/hospitals/<hospital_id>/refresh-measures")
def refresh_measures(hospital_id):
    authorize(["RatingEngine"])
    hospital = _hospital_scope(hospital_id)
    from errors import ERR_HOSPITAL_NOT_ACTIVE, ERR_INVALID_REQUEST, ApiError
    if hospital.get("status") != "ACTIVE":
        raise ApiError(ERR_HOSPITAL_NOT_ACTIVE)
    payload = body_json()
    expected = payload.get("expected_hospital_version")
    if expected is None:
        raise ApiError(ERR_INVALID_REQUEST)
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST)
    measure_set = scoring_service.refresh_hospital_measures(hospital, expected)
    return ok_object(measure_set)


@bp.post("/hospitals/<hospital_id>/score-runs")
def create_score_run(hospital_id):
    authorize(["RatingEngine"])
    hospital = _hospital_scope(hospital_id)
    run = scoring_service.create_score_run(hospital, body_json())
    return ok_object(run), 201


@bp.get("/hospitals/<hospital_id>/score-runs")
def list_hospital_score_runs(hospital_id):
    """PRD §3.8: a score run "can also be listed by the `measure_set_id` it was
    cut from and by its own `hospital_id`, `methodology_version_id` and
    `score_state`". PRD §2.5 lists score runs among the hospital-child
    collections whose path identifiers resolve left to right."""
    require_read()
    _hospital_scope(hospital_id)
    rows = [row for row in store.score_runs.values() if row.get("hospital_id") == hospital_id]
    for key in ("methodology_version_id", "measure_set_id", "score_state"):
        value = filter_value(key)
        if value is not None:
            rows = [row for row in rows if row.get(key) == value]
    return ok_list(rows)


@bp.get("/hospitals/<hospital_id>/composite-preview")
def composite_preview(hospital_id):
    require_read()
    hospital = _hospital_scope(hospital_id)
    payload = scoring_service.composite_preview(hospital, filter_value("methodology_version_id"))
    return ok_list_preview(payload)


def ok_list_preview(payload):
    from routes.common import ok_payload
    return ok_payload(payload)


@bp.get("/hospitals/<hospital_id>/scorecard")
def scorecard(hospital_id):
    require_read()
    hospital = _hospital_scope(hospital_id)
    payload = scoring_service.scorecard(hospital, filter_value("release_cycle_id"))
    from routes.common import ok_payload
    return ok_payload(payload)


# --- Preliminary results ----------------------------------------------------

@bp.post("/hospitals/<hospital_id>/preliminary-results")
def open_preliminary_result(hospital_id):
    authorize(["VerificationAnalyst"])
    hospital = _hospital_scope(hospital_id)
    from services.cycles import create_preliminary_result
    review = create_preliminary_result(hospital, body_json())
    return ok_object(review), 201


@bp.post("/hospitals/<hospital_id>/preliminary-results/<review_id>/accept")
def accept_preliminary_result(hospital_id, review_id):
    authorize(["HospitalRespondent"])
    hospital = _hospital_scope(hospital_id)
    from services.cycles import accept_review, get_hospital_review
    review = get_hospital_review(hospital_id, review_id)
    payload = body_json()
    updated = accept_review(hospital, review, payload.get("expected_hospital_version"))
    return ok_object(updated)


@bp.post("/hospitals/<hospital_id>/preliminary-results/<review_id>/corrections")
def file_correction(hospital_id, review_id):
    authorize(["HospitalRespondent"])
    hospital = _hospital_scope(hospital_id)
    from services.cycles import file_correction as file_correction_service, get_hospital_review
    review = get_hospital_review(hospital_id, review_id)
    correction = file_correction_service(hospital, review, body_json())
    return ok_object(correction), 201


@bp.post("/hospitals/<hospital_id>/preliminary-results/<review_id>/corrections/<correction_id>/decide")
def decide_correction(hospital_id, review_id, correction_id):
    authorize(["RatingEngine"])
    hospital = _hospital_scope(hospital_id)
    from services.cycles import decide_correction as decide_service, get_correction, get_hospital_review
    review = get_hospital_review(hospital_id, review_id)
    correction = get_correction(hospital_id, review_id, correction_id)
    payload = body_json()
    updated = decide_service(hospital, review, correction, payload.get("decision"))
    return ok_object(updated)


@bp.get("/hospitals/<hospital_id>/review-summary")
def review_summary(hospital_id):
    require_read()
    hospital = _hospital_scope(hospital_id)
    from services.cycles import review_summary as summary_service
    from routes.common import ok_payload
    return ok_payload(summary_service(hospital, filter_value("release_cycle_id")))


# --- Reanalysis -------------------------------------------------------------

@bp.post("/hospitals/<hospital_id>/reanalysis-requests")
def raise_reanalysis(hospital_id):
    authorize(["HospitalRespondent"])
    hospital = _hospital_scope(hospital_id)
    from services.reanalysis import create_reanalysis_request
    request = create_reanalysis_request(hospital, body_json())
    return ok_object(request), 201


@bp.post("/hospitals/<hospital_id>/reanalysis-requests/<request_id>/decide")
def decide_reanalysis(hospital_id, request_id):
    user_id, _role = authorize(["VerificationAnalyst", "HospitalRespondent"])
    hospital = _hospital_scope(hospital_id)
    from services.reanalysis import decide_reanalysis_request, get_hospital_request
    request = get_hospital_request(hospital_id, request_id)
    payload = body_json()
    updated = decide_reanalysis_request(hospital, request, payload.get("decision"), user_id)
    return ok_object(updated)


# --- Employer surface -------------------------------------------------------

@bp.get("/hospitals/<hospital_id>/employers")
def list_hospital_employers(hospital_id):
    require_read()
    _hospital_scope(hospital_id)
    minimum_letter = filter_value("minimum_acceptable_letter")
    rows = employer_service.employers_listing_hospital(hospital_id, minimum_letter)
    return ok_list(rows)