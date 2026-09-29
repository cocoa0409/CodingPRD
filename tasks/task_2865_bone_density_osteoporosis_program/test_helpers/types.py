"""Typed shapes for the resources the API returns.

``PayerPolicy``, ``QcRun``, ``SiteMeasurement``, ``AdherenceRefill`` and
``PositioningReview`` are append-only records: per the specification they carry
only ``id`` and ``created_at`` alongside their own fields, so ``updated_at``
and ``version`` are deliberately absent from those shapes.
"""

from typing import Any, Dict, List, Optional, TypedDict

# ── Common field groups ─────────────────────────────────────────────────────


class Timestamped(TypedDict):
    """Identity plus creation stamp — carried by every resource."""

    id: str
    created_at: str


class Versioned(Timestamped):
    """Identity, creation stamp, mutation stamp and optimistic version."""

    updated_at: str
    version: int


# ── Program foundations ─────────────────────────────────────────────────────


class PayerPolicy(Timestamped, total=False):
    payer_code: str
    name: str
    baseline_screening_min_interval_months: int
    high_risk_min_interval_months: int
    treatment_monitoring_min_interval_months: int
    vfa_covered: bool
    vfa_requires_height_loss_cm: float
    repeat_scan_grace_days: int
    max_lifetime_screening_scans: int
    appeal_allowed: bool


class Patient(Versioned, total=False):
    mrn: str
    primary_payer_policy_id: str
    birth_date: str
    sex: str
    postmenopausal: bool
    baseline_height_cm: float
    open_scheduled_order_count: int
    lifetime_screening_scan_count: int
    baseline_report_id: Optional[str]
    last_finalized_report_id: Optional[str]
    current_screening_interval_months: Optional[int]
    next_eligible_scan_date: Optional[str]


class RiskFactorProfile(Versioned, total=False):
    patient_id: str
    height_cm: float
    weight_kg: float
    prior_fragility_fracture: bool
    parental_hip_fracture: bool
    current_smoker: bool
    glucocorticoid_use: bool
    rheumatoid_arthritis: bool
    secondary_osteoporosis: bool
    alcohol_units_per_day: float
    bmi: float
    height_loss_cm: float
    clinical_risk_factor_count: int
    recorded_at_utc: str
    status: str


# ── Equipment ───────────────────────────────────────────────────────────────


class Densitometer(Versioned, total=False):
    serial_number: str
    manufacturer: str
    model: str
    site_code: str
    phantom_baseline_bmd_g_cm2: float
    phantom_baseline_sd_g_cm2: float
    appointment_buffer_minutes: int
    daily_scan_capacity: int
    status: str
    calibration_generation: int
    cross_cal_factor: float
    consecutive_qc_pass_count: int
    rms_sd_g_cm2: Optional[float]
    precision_degrees_of_freedom: Optional[int]
    lsc_g_cm2: Optional[float]
    precision_technologist_user_id: Optional[str]
    precision_certified_at: Optional[str]
    last_qc_result: Optional[str]
    last_qc_run_at: Optional[str]
    qc_hold_started_at: Optional[str]
    qc_hold_reason_code: Optional[str]


class QcRun(Timestamped, total=False):
    densitometer_id: str
    calibration_event_id: Optional[str]
    purpose: str
    phantom_bmd_g_cm2: float
    scan_mode: str
    deviation_g_cm2: float
    deviation_sd_units: float
    result: str
    shift_detected: bool
    performed_by_user_id: str
    performed_at_utc: str


class CalibrationEvent(Versioned, total=False):
    densitometer_id: str
    change_type: str
    change_note: Optional[str]
    status: str
    required_phantom_runs: int
    baseline_run_count: int
    new_run_count: int
    baseline_mean_bmd_g_cm2: Optional[float]
    new_mean_bmd_g_cm2: Optional[float]
    percent_difference: Optional[float]
    proposed_cross_cal_factor: Optional[float]
    outcome_code: Optional[str]
    closed_at_utc: Optional[str]
    adjudicated_at_utc: Optional[str]


# ── Scheduling ──────────────────────────────────────────────────────────────


class ScanOrder(Versioned, total=False):
    patient_id: str
    indication: str
    requested_sites: List[str]
    requested_scan_date: str
    vfa_requested: bool
    status: str
    required_densitometer_id: Optional[str]
    reschedule_required: bool
    frequency_eligibility: str
    earliest_allowed_date: Optional[str]
    payer_floor_months: int
    denial_reason_code: Optional[str]
    ordered_by_user_id: str
    ordered_at_utc: str


