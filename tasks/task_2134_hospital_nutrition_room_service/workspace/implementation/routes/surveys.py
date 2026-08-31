"""Bedside satisfaction surveys: immutable append-only events (PRD section 3.9)."""

from flask import Blueprint

import api
import calcs
import domain
import serialize
import store
from errors import ApiError

bp = Blueprint("surveys", __name__, url_prefix="/nutrition/satisfaction-surveys")


@bp.post("")
@api.require("TrayAide", "DietClerk")
def record_survey():
    body = api.body()
    meal_order_id = api.req_id(body, "meal_order_id")
    taste = api.req_int(body, "taste_score", lo=1, hi=5)
    temperature = api.req_int(body, "temperature_score", lo=1, hi=5)
    accuracy = api.req_int(body, "accuracy_score", lo=1, hi=5)
    comment = api.opt_str(body, "comment")

    tray = store.get_meal_order(meal_order_id)

    if tray["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_MEAL_ORDER_NOT_DELIVERED",
                       "Only a DELIVERED tray may be rated.")
    if any(s["meal_order_id"] == meal_order_id for s in store.surveys.values()):
        raise ApiError("ERR_DUPLICATE_SURVEY",
                       "This tray already carries a satisfaction survey.")

    survey = {
        "meal_order_id": meal_order_id,
        "patient_id": tray["patient_id"],
        "taste_score": taste,
        "temperature_score": temperature,
        "accuracy_score": accuracy,
        "comment": comment,
        "composite_score": calcs.satisfaction_composite(taste, temperature, accuracy),
    }
    store.stamp_new(survey, versioned=False)
    store.surveys[survey["id"]] = survey

    patient = store.patients[tray["patient_id"]]
    domain.refresh_patient_satisfaction(patient)
    store.touch(patient)
    return api.created(serialize.survey(survey))


@bp.get("")
@api.require(*api.ALL_ROLES)
def list_surveys():
    meal_order_id = api.q_str("meal_order_id")
    patient_id = api.q_str("patient_id")
    rows = api.filtered(list(store.surveys.values()),
                        [(meal_order_id, "meal_order_id"), (patient_id, "patient_id")])
    return api.paged(rows, serialize.survey)


@bp.get("/<survey_id>")
@api.require(*api.ALL_ROLES)
def read_survey(survey_id):
    return api.ok(serialize.survey(store.get_survey(survey_id)))
