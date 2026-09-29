"""Emergency action plans and annual exercises (PRD Section 3.5)."""

from flask import Blueprint, request

import calc
import guards
from common import (
    ApiError, add_months, body_dict, ok, ok_list, pagination, q_enum, q_str,
    v_dt, v_bool, v_enum, v_int, v_string,
)
from derive import (
    dam_certified_assessment, dam_eap_required, dam_hazard_class, dam_plans,
    paginate, plan_exercises, serialize_exercise, serialize_plan,
)
from store import db, insert, insertion_order, touch

bp = Blueprint("eaps", __name__)


@bp.route("/emergency-action-plans", methods=["POST"])
def create_plan():
    user_id, role = guards.authenticate(request, ("DamOwner",))
    body = body_dict()
    dam_id = v_string(body, "dam_id", min_len=1)
    version_label = v_string(body, "version_label", min_len=1)
    inundation_map_ref = v_string(body, "inundation_map_ref", min_len=1)
    notification_flowchart_ref = v_string(body, "notification_flowchart_ref", min_len=1)
    notification_contact_count = v_int(body, "notification_contact_count", minimum=0)
    drawdown_procedure_ref = v_string(body, "drawdown_procedure_ref", min_len=1)
    expected_dam_version = v_int(body, "expected_dam_version")
    dam = guards.get_dam(dam_id)
    guards.check_identity(user_id, role)
    guards.check_resource_owner(user_id, role, dam["owner_id"])
    guards.check_dam_operable(dam)
    guards.check_dam_version(dam, expected_dam_version)
    plan = insert(db.plans, {
        "dam_id": dam["id"],
        "version_label": version_label,
        "inundation_map_ref": inundation_map_ref,
        "notification_flowchart_ref": notification_flowchart_ref,
        "notification_contact_count": notification_contact_count,
        "drawdown_procedure_ref": drawdown_procedure_ref,
        "status": "DRAFT",
        "review_findings": None,
        "approved_at": None,
        "expires_at": None,
    })
    touch(dam)
    return ok(serialize_plan(plan), 201)


@bp.route("/emergency-action-plans/<plan_id>", methods=["GET"])
def read_plan(plan_id):
    user_id, role = guards.authenticate(
        request, ("ProgramAdmin", "Engineer", "DamOwner", "EmergencyCoordinator"))
    plan = guards.get_plan(plan_id)
    guards.check_identity(user_id, role)
    return ok(serialize_plan(plan))


