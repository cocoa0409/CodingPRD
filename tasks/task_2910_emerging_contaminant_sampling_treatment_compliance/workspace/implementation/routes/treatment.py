"""Treatment evaluations, pilot skids and residuals manifests
(PRD sections 3.7 and 3.8).
"""

from decimal import Decimal

from flask import Blueprint

import constants as C
import db
from db import store, touch, now
from errors import ApiError, invalid
from middleware import authenticate
from numeric import cents, q2
from response import created_response, object_response
from routes.common import (
    apply_boolean_filters,
    apply_scalar_filters,
    detail,
    filter_fk,
    page,
    pagination,
    resolve,
)
from services import treatment
from shape import Body

bp = Blueprint("treatment", __name__)

ZERO2 = Decimal("0.00")


# ------------------------------------------------------- treatment evaluations
@bp.route("/treatment-evaluations", methods=["POST"])
def create_evaluation():
    authenticate(("TreatmentEngineer",))
    body = Body(["entry_point_id", "residuals_budget_cents"])
    entry_point_id = body.string("entry_point_id")
    budget = body.integer(
        "residuals_budget_cents",
        required=False,
        default=C.DEFAULT_RESIDUALS_BUDGET_CENTS,
        minimum=0,
    )
    resolve("entry_points", entry_point_id)
    row = db.insert(
        "evaluations",
        {
            "entry_point_id": entry_point_id,
            "residuals_budget_cents": budget,
            "residuals_spent_cents": 0,
            "mandated": False,
            "status": "SCREENING",
            "selected_technology": None,
            "decision_note": None,
        },
    )
    return created_response(db.public(row))


@bp.route("/treatment-evaluations", methods=["GET"])
def list_evaluations():
    authenticate(C.ANY_ROLE)
    limit, offset = pagination()
    rows = db.sorted_rows("evaluations")
    rows = filter_fk(rows, "entry_point_id", "entry_points")
    rows = apply_scalar_filters(rows, ["status"])
    rows = apply_boolean_filters(rows, ["mandated"])
    return page(rows, limit, offset)


@bp.route("/treatment-evaluations/<row_id>", methods=["GET"])
def get_evaluation(row_id):
    authenticate(C.ANY_ROLE)
    return detail("evaluations", row_id)


@bp.route("/treatment-evaluations/<row_id>/decision", methods=["POST"])
def decide_evaluation(row_id):
    authenticate(("TreatmentEngineer",))
    evaluation = resolve("evaluations", row_id)
    body = Body(["action", "decision_note"])
    action = body.enum("action", ("SELECT", "ABANDON"))
    decision_note = body.string("decision_note", required=False, default=None)
    if action == "ABANDON" and (decision_note is None or decision_note.strip() == ""):
        raise invalid("decision_note is required when abandoning an evaluation")

    if evaluation["status"] != "PILOTING":
        raise ApiError("ERR_EVALUATION_STATE_INVALID")

    completed = [
        pilot
        for pilot in treatment.pilots_for(evaluation["id"])
        if pilot["status"] == "COMPLETED"
    ]
    if len(completed) < C.MIN_COMPLETED_PILOTS:
        raise ApiError("ERR_INSUFFICIENT_PILOT_EVIDENCE")

    entry_point = store.entry_points.get(evaluation["entry_point_id"])

    if action == "ABANDON":
        evaluation["status"] = "REJECTED_ALL"
        evaluation["decision_note"] = decision_note
        touch(evaluation)
        if entry_point is not None:
            entry_point["treatment_status"] = "NONE"
            touch(entry_point)
        return object_response(db.public(evaluation))

    winner = treatment.select_winner(evaluation["id"])
    if winner is None:
        raise ApiError("ERR_NO_QUALIFYING_TECHNOLOGY")

    winner["selected"] = True
    touch(winner)
    evaluation["status"] = "SELECTED"
    evaluation["selected_technology"] = winner["technology"]
    evaluation["decision_note"] = decision_note
    touch(evaluation)
    if entry_point is not None:
        treatment.create_capital_project(evaluation, entry_point, winner)
    return object_response(db.public(evaluation))


