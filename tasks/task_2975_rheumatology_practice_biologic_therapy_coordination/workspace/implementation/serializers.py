"""Wire representations.  Datetimes become ISO 8601 UTC instants with exactly
three fractional digits; derived postures are recomputed at read time."""

import calculations as calc
from store import db, fmt_ts


def patient_out(row):
    """PRD 3.3: the postures are re-evaluated whenever the patient is read."""
    return {
        "id": row["id"],
        "mrn": row["mrn"],
        "full_name": row["full_name"],
        "date_of_birth": row["date_of_birth"],
        "diagnosis_code": row["diagnosis_code"],
        "registry_consent": row["registry_consent"],
        "tb_screen_status": calc.tb_screen_status(row["id"]),
        "hbv_screen_status": calc.hbv_screen_status(row["id"]),
        "latest_activity_score": row["latest_activity_score"],
        "latest_activity_category": row["latest_activity_category"],
        "target_status": row["target_status"],
        "administered_dose_total": row["administered_dose_total"],
        "active_episode_count": row["active_episode_count"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def clinician_out(row):
    return {
        "id": row["id"],
        "npi": row["npi"],
        "full_name": row["full_name"],
        "role_type": row["role_type"],
        "can_attest_formulary_exception": row["can_attest_formulary_exception"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def drug_out(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "molecule_class": row["molecule_class"],
        "route": row["route"],
        "is_biosimilar": row["is_biosimilar"],
        "formulary_tier": row["formulary_tier"],
        "acquisition_cost_cents": row["acquisition_cost_cents"],
        "admin_time_minutes": row["admin_time_minutes"],
        "monitoring_panel_type": row["monitoring_panel_type"],
        "monitoring_panel_interval_days": row["monitoring_panel_interval_days"],
        "tb_screen_required": row["tb_screen_required"],
        "hbv_screen_required": row["hbv_screen_required"],
        "step_therapy_required_classes": list(row["step_therapy_required_classes"]),
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def payer_plan_out(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "pharmacy_benefit_enabled": row["pharmacy_benefit_enabled"],
        "medical_benefit_enabled": row["medical_benefit_enabled"],
        "site_of_care_policy": row["site_of_care_policy"],
        "coinsurance_pct": row["coinsurance_pct"],
        "deductible_remaining_cents": row["deductible_remaining_cents"],
        "medical_facility_fee_cents": row["medical_facility_fee_cents"],
        "hospital_outpatient_multiplier": row["hospital_outpatient_multiplier"],
        "appeal_rounds_allowed": row["appeal_rounds_allowed"],
        "auth_validity_days": row["auth_validity_days"],
        "step_therapy_classes_required": list(row["step_therapy_classes_required"]),
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def chair_out(row):
    return {
        "id": row["id"],
        "label": row["label"],
        "site_type": row["site_type"],
        "turnover_buffer_minutes": row["turnover_buffer_minutes"],
        "status": row["status"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def visit_out(row):
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "clinician_id": row["clinician_id"],
        "visit_datetime": fmt_ts(row["visit_datetime"]),
        "visit_end_datetime": fmt_ts(row["visit_end_datetime"]),
        "visit_type": row["visit_type"],
        "status": row["status"],
        "scoring_instrument": row["scoring_instrument"],
        "tender_joint_count": row["tender_joint_count"],
        "swollen_joint_count": row["swollen_joint_count"],
        "patient_global_assessment": row["patient_global_assessment"],
        "physician_global_assessment": row["physician_global_assessment"],
        "crp_mg_dl": row["crp_mg_dl"],
        "esr_mm_hr": row["esr_mm_hr"],
        "activity_score": row["activity_score"],
        "activity_category": row["activity_category"],
        "escalation_recommendation": row["escalation_recommendation"],
        "scored_at": fmt_ts(row["scored_at"]),
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def screening_record_out(row):
    """PRD 2.4: append-only clinical document -- no updated_at, no version."""
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "screen_type": row["screen_type"],
        "result": row["result"],
        "collected_at": fmt_ts(row["collected_at"]),
        "resulted_at": fmt_ts(row["resulted_at"]),
        "recorded_by_user_id": row["recorded_by_user_id"],
        "created_at": fmt_ts(row["created_at"]),
    }


def episode_out(row):
    """PRD 3.6: monitoring_status is derived against the logical clock at read."""
    drug = db.drugs.get(row["drug_id"])
    status = calc.monitoring_status(row, drug) if drug is not None else "OVERDUE"
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "drug_id": row["drug_id"],
        "payer_plan_id": row["payer_plan_id"],
        "prior_episode_id": row["prior_episode_id"],
        "therapy_start_at": fmt_ts(row["therapy_start_at"]),
        "therapy_state": row["therapy_state"],
        "funding_state": row["funding_state"],
        "line_of_therapy": row["line_of_therapy"],
        "benefit_channel": row["benefit_channel"],
        "site_of_care": row["site_of_care"],
        "routing_frozen": row["routing_frozen"],
        "hold_reason": row["hold_reason"],
        "held_at": fmt_ts(row["held_at"]),
        "resume_not_before": fmt_ts(row["resume_not_before"]),
        "hold_count": row["hold_count"],
        "discontinuation_reason": row["discontinuation_reason"],
        "discontinued_at": fmt_ts(row["discontinued_at"]),
        "therapy_exposure_weeks": row["therapy_exposure_weeks"],
        "doses_administered": row["doses_administered"],
        "self_injection_training_status": row["self_injection_training_status"],
        "self_injection_training_attempts": row["self_injection_training_attempts"],
        "monitoring_status": status,
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def authorization_out(row):
    return {
        "id": row["id"],
        "episode_id": row["episode_id"],
        "exception_attested_by_clinician_id": row["exception_attested_by_clinician_id"],
        "benefit_channel": row["benefit_channel"],
        "status": row["status"],
        "requested_units": row["requested_units"],
        "approved_units": row["approved_units"],
        "units_reserved": row["units_reserved"],
        "units_consumed": row["units_consumed"],
        "units_remaining": row["units_remaining"],
        "formulary_exception_requested": row["formulary_exception_requested"],
        "hbv_prophylaxis_documented": row["hbv_prophylaxis_documented"],
        "appeal_round": row["appeal_round"],
        "decision_reason": row["decision_reason"],
        "determination_at": fmt_ts(row["determination_at"]),
        "valid_from": fmt_ts(row["valid_from"]),
        "valid_through": fmt_ts(row["valid_through"]),
        "submitted_at": fmt_ts(row["submitted_at"]),
        "unmet_step_therapy_classes": list(row["unmet_step_therapy_classes"]),
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def monitoring_lab_out(row):
    """PRD 2.4: append-only clinical document -- no updated_at, no version."""
    return {
        "id": row["id"],
        "episode_id": row["episode_id"],
        "panel_type": row["panel_type"],
        "collected_at": fmt_ts(row["collected_at"]),
        "alt_u_l": row["alt_u_l"],
        "wbc_k_ul": row["wbc_k_ul"],
        "neutrophil_k_ul": row["neutrophil_k_ul"],
        "alt_grade": row["alt_grade"],
        "anc_grade": row["anc_grade"],
        "abnormal_grade": row["abnormal_grade"],
        "triggers_hold": row["triggers_hold"],
        "recorded_by_user_id": row["recorded_by_user_id"],
        "created_at": fmt_ts(row["created_at"]),
    }


def appointment_out(row):
    return {
        "id": row["id"],
        "episode_id": row["episode_id"],
        "chair_id": row["chair_id"],
        "reserved_authorization_id": row["reserved_authorization_id"],
        "reserved_enrollment_id": row["reserved_enrollment_id"],
        "scheduled_start": fmt_ts(row["scheduled_start"]),
        "scheduled_end": fmt_ts(row["scheduled_end"]),
        "status": row["status"],
        "dose_sequence": row["dose_sequence"],
        "dose_cost_share_cents": row["dose_cost_share_cents"],
        "assistance_applied_cents": row["assistance_applied_cents"],
        "patient_out_of_pocket_cents": row["patient_out_of_pocket_cents"],
        "administered_at": fmt_ts(row["administered_at"]),
        "cancellation_reason": row["cancellation_reason"],
        "reversal_reason": row["reversal_reason"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }


def enrollment_out(row):
    return {
        "id": row["id"],
        "episode_id": row["episode_id"],
        "program_type": row["program_type"],
        "status": row["status"],
        "annual_benefit_cents": row["annual_benefit_cents"],
        "benefit_used_cents": row["benefit_used_cents"],
        "benefit_reserved_cents": row["benefit_reserved_cents"],
        "benefit_remaining_cents": row["benefit_remaining_cents"],
        "coverage_start": fmt_ts(row["coverage_start"]),
        "coverage_end": fmt_ts(row["coverage_end"]),
        "reauth_due_at": fmt_ts(row["reauth_due_at"]),
        "submitted_by_user_id": row["submitted_by_user_id"],
        "attested_by_user_id": row["attested_by_user_id"],
        "attested_at": fmt_ts(row["attested_at"]),
        "termination_reason": row["termination_reason"],
        "created_at": fmt_ts(row["created_at"]),
        "updated_at": fmt_ts(row["updated_at"]),
        "version": row["version"],
    }
