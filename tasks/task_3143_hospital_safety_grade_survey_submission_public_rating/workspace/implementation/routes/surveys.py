"""Stand-alone survey and survey-measure routes."""

from flask import Blueprint

from db import store
from errors import ERR_INVALID_REQUEST, ApiError
from middleware import VERIFICATION_ANALYST, body_json, require_read, authorize
from routes.common import filter_value, ok_list, ok_object
from services import surveys as survey_service

bp = Blueprint("surveys", __name__, url_prefix="/hospital-safety-rating")


def _matching(rows, filters):
    for key, value in filters.items():
        if value is None:
            continue
        rows = [row for row in rows if row.get(key) == value]
    return rows


@bp.get("/surveys")
def list_surveys():
    require_read()
    rows = list(store.surveys.values())
    rows = _matching(rows, {
        "hospital_id": filter_value("hospital_id"),
        "methodology_version_id": filter_value("methodology_version_id"),
        "af_status": filter_value("af_status"),
    })
    return ok_list(rows)


@bp.get("/surveys/<survey_id>")
def read_survey(survey_id):
    require_read()
    return ok_object(survey_service.get_survey(survey_id))


@bp.put("/surveys/<survey_id>")
def modify_survey(survey_id):
    authorize(["HospitalRespondent"])
    survey = survey_service.get_survey(survey_id)
    return ok_object(survey_service.update_survey(survey, body_json()))


@bp.post("/surveys/<survey_id>/submit")
def submit_survey(survey_id):
    authorize(["HospitalRespondent"])
    survey = survey_service.get_survey(survey_id)
    return ok_object(survey_service.submit_survey(survey))


@bp.post("/surveys/<survey_id>/verify")
def verify_survey(survey_id):
    user_id, _role = authorize([VERIFICATION_ANALYST])
    survey = survey_service.get_survey(survey_id)
    payload = body_json()
    response = payload.get("verification_response")
    if not isinstance(response, str) or response.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    updated = survey_service.verify_survey(survey, response.strip().upper(), user_id)
    return ok_object(updated)


@bp.post("/surveys/<survey_id>/resolve")
def resolve_survey(survey_id):
    user_id, _role = authorize(["HospitalRespondent"])
    survey = survey_service.get_survey(survey_id)
    updated = survey_service.resolve_survey(survey, user_id)
    return ok_object(updated)


@bp.get("/survey-measures")
def list_measures():
    require_read()
    rows = list(store.survey_measures.values())
    rows = _matching(rows, {
        "hospital_id": filter_value("hospital_id"),
        "survey_id": filter_value("survey_id"),
        "measure_code": filter_value("measure_code"),
        "measure_status": filter_value("measure_status"),
    })
    return ok_list(rows)


@bp.get("/survey-measures/<row_id>")
def read_measure(row_id):
    require_read()
    return ok_object(survey_service.get_survey_measure(row_id))