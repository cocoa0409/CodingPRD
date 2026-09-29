"""Units, professionals, stability assessments, unit lifecycle, logical clock."""
import re

from flask import Blueprint

import calc
import common
import derive
import envelope
import shape
import store
from errors import ApiError
from guards import authenticate, require_discipline, require_license_active

bp = Blueprint("units", __name__)

CODE_RE = re.compile(r"^[A-Z0-9-]+$")
PLANT_RE = re.compile(r"^[A-Z0-9]+$")
STATE_RE = re.compile(r"^[A-Z]{2}$")

UNIT_SPEC = {
    "unit_code": {"t": "str", "req": True, "min": 6, "max": 12, "re": CODE_RE},
    "unit_name": {"t": "str", "req": True, "min": 1, "max": 120},
    "unit_type": {"t": "enum", "req": True,
                  "vals": ("SURFACE_IMPOUNDMENT", "LANDFILL")},
    "plant_code": {"t": "str", "req": True, "min": 4, "max": 8, "re": PLANT_RE},
    "liner_class": {"t": "enum", "req": True,
                    "vals": ("UNLINED", "CLAY_LINED", "COMPOSITE_LINED")},
    "hazard_potential_class": {"t": "enum", "req": True,
                              "vals": ("LOW", "SIGNIFICANT", "HIGH")},
    "original_ash_in_place_tons": {"t": "int", "req": True, "min": 1},
    "cessation_date": {"t": "date", "req": True},
    "uppermost_aquifer_separation_ft": {"t": "num", "req": True, "min": 0, "dp": 2},
    "wetland_distance_ft": {"t": "num", "req": True, "min": 0, "dp": 2},
    "seismic_pga_g": {"t": "num", "req": True, "min": 0, "dp": 3},
    "fault_distance_ft": {"t": "num", "req": True, "min": 0, "dp": 2},
    "unstable_area_flag": {"t": "bool", "req": True},
}


@bp.post("/ccr/units")
def create_unit():
    authenticate(("UtilityAdmin",))
    data = shape.read_body(UNIT_SPEC)
    common.no_future_date(data["cessation_date"])
    common.unique_code(store.units, "unit_code", data["unit_code"])
    unit = dict(data)
    unit["ash_in_place_tons"] = data["original_ash_in_place_tons"]
    unit["ash_mass_balance_ok"] = True
    unit["location_restriction_verdict"] = calc.location_restriction_verdict(unit)
    unit["demonstration_required"] = (
        unit["location_restriction_verdict"] == "RESTRICTED_DEMONSTRATION_REQUIRED")
    unit["closure_state"] = "ACTIVE"
    unit["cap_integrity_state"] = "NOT_APPLICABLE"
    unit["governing_stability_verdict"] = "UNASSESSED"
    unit["granted_extension_months"] = 0
    unit["closure_deadline_date"] = calc.closure_deadline_date(unit)
    unit["closure_initiated_on"] = None
    unit["closure_completed_on"] = None
    unit["closure_timeliness"] = "PENDING"
    unit["post_closure_care_start_on"] = None
    unit["deficiency_extension_months"] = 0
    unit["post_closure_care_end_date"] = None
    unit["cap_repair_due_date"] = None
    unit["ssi_notice_due_date"] = None
    unit["stability_posting_due_date"] = None
    unit["closure_plan_posting_due_date"] = None
    unit["extension_demonstration_due_date"] = None
    unit["overdue_posting_types"] = []
    unit["late_posting_count"] = 0
    unit["_pending_obligation_due"] = False
    unit["compliance_posture"] = "COMPLIANT"
    store.stamp_new(unit)
    store.units[unit["id"]] = unit
    program = {
        "unit_id": unit["id"],
        "phase": "DETECTION",
        "network_certified": False,
        "network_certified_on": None,
        "network_certified_by": None,
        "statistical_method": "PARAMETRIC_PREDICTION_INTERVAL",
        "comparison_basis": "INTERWELL",
        "sampling_frequency": "SEMIANNUAL",
        "background_window_start_on": None,
        "background_window_end_on": None,
        "background_well_count": 0,
        "downgradient_well_count": 0,
        "last_validated_event_id": None,
        "next_sampling_due_date": None,
        "assessment_entered_on": None,
        "corrective_action_entered_on": None,
        "remedy_base_cost_usd_cents": None,
        "remedy_duration_years": None,
        "remedy_description": None,
        "assurance_amount_usd_cents": None,
    }
    store.stamp_new(program)
    store.programs[program["id"]] = program
    unit["monitoring_program_id"] = program["id"]
    return envelope.created(derive.unit(unit))