@bp.route("/emergency-action-plans", methods=["GET"])
def list_plans():
    user_id, role = guards.authenticate(
        request, ("ProgramAdmin", "Engineer", "DamOwner", "EmergencyCoordinator"))
    limit, offset = pagination()
    dam_id = q_str("dam_id")
    status = q_enum("status", calc.EAP_STATUSES)
    guards.check_identity(user_id, role)
    rows = list(db.plans.values())
    if dam_id is not None:
        rows = [r for r in rows if r["dam_id"] == dam_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    data, total = paginate(rows, limit, offset, serialize_plan)
    return ok_list(data, limit, offset, total)


@bp.route("/emergency-action-plans/<plan_id>/submit", methods=["POST"])
def submit_plan(plan_id):
    user_id, role = guards.authenticate(request, ("DamOwner",))
    body = body_dict()
    inundation_map_ref = v_string(body, "inundation_map_ref", required=False, min_len=1)
    notification_flowchart_ref = v_string(body, "notification_flowchart_ref", required=False, min_len=1)
    notification_contact_count = v_int(body, "notification_contact_count", required=False, minimum=0)
    drawdown_procedure_ref = v_string(body, "drawdown_procedure_ref", required=False, min_len=1)
    plan = guards.get_plan(plan_id)
    dam = guards.get_dam(plan["dam_id"])
    guards.check_identity(user_id, role)
    guards.check_resource_owner(user_id, role, dam["owner_id"])
    guards.check_plan_state(plan, ("DRAFT", "REVISION_REQUIRED"))
    guards.check_dam_classified(dam)

    # Supplied values overwrite the stored ones before the admission checks run.
    effective_map = inundation_map_ref if inundation_map_ref is not None else plan["inundation_map_ref"]
    effective_flowchart = (notification_flowchart_ref if notification_flowchart_ref is not None
                           else plan["notification_flowchart_ref"])
    effective_contacts = (notification_contact_count if notification_contact_count is not None
                          else plan["notification_contact_count"])
    effective_procedure = (drawdown_procedure_ref if drawdown_procedure_ref is not None
                           else plan["drawdown_procedure_ref"])

    hazard_class = dam_hazard_class(dam)
    minimum_contacts = calc.MIN_NOTIFICATION_CONTACTS[hazard_class]
    if effective_contacts < minimum_contacts:
        raise ApiError("ERR_INSUFFICIENT_NOTIFICATION_CONTACTS",
                       "hazard class %s requires at least %d notification contacts"
                       % (hazard_class, minimum_contacts))
    if calc.EAP_REQUIRED[hazard_class]:
        assessment = dam_certified_assessment(dam["id"])
        certified_map = assessment["inundation_map_ref"] if assessment else None
        if effective_map != certified_map:
            raise ApiError("ERR_INUNDATION_MAP_STALE",
                           "plan inundation_map_ref does not match the certified assessment")

    plan["inundation_map_ref"] = effective_map
    plan["notification_flowchart_ref"] = effective_flowchart
    plan["notification_contact_count"] = effective_contacts
    plan["drawdown_procedure_ref"] = effective_procedure
    plan["status"] = "SUBMITTED"
    touch(plan)
    touch(dam)
    return ok(serialize_plan(plan))


@bp.route("/emergency-action-plans/<plan_id>/review", methods=["POST"])
def review_plan(plan_id):
    user_id, role = guards.authenticate(request, ("Engineer",))
    body = body_dict()
    decision = v_enum(body, "decision", ("APPROVE", "REVISE"))
    findings = v_string(body, "findings", min_len=1)
    plan = guards.get_plan(plan_id)
    engineer = guards.check_identity(user_id, role)
    guards.check_plan_state(plan, ("SUBMITTED",))
    guards.check_license_active(engineer)
    dam = guards.get_dam(plan["dam_id"])
    plan["review_findings"] = findings
    if decision == "REVISE":
        plan["status"] = "REVISION_REQUIRED"
        touch(plan)
    else:
        plan["status"] = "APPROVED"
        plan["approved_at"] = db.clock
        validity_months = calc.EAP_VALIDITY_MONTHS[dam_hazard_class(dam)]
        plan["expires_at"] = add_months(db.clock, validity_months) if validity_months else None
        touch(plan)
        for other in insertion_order(dam_plans(dam["id"])):
            if other["id"] != plan["id"] and other["status"] == "APPROVED":
                other["status"] = "SUPERSEDED"
                touch(other)
    touch(dam)
    return ok(serialize_plan(plan))


@bp.route("/emergency-action-plans/<plan_id>/exercises", methods=["POST"])
def log_exercise(plan_id):
    user_id, role = guards.authenticate(request, ("DamOwner", "EmergencyCoordinator"))
    body = body_dict()
    exercise_type = v_enum(body, "exercise_type", calc.EXERCISE_TYPES)
    conducted_at = v_dt(body, "conducted_at")
    participant_count = v_int(body, "participant_count", minimum=0)
    notification_test_passed = v_bool(body, "notification_test_passed")
    plan = guards.get_plan(plan_id)
    guards.check_identity(user_id, role)
    guards.check_plan_state(plan, ("APPROVED",))
    # Rung 34: exercises are logged after the fact.
    if conducted_at > db.clock:
        raise ApiError("ERR_EXERCISE_DATE_IN_FUTURE",
                       "conducted_at is later than the current logical clock")
    dam = guards.get_dam(plan["dam_id"])
    hazard_class = dam_hazard_class(dam)
    outcome, reason = calc.grade_exercise(
        hazard_class, notification_test_passed, participant_count, exercise_type)
    exercise = insert(db.exercises, {
        "eap_id": plan["id"],
        "exercise_type": exercise_type,
        "conducted_at": conducted_at,
        "participant_count": participant_count,
        "notification_test_passed": notification_test_passed,
        "outcome": outcome,
        "deficiency_reason": reason,
        "logged_by_user_id": user_id,
    }, versioned=False)
    if outcome == "DEFICIENT":
        insert(db.deficiencies, {
            "dam_id": dam["id"],
            "inspection_id": None,
            "source": "SYSTEM_EXERCISE",
            "category": "EAP_EXERCISE",
            "severity": "MODERATE",
            "description": "Emergency action plan exercise graded DEFICIENT (%s)." % reason,
            "status": "OPEN",
            "remediation_due_at": None,
            "closed_at": None,
        })
        touch(dam)
    return ok(serialize_exercise(exercise), 201)


@bp.route("/emergency-action-plans/<plan_id>/exercises", methods=["GET"])
def list_exercises(plan_id):
    user_id, role = guards.authenticate(
        request, ("ProgramAdmin", "Engineer", "DamOwner", "EmergencyCoordinator"))
    limit, offset = pagination()
    outcome = q_enum("outcome", calc.EXERCISE_OUTCOMES)
    plan = guards.get_plan(plan_id)
    guards.check_identity(user_id, role)
    rows = plan_exercises(plan["id"])
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    data, total = paginate(rows, limit, offset, serialize_exercise)
    return ok_list(data, limit, offset, total)