# ----------------------------------------------------------------- pilot tests
@bp.route("/pilot-tests", methods=["POST"])
def create_pilot():
    authenticate(("TreatmentEngineer",))
    body = Body(
        [
            "treatment_evaluation_id",
            "technology",
            "window_start_at",
            "window_end_at",
            "ebct_min",
            "lifecycle_cost_cents",
            "capital_cost_estimate_cents",
            "annual_om_estimate_cents",
            "residuals_burden_score",
            "footprint_score",
            "om_complexity_score",
        ]
    )
    evaluation_id = body.string("treatment_evaluation_id")
    technology = body.enum("technology", C.TECHNOLOGIES)
    window_start = body.instant("window_start_at")
    window_end = body.instant("window_end_at")
    ebct = body.decimal("ebct_min", exclusive_minimum=0)
    lifecycle_cost = body.integer("lifecycle_cost_cents", minimum=0)
    capital_estimate = body.integer("capital_cost_estimate_cents", minimum=0)
    om_estimate = body.integer("annual_om_estimate_cents", minimum=0)
    residuals_burden = body.decimal("residuals_burden_score", minimum=0, maximum=100)
    footprint = body.decimal("footprint_score", minimum=0, maximum=100)
    om_complexity = body.decimal("om_complexity_score", minimum=0, maximum=100)
    if window_end <= window_start:
        raise invalid("window_end_at must be strictly after window_start_at")

    evaluation = resolve("evaluations", evaluation_id)
    if evaluation["status"] not in ("SCREENING", "PILOTING"):
        raise ApiError("ERR_EVALUATION_STATE_INVALID")

    entry_point = store.entry_points.get(evaluation["entry_point_id"])
    if entry_point is not None:
        if treatment.conflicting_pilot(entry_point["id"], window_start, window_end) is not None:
            raise ApiError("ERR_PILOT_WINDOW_CONFLICT")

    row = db.insert(
        "pilots",
        {
            "treatment_evaluation_id": evaluation_id,
            "technology": technology,
            "window_start_at": window_start,
            "window_end_at": window_end,
            "ebct_min": ebct,
            "lifecycle_cost_cents": lifecycle_cost,
            "capital_cost_estimate_cents": capital_estimate,
            "annual_om_estimate_cents": om_estimate,
            "residuals_burden_score": residuals_burden,
            "footprint_score": footprint,
            "om_complexity_score": om_complexity,
            "influent_ng_per_l": None,
            "effluent_ng_per_l": None,
            "bed_volumes_treated": None,
            "spent_media_kg": None,
            "unmanifested_media_kg": ZERO2,
            "removal_pct": None,
            "lifecycle_cost_score": None,
            "technology_score": None,
            "selected": False,
            "status": "PLANNED",
        },
    )

    if evaluation["status"] == "SCREENING":
        evaluation["status"] = "PILOTING"
        touch(evaluation)
        if entry_point is not None:
            entry_point["treatment_status"] = "PILOT"
            touch(entry_point)
    return created_response(db.public(row))


@bp.route("/pilot-tests", methods=["GET"])
def list_pilots():
    authenticate(C.ANY_ROLE)
    limit, offset = pagination()
    rows = db.sorted_rows("pilots")
    rows = filter_fk(rows, "treatment_evaluation_id", "evaluations")
    rows = apply_scalar_filters(rows, ["technology", "status"])
    rows = apply_boolean_filters(rows, ["selected"])
    return page(rows, limit, offset)


@bp.route("/pilot-tests/<row_id>", methods=["GET"])
def get_pilot(row_id):
    authenticate(C.ANY_ROLE)
    return detail("pilots", row_id)