PROFESSIONAL_SPEC = {
    "full_name": {"t": "str", "req": True, "min": 1, "max": 120},
    "license_number": {"t": "str", "req": True, "min": 4, "max": 20, "re": CODE_RE},
    "license_state": {"t": "str", "req": True, "min": 2, "max": 2, "re": STATE_RE},
    "discipline": {"t": "enum", "req": True,
                   "vals": ("GEOTECHNICAL", "CIVIL", "HYDROGEOLOGY", "STATISTICS")},
    "license_status": {"t": "enum", "vals": ("ACTIVE", "SUSPENDED", "LAPSED"),
                       "default": "ACTIVE"},
}


@bp.post("/ccr/professionals")
def create_professional():
    authenticate(("UtilityAdmin",))
    data = shape.read_body(PROFESSIONAL_SPEC)
    if data["license_status"] is None:
        data["license_status"] = "ACTIVE"
    common.unique_code(store.professionals, "license_number",
                       data["license_number"], "license_state",
                       data["license_state"])
    record = dict(data)
    record["license_status_effective_on"] = store.fmt_date(store.today())
    store.stamp_new(record)
    store.professionals[record["id"]] = record
    return envelope.created(derive.professional(record))


LICENSE_SPEC = {
    "license_status": {"t": "enum", "req": True,
                       "vals": ("ACTIVE", "SUSPENDED", "LAPSED")},
    "effective_on": {"t": "date", "req": True},
}


@bp.post("/ccr/professionals/<professional_id>/license-status")
def set_license_status(professional_id):
    authenticate(("UtilityAdmin",))
    data = shape.read_body(LICENSE_SPEC)
    record = common.get_body_professional(professional_id)
    record["license_status"] = data["license_status"]
    record["license_status_effective_on"] = data["effective_on"]
    store.touch(record)
    return envelope.ok(derive.professional(record))


STABILITY_SPEC = {
    "unit_id": {"t": "id", "req": True},
    "assessed_on": {"t": "date", "req": True},
    "factor_of_safety_static": {"t": "num", "req": True, "dp": 2},
    "factor_of_safety_seismic": {"t": "num", "req": True, "dp": 2},
    "factor_of_safety_liquefaction": {"t": "num", "req": True, "dp": 2},
}


@bp.post("/ccr/stability-assessments")
def create_stability():
    actor = authenticate(("ProfessionalEngineer",))
    data = shape.read_body(STABILITY_SPEC)
    for name in ("factor_of_safety_static", "factor_of_safety_seismic",
                 "factor_of_safety_liquefaction"):
        if data[name] <= 0:
            raise shape.bad("Field '%s' must be greater than 0." % name)
    unit = common.get_unit(data["unit_id"])
    common.no_future_date(data["assessed_on"])
    require_license_active(actor)
    require_discipline(actor, common.D_STABILITY)
    common.unit_not_care_complete(unit)
    record = dict(data)
    record["certifying_professional_id"] = actor.user_id
    verdict, criteria = calc.stability_assessment_verdict(record)
    record["verdict"] = verdict
    record["deficient_criteria"] = criteria
    record["superseded"] = False
    store.stamp_new(record, versioned=False)
    store.stability_assessments[record["id"]] = record
    governing, unit_verdict = calc.governing_stability_verdict(unit["id"])
    unit["governing_stability_verdict"] = unit_verdict
    unit["stability_posting_due_date"] = store.add_days(
        governing["assessed_on"], calc.STABILITY_POSTING_WINDOW_DAYS)
    store.touch(unit)
    common.settle(unit)
    return envelope.created(derive.stability(record))


