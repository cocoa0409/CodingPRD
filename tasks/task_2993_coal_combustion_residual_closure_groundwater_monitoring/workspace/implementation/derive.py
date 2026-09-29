"""Derived-field refresh and response serialization.

Derived values are re-derived from the current store on every read; doing so
never bumps `version` or `updated_at` (PRD 2.4).
"""
import calc
import store


# ------------------------------------------------------------------- refresh
def refresh_unit(unit):
    _, verdict = calc.governing_stability_verdict(unit["id"])
    unit["governing_stability_verdict"] = verdict
    calc.ash_in_place_balance(unit)
    count = calc.deficient_inspection_count(unit["id"])
    unit["deficiency_extension_months"] = min(
        calc.DEFICIENCY_EXTENSION_CAP_MONTHS,
        count * calc.DEFICIENCY_EXTENSION_MONTHS_EACH)
    unit["post_closure_care_end_date"] = calc.post_closure_care_end_date(unit)
    unit["closure_deadline_date"] = calc.closure_deadline_date(unit)
    program = calc.unit_program(unit["id"])
    unit["monitoring_program_id"] = program["id"] if program else None
    unit["compliance_posture"] = calc.compliance_posture(unit)
    return unit


def refresh_program(program):
    background, downgradient, _ = calc.network_certification_readiness(program)
    program["background_well_count"] = background
    program["downgradient_well_count"] = downgradient
    last_id, due = calc.next_sampling_due_date(program)
    program["last_validated_event_id"] = last_id
    program["next_sampling_due_date"] = due
    return program


def refresh_agreement(agreement):
    agreement["shipped_tons_total"] = calc.agreement_shipped_tons(agreement["id"])
    return agreement


def refresh_event(event):
    event["result_count"] = len([r for r in store.analytical_results.values()
                                 if r["sampling_event_id"] == event["id"]])
    return event


def sync_agreement_suspension(unit):
    """PRD 2.8: a RESTRICTED or FROZEN posture suspends the unit's ACTIVE reuse
    agreements, and a posture that clears restores them."""
    posture = calc.compliance_posture(unit)
    today = store.fmt_date(store.today())
    for agreement in calc.unit_agreements(unit["id"]):
        if posture in ("RESTRICTED", "FROZEN"):
            if agreement["status"] == "ACTIVE":
                agreement["status"] = "SUSPENDED"
                agreement["suspended_on"] = today
                store.touch(agreement)
        else:
            if agreement["status"] == "SUSPENDED":
                agreement["status"] = "ACTIVE"
                agreement["suspended_on"] = None
                store.touch(agreement)


def settle_unit(unit):
    """Full post-write reconciliation for a unit."""
    refresh_unit(unit)
    sync_agreement_suspension(unit)
    refresh_unit(unit)
    return unit


# --------------------------------------------------------------- serializers
def _base(record, versioned=True):
    out = {"id": record["id"], "created_at": record["created_at"]}
    if versioned:
        out["updated_at"] = record["updated_at"]
        out["version"] = record["version"]
    return out


UNIT_FIELDS = (
    "unit_code", "unit_name", "unit_type", "plant_code", "liner_class",
    "hazard_potential_class", "original_ash_in_place_tons", "ash_in_place_tons",
    "cessation_date", "uppermost_aquifer_separation_ft", "wetland_distance_ft",
    "seismic_pga_g", "fault_distance_ft", "unstable_area_flag",
    "location_restriction_verdict", "demonstration_required", "closure_state",
    "cap_integrity_state", "compliance_posture", "governing_stability_verdict",
    "monitoring_program_id", "granted_extension_months", "closure_deadline_date",
    "closure_initiated_on", "closure_completed_on", "closure_timeliness",
    "post_closure_care_start_on", "deficiency_extension_months",
    "post_closure_care_end_date", "cap_repair_due_date", "ssi_notice_due_date",
    "stability_posting_due_date", "closure_plan_posting_due_date",
    "extension_demonstration_due_date", "overdue_posting_types",
    "late_posting_count", "ash_mass_balance_ok",
)


def unit(record):
    refresh_unit(record)
    out = _base(record)
    for name in UNIT_FIELDS:
        out[name] = record[name]
    return out


PROFESSIONAL_FIELDS = ("full_name", "license_number", "license_state",
                       "discipline", "license_status",
                       "license_status_effective_on")


def professional(record):
    out = _base(record)
    for name in PROFESSIONAL_FIELDS:
        out[name] = record[name]
    return out


STABILITY_FIELDS = ("unit_id", "certifying_professional_id", "assessed_on",
                    "factor_of_safety_static", "factor_of_safety_seismic",
                    "factor_of_safety_liquefaction", "verdict",
                    "deficient_criteria", "superseded")


def stability(record):
    calc.governing_stability_verdict(record["unit_id"])
    out = _base(record, versioned=False)
    for name in STABILITY_FIELDS:
        out[name] = record[name]
    return out


WELL_FIELDS = ("unit_id", "well_code", "well_role", "aquifer_zone",
               "screen_top_ft", "screen_bottom_ft", "installed_on",
               "well_status", "decommissioned_on", "decommission_reason")