@bp.route("/pilot-tests/<row_id>/start", methods=["POST"])
def start_pilot(row_id):
    authenticate(("TreatmentEngineer",))
    pilot = resolve("pilots", row_id)
    Body([])
    if pilot["status"] != "PLANNED":
        raise ApiError("ERR_PILOT_STATE_INVALID")
    if now() < pilot["window_start_at"]:
        raise ApiError("ERR_PILOT_WINDOW_NOT_STARTED")
    pilot["status"] = "RUNNING"
    touch(pilot)
    return object_response(db.public(pilot))


@bp.route("/pilot-tests/<row_id>/complete", methods=["POST"])
def complete_pilot(row_id):
    authenticate(("TreatmentEngineer",))
    pilot = resolve("pilots", row_id)
    body = Body(
        ["influent_ng_per_l", "effluent_ng_per_l", "bed_volumes_treated", "spent_media_kg"]
    )
    influent = body.decimal("influent_ng_per_l", minimum=0)
    effluent = body.decimal("effluent_ng_per_l", minimum=0)
    bed_volumes = body.integer("bed_volumes_treated", minimum=0)
    spent_media = body.decimal("spent_media_kg", exclusive_minimum=0)

    if pilot["status"] != "RUNNING":
        raise ApiError("ERR_PILOT_STATE_INVALID")
    if effluent > influent:
        raise ApiError("ERR_EFFLUENT_EXCEEDS_INFLUENT")

    pilot["influent_ng_per_l"] = influent
    pilot["effluent_ng_per_l"] = effluent
    pilot["bed_volumes_treated"] = bed_volumes
    pilot["spent_media_kg"] = spent_media
    pilot["unmanifested_media_kg"] = spent_media
    pilot["status"] = "COMPLETED"

    removal = treatment.removal_pct(influent, effluent)
    cost_score = treatment.lifecycle_cost_score(pilot["lifecycle_cost_cents"])
    pilot["removal_pct"] = removal
    pilot["lifecycle_cost_score"] = cost_score
    pilot["technology_score"] = treatment.technology_score(
        removal,
        cost_score,
        pilot["residuals_burden_score"],
        pilot["footprint_score"],
        pilot["om_complexity_score"],
    )
    touch(pilot)
    return object_response(db.public(pilot))


# ---------------------------------------------------------- residuals manifests
@bp.route("/residuals-manifests", methods=["POST"])
def create_manifest():
    authenticate(("TreatmentEngineer",))
    body = Body(["pilot_test_id", "media_type", "mass_kg"])
    pilot_id = body.string("pilot_test_id")
    media_type = body.enum("media_type", C.MEDIA_TYPES)
    mass = body.decimal("mass_kg", exclusive_minimum=0)

    pilot = resolve("pilots", pilot_id)
    if pilot["status"] != "COMPLETED":
        raise ApiError("ERR_PILOT_NOT_COMPLETED")
    if media_type not in C.MEDIA_TYPE_BY_TECHNOLOGY[pilot["technology"]]:
        raise ApiError("ERR_MEDIA_TYPE_MISMATCH")
    if mass > pilot["unmanifested_media_kg"]:
        raise ApiError("ERR_MASS_EXCEEDS_SPENT_MEDIA")

    row = db.insert(
        "manifests",
        {
            "pilot_test_id": pilot_id,
            "media_type": media_type,
            "mass_kg": mass,
            "leachate_pfas_ng_per_l": None,
            "waste_classification": None,
            "disposal_method": None,
            "disposal_cost_cents": None,
            "carrier_ref": None,
            "status": "DRAFT",
            "classified_by_user_id": None,
            "void_reason_code": None,
        },
    )
    pilot["unmanifested_media_kg"] = q2(pilot["unmanifested_media_kg"] - mass)
    touch(pilot)
    return created_response(db.public(row))