BEGIN_SPEC = {"initiated_on": {"t": "date", "req": True}}


@bp.post("/ccr/units/<unit_id>/begin-closure")
def begin_closure(unit_id):
    authenticate(("UtilityAdmin",))
    data = shape.read_body(BEGIN_SPEC)
    unit = common.get_unit(unit_id)
    common.unit_state(unit, ("ACTIVE", "CLOSURE_PLANNED"))
    common.not_frozen(unit)
    plan = common.approved_plan(unit["id"])
    if plan is None:
        raise ApiError("ERR_NO_APPROVED_CLOSURE_PLAN",
                       "The unit has no APPROVED closure plan.")
    today = store.fmt_date(store.today())
    if today > unit["closure_deadline_date"]:
        raise ApiError("ERR_CLOSURE_DEADLINE_MISSED",
                       "The closure deadline has already passed.")
    unit["closure_initiated_on"] = data["initiated_on"]
    unit["closure_state"] = "CLOSING"
    unit["closure_timeliness"] = "ON_TIME"
    store.touch(unit)
    common.settle(unit)
    return envelope.ok(derive.unit(unit))


COMPLETE_SPEC = {"completed_on": {"t": "date", "req": True}}


@bp.post("/ccr/units/<unit_id>/complete-closure")
def complete_closure(unit_id):
    actor = authenticate(("ProfessionalEngineer",))
    data = shape.read_body(COMPLETE_SPEC)
    unit = common.get_unit(unit_id)
    require_license_active(actor)
    require_discipline(actor, common.D_CLOSURE_WORK)
    common.unit_state(unit, ("CLOSING",))
    plan = common.approved_plan(unit["id"])
    if (plan is not None and plan["selected_method"] == "CLOSURE_BY_REMOVAL"
            and unit["ash_in_place_tons"] != 0):
        raise ApiError("ERR_ASH_REMOVAL_INCOMPLETE",
                       "Ash remains in place under a removal plan.")
    unit["closure_completed_on"] = data["completed_on"]
    unit["post_closure_care_start_on"] = data["completed_on"]
    unit["closure_state"] = "POST_CLOSURE_CARE"
    if unit["cap_integrity_state"] == "NOT_APPLICABLE":
        unit["cap_integrity_state"] = "ADEQUATE"
    unit["post_closure_care_end_date"] = calc.post_closure_care_end_date(unit)
    store.touch(unit)
    common.settle(unit)
    return envelope.ok(derive.unit(unit))


@bp.post("/ccr/units/<unit_id>/certify-care-complete")
def certify_care_complete(unit_id):
    actor = authenticate(("ProfessionalEngineer",))
    shape.read_body({})
    unit = common.get_unit(unit_id)
    require_license_active(actor)
    require_discipline(actor, common.D_CLOSURE_WORK)
    common.unit_state(unit, ("POST_CLOSURE_CARE",))
    program = calc.unit_program(unit["id"])
    if program is not None:
        common.program_phase(program, ("DETECTION",))
    inspection = common.governing_inspection(unit["id"])
    if inspection is not None:
        common.segregation(actor.user_id, inspection["inspecting_professional_id"])
    if unit["cap_integrity_state"] == "DEFICIENT":
        raise ApiError("ERR_CAP_DEFICIENCY_UNRESOLVED",
                       "The final cover deficiency is unresolved.")
    derive.refresh_unit(unit)
    end_date = unit["post_closure_care_end_date"]
    today = store.fmt_date(store.today())
    if end_date is None or today < end_date:
        raise ApiError("ERR_CARE_PERIOD_NOT_ELAPSED",
                       "The post-closure care period has not yet elapsed.")
    unit["closure_state"] = "CARE_COMPLETE"
    store.touch(unit)
    common.settle(unit)
    return envelope.ok(derive.unit(unit))


CLOCK_SPEC = {"to_iso8601": {"t": "instant", "req": True}}


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("UtilityAdmin",))
    data = shape.read_body(CLOCK_SPEC)
    moment = store.parse_instant(data["to_iso8601"])
    store.clock_set(moment)
    return envelope.ok({"current_utc": store.iso_instant(store.clock_now())})
