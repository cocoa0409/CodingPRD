"""Observation orders, reassessments and the discontinuation review (PRD 3.2,
3.3 and 3.9)."""
from datetime import timedelta

from flask import Blueprint

import calc
import db as D
import serializers as S
import services as SVC
from db import (
    ATTEMPT_WINDOW_HOURS,
    DECISIONS,
    MODALITIES,
    RECOMMENDATIONS,
    RISK_CATEGORIES,
    base_entity,
    db,
    touch,
)
from errors import fail
from response import object_response
from validation import (
    authenticate,
    body_json,
    raw_opt_str,
    req_enum,
    req_enum_array,
    req_str,
)

bp = Blueprint("orders", __name__)

ORDER_WRITERS = ("AttendingProvider", "SystemAdmin")


# ---------------------------------------------------------------------------
# POST /observation/orders
# ---------------------------------------------------------------------------
@bp.post("/observation/orders")
def create_order():
    caller = authenticate(ORDER_WRITERS)
    body = body_json()
    patient_id = req_str(body, "patient_id")
    ordering_provider_user_id = req_str(body, "ordering_provider_user_id")
    risk_categories = req_enum_array(body, "risk_categories", RISK_CATEGORIES)
    required_modality = req_enum(body, "required_modality", MODALITIES)
    clinical_rationale = req_str(body, "clinical_rationale", 1, 500)
    patient = db.patients.get(patient_id)
    if patient is None:
        fail("ERR_PATIENT_NOT_FOUND")
    if patient["status"] != "ADMITTED":
        fail("ERR_PATIENT_DISCHARGED", "The patient has been discharged.")
    unit = calc.unit_of_patient(patient)
    # The admission-baseline variant consults no safety-event row at all.
    score = calc.risk_score(risk_categories, patient["age_years"], "ADMISSION_BASELINE")
    interval = calc.interval_hours_for_score(score)
    if required_modality == "VIDEO_MONITORING":
        if not calc.video_permitted(unit, risk_categories, score):
            fail("ERR_VIDEO_MODALITY_NOT_PERMITTED",
                 "Video monitoring is not permitted for this order.")
    order = base_entity()
    order.update({
        "patient_id": patient["id"],
        "ordering_provider_user_id": ordering_provider_user_id,
        "risk_categories": risk_categories,
        "required_modality": required_modality,
        "clinical_rationale": clinical_rationale,
        "status": "ACTIVE",
        "elopement_risk_score": score,
        "risk_score_variant": "ADMISSION_BASELINE",
        "reassessment_interval_hours": interval,
        "last_reassessed_at": db.clock,
        "next_reassessment_due_at": db.clock + timedelta(hours=interval),
        "coverage_gap_flag": False,
        "discontinuation_recommendation": None,
        "discontinuation_review_opened_by_user_id": None,
        "discontinued_at": None,
        "lapsed_at": None,
    })
    db.orders[order["id"]] = order
    # open_order_count is a derived figure on the unit, and recomputing it is
    # itself a mutation of the unit (PRD 3.1).
    touch(unit)
    return object_response(S.order_json(order), 201)


# ---------------------------------------------------------------------------
# POST /observation/orders/{id}/reassessments
# ---------------------------------------------------------------------------
@bp.post("/observation/orders/<order_id>/reassessments")
def create_reassessment(order_id):
    caller = authenticate(ORDER_WRITERS)
    body = body_json()
    categories_after = req_enum_array(body, "risk_categories_after", RISK_CATEGORIES)
    order = db.orders.get(order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND")
    if order["status"] not in ("ACTIVE", "REASSESSMENT_DUE"):
        fail("ERR_INVALID_ORDER_STATE",
             "A reassessment is only accepted from ACTIVE or REASSESSMENT_DUE.")
    patient = db.patients.get(order["patient_id"])
    if patient is None or patient["status"] != "ADMITTED":
        fail("ERR_PATIENT_DISCHARGED", "The patient has been discharged.")
    score_before = order["elopement_risk_score"]
    order["risk_categories"] = categories_after
    score_after, interval = SVC.recompute_score_and_interval(
        order, "ROLLING_EVENT_WEIGHTED", rebase_last_reassessed=True
    )
    order["status"] = "ACTIVE"
    row = base_entity(versioned=False)
    row.update({
        "order_id": order["id"],
        "performed_by_user_id": caller.user_id,
        "risk_categories_after": list(categories_after),
        "score_before": score_before,
        "score_after": score_after,
        "interval_hours_after": interval,
        "reassessed_at": db.clock,
    })
    db.reassessments[row["id"]] = row
    touch(order)
    return object_response(S.reassessment_json(row), 201)


# ---------------------------------------------------------------------------
# POST /observation/orders/{id}/discontinuation-review
# ---------------------------------------------------------------------------
@bp.post("/observation/orders/<order_id>/discontinuation-review")
def open_discontinuation_review(order_id):
    caller = authenticate(ORDER_WRITERS)
    body = body_json()
    recommendation = req_enum(body, "recommendation", RECOMMENDATIONS)
    order = db.orders.get(order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND")
    if order["status"] != "ACTIVE":
        fail("ERR_INVALID_ORDER_STATE",
             "A discontinuation review is only opened from ACTIVE.")
    if calc.reassessment_count(order) < 1:
        fail("ERR_REASSESSMENT_REQUIRED_BEFORE_REVIEW",
             "The order has never been reassessed.")
    order["status"] = "DISCONTINUATION_REVIEW"
    order["discontinuation_recommendation"] = recommendation
    order["discontinuation_review_opened_by_user_id"] = caller.user_id
    touch(order)
    return object_response(S.order_json(order))


# ---------------------------------------------------------------------------
# POST /observation/orders/{id}/discontinuation-decision
# ---------------------------------------------------------------------------
@bp.post("/observation/orders/<order_id>/discontinuation-decision")
def decide_discontinuation(order_id):
    caller = authenticate(ORDER_WRITERS)
    body = body_json()
    decision = req_enum(body, "decision", DECISIONS)
    raw_opt_str(body, "rationale")
    order = db.orders.get(order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND")
    if order["status"] != "DISCONTINUATION_REVIEW":
        fail("ERR_INVALID_ORDER_STATE",
             "A decision is only rendered from DISCONTINUATION_REVIEW.")
    # PRD 2.6 ranks the trailing-24h window at rung 15 and segregation of duties
    # at rung 16, so the window is evaluated first on the APPROVE branch.
    if decision == "APPROVE":
        window_start = db.clock - timedelta(hours=ATTEMPT_WINDOW_HOURS)
        for event in calc.events_of_order(order["id"]):
            if event["occurred_at"] >= window_start:
                fail("ERR_RECENT_SAFETY_EVENT_BLOCKS_DISCONTINUATION",
                     "A safety event occurred within the trailing 24 hours.")
    if caller.user_id == order["ordering_provider_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The ordering provider may not decide the discontinuation.")
    if decision == "APPROVE":
        SVC.discontinue_order(order)
    else:
        order["status"] = "ACTIVE"
        order["discontinuation_recommendation"] = None
        order["discontinuation_review_opened_by_user_id"] = None
        SVC.recompute_interval_only(order, rebase_last_reassessed=True)
        touch(order)
    return object_response(S.order_json(order))