@bp.route("/residuals-manifests", methods=["GET"])
def list_manifests():
    authenticate(C.ANY_ROLE)
    limit, offset = pagination()
    rows = db.sorted_rows("manifests")
    rows = filter_fk(rows, "pilot_test_id", "pilots")
    rows = apply_scalar_filters(rows, ["status", "waste_classification"])
    return page(rows, limit, offset)


@bp.route("/residuals-manifests/<row_id>", methods=["GET"])
def get_manifest(row_id):
    authenticate(C.ANY_ROLE)
    return detail("manifests", row_id)


@bp.route("/residuals-manifests/<row_id>/classify", methods=["POST"])
def classify_manifest(row_id):
    user_id, _role = authenticate(("StateRegulator",))
    manifest = resolve("manifests", row_id)
    body = Body(["leachate_pfas_ng_per_l"])
    leachate = body.decimal("leachate_pfas_ng_per_l", minimum=0)
    if manifest["status"] != "DRAFT":
        raise ApiError("ERR_MANIFEST_STATE_INVALID")
    manifest["leachate_pfas_ng_per_l"] = leachate
    manifest["waste_classification"] = treatment.waste_classification_for(leachate)
    manifest["classified_by_user_id"] = user_id
    manifest["status"] = "CLASSIFIED"
    touch(manifest)
    return object_response(db.public(manifest))


@bp.route("/residuals-manifests/<row_id>/ship", methods=["POST"])
def ship_manifest(row_id):
    authenticate(("TreatmentEngineer",))
    manifest = resolve("manifests", row_id)
    body = Body(["disposal_method", "carrier_ref"])
    disposal_method = body.enum("disposal_method", C.DISPOSAL_METHODS)
    carrier_ref = body.string("carrier_ref", nonblank=True)

    if manifest["status"] != "CLASSIFIED":
        raise ApiError("ERR_MANIFEST_STATE_INVALID")
    permitted = C.PERMITTED_DISPOSAL_BY_CLASSIFICATION[manifest["waste_classification"]]
    if disposal_method not in permitted:
        raise ApiError("ERR_DISPOSAL_METHOD_PROHIBITED")

    cost = cents(manifest["mass_kg"] * C.DISPOSAL_RATE_CENTS_PER_KG[disposal_method])

    pilot = store.pilots.get(manifest["pilot_test_id"])
    evaluation = None
    if pilot is not None:
        evaluation = store.evaluations.get(pilot["treatment_evaluation_id"])
    if evaluation is not None:
        if evaluation["residuals_spent_cents"] + cost > evaluation["residuals_budget_cents"]:
            raise ApiError("ERR_RESIDUALS_BUDGET_EXCEEDED")

    manifest["disposal_method"] = disposal_method
    manifest["carrier_ref"] = carrier_ref
    manifest["disposal_cost_cents"] = cost
    manifest["status"] = "SHIPPED"
    touch(manifest)
    if evaluation is not None:
        evaluation["residuals_spent_cents"] = evaluation["residuals_spent_cents"] + cost
        touch(evaluation)
    return object_response(db.public(manifest))


@bp.route("/residuals-manifests/<row_id>/void", methods=["POST"])
def void_manifest(row_id):
    authenticate(("TreatmentEngineer",))
    manifest = resolve("manifests", row_id)
    body = Body(["void_reason_code"])
    reason = body.enum("void_reason_code", C.VOID_REASON_CODES)
    if manifest["status"] not in ("DRAFT", "CLASSIFIED"):
        raise ApiError("ERR_MANIFEST_STATE_INVALID")
    manifest["void_reason_code"] = reason
    manifest["status"] = "VOIDED"
    touch(manifest)
    pilot = store.pilots.get(manifest["pilot_test_id"])
    if pilot is not None:
        pilot["unmanifested_media_kg"] = q2(
            pilot["unmanifested_media_kg"] + manifest["mass_kg"]
        )
        touch(pilot)
    return object_response(db.public(manifest))