def well(record):
    out = _base(record)
    for name in WELL_FIELDS:
        out[name] = record[name]
    return out


PROGRAM_FIELDS = (
    "unit_id", "phase", "network_certified", "network_certified_on",
    "network_certified_by", "statistical_method", "comparison_basis",
    "sampling_frequency", "background_window_start_on",
    "background_window_end_on", "background_well_count",
    "downgradient_well_count", "last_validated_event_id",
    "next_sampling_due_date", "assessment_entered_on",
    "corrective_action_entered_on", "remedy_base_cost_usd_cents",
    "remedy_duration_years", "remedy_description", "assurance_amount_usd_cents",
)


def program(record):
    refresh_program(record)
    out = _base(record)
    for name in PROGRAM_FIELDS:
        out[name] = record[name]
    return out


EVENT_FIELDS = ("program_id", "submitted_by_professional_id", "event_code",
                "event_type", "sampled_on", "status", "result_count",
                "validated_on", "rejection_reason")


def event(record):
    refresh_event(record)
    out = _base(record)
    for name in EVENT_FIELDS:
        out[name] = record[name]
    return out


RESULT_FIELDS = ("sampling_event_id", "well_id", "parameter_code",
                 "concentration", "unit_of_measure", "detection_flag",
                 "reporting_limit", "effective_value")


def result(record):
    out = _base(record, versioned=False)
    for name in RESULT_FIELDS:
        out[name] = record[name]
    return out


EVALUATION_FIELDS = (
    "program_id", "compliance_well_id", "reviewing_professional_id",
    "asd_certifying_professional_id", "comparison_source_event_id",
    "evaluation_code", "parameter_code", "method_used", "comparison_basis_used",
    "background_n", "background_mean", "background_stdev",
    "background_upper_limit", "comparison_value", "verdict", "retest_confirmed",
    "determined_on", "status", "asd_deadline_date", "asd_submitted_on",
    "asd_decided_on", "asd_narrative",
)


def evaluation(record):
    out = _base(record)
    for name in EVALUATION_FIELDS:
        out[name] = record[name]
    return out


PLAN_FIELDS = (
    "unit_id", "engineering_certified_by", "cost_certified_by", "plan_code",
    "selected_method", "in_place_capital_usd_cents",
    "in_place_annual_care_usd_cents", "removal_capital_usd_cents",
    "removal_annual_care_usd_cents", "care_period_years",
    "selection_justification", "in_place_pv_usd_cents", "removal_pv_usd_cents",
    "in_place_nominal_usd_cents", "removal_nominal_usd_cents",
    "cost_variance_pct", "recommended_method", "status",
    "engineering_certified_on", "cost_certified_on", "design_narrative",
    "cost_basis_note", "approved_on", "permit_reference", "return_count",
)


def plan(record):
    out = _base(record)
    for name in PLAN_FIELDS:
        out[name] = record[name]
    return out


EXTENSION_FIELDS = ("unit_id", "requested_months", "justification_category",
                    "narrative", "status", "granted_months", "decided_on",
                    "decision_note", "rescinded_on", "rescission_reason")


def extension(record):
    out = _base(record)
    for name in EXTENSION_FIELDS:
        out[name] = record[name]
    return out


AGREEMENT_FIELDS = (
    "unit_id", "qualified_by", "agreement_code", "product_type",
    "offtaker_name", "committed_tons", "commitment_start_on",
    "commitment_end_on", "loi_percent", "retained_325_percent",
    "oxide_sum_percent", "market_price_usd_cents_per_ton",
    "haul_distance_miles", "meets_astm_c618_class_f", "qualification_score",
    "status", "shipped_tons_total", "qualified_on", "activated_on",
    "suspended_on",
)


def agreement(record):
    refresh_agreement(record)
    out = _base(record)
    for name in AGREEMENT_FIELDS:
        out[name] = record[name]
    return out


SHIPMENT_FIELDS = ("agreement_id", "shipment_code", "tons", "shipped_on",
                   "status", "returned_on", "return_reason")


def shipment(record):
    out = _base(record)
    for name in SHIPMENT_FIELDS:
        out[name] = record[name]
    return out


INSPECTION_FIELDS = ("unit_id", "inspecting_professional_id", "inspected_on",
                     "erosion_severity", "settlement_inches",
                     "vegetation_cover_pct", "note", "verdict",
                     "deficient_criteria")


def inspection(record):
    out = _base(record, versioned=False)
    for name in INSPECTION_FIELDS:
        out[name] = record[name]
    return out


POSTING_FIELDS = ("unit_id", "posting_type", "posted_on", "document_uri",
                  "document_sha256", "community_meeting_held_on",
                  "posted_by_user_id", "status", "withdrawn_on",
                  "withdrawal_reason", "satisfied_obligation", "days_late")


def posting(record):
    owner = store.units.get(record["unit_id"])
    if owner is not None:
        calc.refresh_postings(owner)
    out = _base(record)
    for name in POSTING_FIELDS:
        out[name] = record[name]
    return out