class ScanAppointment(Versioned, total=False):
    scan_order_id: str
    densitometer_id: str
    start_utc: str
    end_utc: str
    scheduled_duration_minutes: int
    status: str
    slot_index: Optional[int]
    cancellation_reason_code: Optional[str]
    cancelled_at_utc: Optional[str]


# ── Acquisition ─────────────────────────────────────────────────────────────


class ScanSession(Versioned, total=False):
    scan_appointment_id: str
    patient_id: str
    densitometer_id: str
    scan_mode: str
    technologist_user_id: str
    acquisition_status: str
    review_status: str
    repeat_count: int
    calibration_generation: int
    applied_lsc_g_cm2: float
    applied_cross_cal_factor: float
    prior_session_id: Optional[str]
    prior_comparison_status: str
    measured_site_count: int
    submitted_at_utc: Optional[str]
    lowest_t_score: Optional[float]
    lowest_t_score_site: Optional[str]
    lowest_z_score: Optional[float]
    vfa_performed: bool
    vfa_eligibility_code: Optional[str]
    vfa_max_genant_grade: Optional[int]
    vfa_fracture_count: Optional[int]
    genant_grades: Optional[List[int]]


class SiteMeasurement(Timestamped, total=False):
    scan_session_id: str
    site_code: str
    bmd_g_cm2: float
    area_cm2: float
    bmc_g: float
    reference_mean_bmd_g_cm2: float
    reference_sd_g_cm2: float
    age_matched_mean_bmd_g_cm2: float
    age_matched_sd_g_cm2: float
    included_vertebrae: Optional[List[str]]
    valid_vertebral_count: int
    site_usable_for_diagnosis: bool
    t_score: float
    z_score: float
    superseded: bool


class PositioningReview(Timestamped, total=False):
    scan_session_id: str
    defect_codes: List[str]
    reviewer_note: Optional[str]
    severity_score: int
    repeat_criterion_met: bool
    outcome: str
    reviewer_user_id: str
    reviewed_at_utc: str


# ── Interpretation ──────────────────────────────────────────────────────────


class FraxAssessment(Versioned, total=False):
    patient_id: str
    risk_factor_profile_id: str
    scan_session_id: Optional[str]
    variant: str
    age_years: int
    age_points: float
    sex_points: float
    bmi_used: float
    bmi_points: float
    clinical_risk_points: float
    bmd_points: float
    raw_score: float
    major_osteoporotic_10yr_pct: float
    hip_fracture_10yr_pct: float
    treatment_threshold_met: bool
    threshold_basis: str
    assessed_by_user_id: str
    assessed_at_utc: str


class DiagnosticReport(Versioned, total=False):
    scan_session_id: str
    frax_assessment_id: Optional[str]
    non_comparability_note: Optional[str]
    vfa_narrative: Optional[str]
    status: str
    amends_report_id: Optional[str]
    amendment_reason: Optional[str]
    patient_age_years: int
    classification_basis: str
    diagnostic_category: str
    lsc_interpretation: str
    lsc_site_code: Optional[str]
    current_bmd_used_g_cm2: Optional[float]
    prior_bmd_used_g_cm2: Optional[float]
    bmd_change_g_cm2: Optional[float]
    bmd_change_pct: Optional[float]
    clinical_interval_months: int
    payer_floor_months: int
    recommended_interval_months: int
    recommended_action: str
    missing_element_codes: List[str]
    required_elements_complete: bool
    finalized_at_utc: Optional[str]
    finalized_by_user_id: Optional[str]


# ── Therapy ─────────────────────────────────────────────────────────────────


class TreatmentPlan(Versioned, total=False):
    patient_id: str
    initiating_report_id: str
    drug_class: str
    start_date: str
    adherence_source_policy: str
    status: str
    followup_interval_months: int
    next_followup_due_date: str
    last_review_date: Optional[str]
    adherence_review_count: int
    consecutive_nonadherent_reviews: int
    adherence_status: str
    adherence_window_days: Optional[int]
    covered_days_supplied: Optional[float]
    medication_possession_ratio: Optional[float]
    denosumab_gap_days: Optional[int]
    cumulative_therapy_months: Optional[int]
    holiday_eligible: bool
    discontinuation_reason_code: Optional[str]


class AdherenceRefill(Timestamped, total=False):
    treatment_plan_id: str
    dispensed_date: str
    days_supplied: int
    source: str
    source_weight: float
    coverage_end_date: str
    recorded_by_user_id: str


JsonDict = Dict[str, Any]
