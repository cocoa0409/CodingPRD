"""Consequence assessments and the reclassification cascade (PRD Section 3.2)."""

from flask import Blueprint, request

import calc
import guards
import services
from common import (
    ApiError, body_dict, dec, ok, ok_list, pagination, q_enum, q_str,
    v_enum, v_int, v_num, v_string,
)
from derive import (
    dam_certified_assessment, dam_eap_required, dam_hazard_class, dam_plans,
    paginate, serialize_assessment,
)
from store import db, insert, insertion_order, touch

bp = Blueprint("assessments", __name__)


@bp.route("/consequence-assessments", methods=["POST"])
def create_assessment():
    user_id, role = guards.authenticate(request, ("Engineer",))
    body = body_dict()
    dam_id = v_string(body, "dam_id", min_len=1)
    population_at_risk = v_int(body, "population_at_risk", minimum=0)
    habitable_structures = v_int(body, "habitable_structures", minimum=0)
    critical_facilities = v_int(body, "critical_facilities", minimum=0)
    breach_peak_outflow_cfs = v_num(body, "breach_peak_outflow_cfs", exclusive_min=0)
    breach_travel_time_minutes = v_int(body, "breach_travel_time_minutes", minimum=1)
    inundation_area_acres = v_num(body, "inundation_area_acres", exclusive_min=0)
    inundation_map_ref = v_string(body, "inundation_map_ref", min_len=1)
    dam = guards.get_dam(dam_id)
    guards.check_identity(user_id, role)
    guards.check_dam_operable(dam, block_removal_permitted=True)

    screening_score = calc.consequence_score(
        population_at_risk, habitable_structures, critical_facilities,
        breach_travel_time_minutes, inundation_area_acres, "screening")
    recommended = calc.hazard_classification(screening_score, population_at_risk)
    assessment = insert(db.assessments, {
        "dam_id": dam["id"],
        "prepared_by_user_id": user_id,
        "population_at_risk": population_at_risk,
        "habitable_structures": habitable_structures,
        "critical_facilities": critical_facilities,
        "breach_peak_outflow_cfs": breach_peak_outflow_cfs,
        "breach_travel_time_minutes": breach_travel_time_minutes,
        "inundation_area_acres": inundation_area_acres,
        "inundation_map_ref": inundation_map_ref,
        "screening_score": screening_score,
        "recommended_hazard_class": recommended,
        "certified_score": None,
        "certified_hazard_class": None,
        "status": "DRAFT",
        "certified_at": None,
        "superseded_at": None,
    })
    return ok(serialize_assessment(assessment), 201)


@bp.route("/consequence-assessments/<assessment_id>", methods=["GET"])
def read_assessment(assessment_id):
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer", "DamOwner"))
    assessment = guards.get_assessment(assessment_id)
    guards.check_identity(user_id, role)
    return ok(serialize_assessment(assessment))


@bp.route("/consequence-assessments", methods=["GET"])
def list_assessments():
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer", "DamOwner"))
    limit, offset = pagination()
    dam_id = q_str("dam_id")
    status = q_enum("status", calc.ASSESSMENT_STATUSES)
    guards.check_identity(user_id, role)
    rows = list(db.assessments.values())
    if dam_id is not None:
        rows = [r for r in rows if r["dam_id"] == dam_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    data, total = paginate(rows, limit, offset, serialize_assessment)
    return ok_list(data, limit, offset, total)


@bp.route("/consequence-assessments/<assessment_id>/certify", methods=["POST"])
def certify_assessment(assessment_id):
    user_id, role = guards.authenticate(request, ("Engineer",))
    assessment = guards.get_assessment(assessment_id)
    engineer = guards.check_identity(user_id, role)
    guards.check_assessment_state(assessment, ("DRAFT",))
    dam = guards.get_dam(assessment["dam_id"])
    guards.check_dam_operable(dam)
    guards.check_license_active(engineer)
    guards.check_certified_for(engineer, dam_hazard_class(dam))
    # Rung 33: the breach analysis must be complete
    if (dec(assessment["breach_peak_outflow_cfs"]) <= 0
            or dec(assessment["breach_travel_time_minutes"]) <= 0
            or dec(assessment["inundation_area_acres"]) <= 0):
        raise ApiError("ERR_BREACH_ANALYSIS_INCOMPLETE",
                       "breach analysis outputs must all be strictly positive")

    # Link 1: the dam's previously certified assessment is superseded.
    prior = dam_certified_assessment(dam["id"])
    if prior is not None and prior["id"] != assessment["id"]:
        prior["status"] = "SUPERSEDED"
        prior["superseded_at"] = db.clock
        touch(prior)

    certified_score = calc.consequence_score(
        assessment["population_at_risk"], assessment["habitable_structures"],
        assessment["critical_facilities"], assessment["breach_travel_time_minutes"],
        assessment["inundation_area_acres"], "certified")
    assessment["certified_score"] = certified_score
    assessment["certified_hazard_class"] = calc.hazard_classification(
        certified_score, assessment["population_at_risk"])
    assessment["status"] = "CERTIFIED"
    assessment["certified_at"] = db.clock
    touch(assessment)

    # Link 3: an approved plan drawn against a different inundation map is
    # knocked back to REVISION_REQUIRED and loses its expiry.
    moved_any = False
    for plan in insertion_order(dam_plans(dam["id"])):
        if plan["status"] == "APPROVED" and plan["inundation_map_ref"] != assessment["inundation_map_ref"]:
            plan["status"] = "REVISION_REQUIRED"
            plan["expires_at"] = None
            touch(plan)
            moved_any = True

    # Link 4: fires only as a consequence of link 3 actually moving a plan.
    if moved_any:
        services.open_eap_missing_deficiency(dam)

    # Link 2: the dam's derived classification fields are rewritten; the dam's
    # version advances by 1 across the whole certification.
    touch(dam)
    return ok(serialize_assessment(assessment))
