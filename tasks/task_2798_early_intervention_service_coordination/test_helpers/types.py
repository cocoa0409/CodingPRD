"""
TypedDict shapes for every resource and computed read the API returns.

These are documentation-grade aliases used to keep test code readable; they are
not runtime-validated. ``ContactLog`` deliberately omits ``updated_at`` and
``version`` because the contact register is append-only.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    """Audit fields carried by every mutable resource."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Child(CommonFields):
    first_name: str
    last_name: str
    date_of_birth: str
    county_code: str
    primary_language: str
    third_birthday_date: str
    active_referral_count: int


class Referral(CommonFields):
    child_id: str
    primary_referral_source: str
    referral_received_date: str
    county_code: str
    presenting_concern: str
    interpreter_required: bool
    coordinator_id: Optional[str]
    assignment_date: Optional[str]
    statutory_deadline_date: str
    status: str
    eligibility_status: str
    eligibility_determination_date: Optional[str]
    initial_ifsp_meeting_date: Optional[str]
    excluded_delay_days: int
    gross_elapsed_days: int
    net_elapsed_days: int
    initial_timeline_status: str
    case_weight_points: float
    entry_rating_social: Optional[int]
    entry_rating_knowledge: Optional[int]
    entry_rating_needs: Optional[int]
    entry_outcomes_date: Optional[str]
    exit_rating_social: Optional[int]
    exit_rating_knowledge: Optional[int]
    exit_rating_needs: Optional[int]
    services_start_date: Optional[str]
    exit_date: Optional[str]
    exit_reason: Optional[str]
    service_duration_days: int
    progress_category_social: Optional[str]
    progress_category_knowledge: Optional[str]
    progress_category_needs: Optional[str]
    last_qualifying_contact_date: Optional[str]
    monthly_contact_status: str
    service_gap_flag: bool


class ServiceCoordinator(CommonFields):
    full_name: str
    county_code: str
    language_codes: List[str]
    max_weighted_caseload_points: float
    status: str
    weighted_caseload_points: float
    active_case_count: int
    utilization_ratio: float


class CaseloadSummary(TypedDict):
    """Computed read: GET /ei/service-coordinators/{id}/caseload-summary."""

    coordinator_id: str
    active_case_count: int
    weighted_caseload_points: float
    max_weighted_caseload_points: float
    utilization_ratio: float
    caseload_posture: str
    headroom_points: float


class TimelineCompliance(TypedDict):
    """Computed read: GET /ei/referrals/{id}/timeline-compliance."""

    referral_id: str
    referral_received_date: str
    statutory_deadline_date: str
    stop_date: str
    gross_elapsed_days: int
    excluded_delay_days: int
    net_elapsed_days: int
    initial_timeline_status: str
    monthly_contact_status: str
    last_qualifying_contact_date: Optional[str]


class Assessment(CommonFields):
    referral_id: str
    assessment_type: str
    scheduled_date: str
    setting_code: str
    natural_environment_justification: Optional[str]
    domains_assessed: Optional[List[str]]
    evaluator_user_id: str
    status: str
    completion_date: Optional[str]
    family_unavailable_days: int
    eligibility_recommendation: Optional[str]


class IFSP(CommonFields):
    referral_id: str
    ifsp_type: str
    meeting_date: str
    supersedes_ifsp_id: Optional[str]
    authoring_coordinator_id: str
    natural_environment_justification: Optional[str]
    status: str
    consent_scope: Optional[str]
    consent_signed_date: Optional[str]
    consent_user_id: Optional[str]
    activated_date: Optional[str]
    service_line_count: int
    non_natural_setting_line_count: int


class IFSPService(CommonFields):
    ifsp_id: str
    service_type: str
    setting_code: str
    natural_environment_justification: Optional[str]
    frequency_per_month: int
    units_per_session: int
    unit_rate_cents: int
    planned_units_total: int
    family_fee_exempt: bool
    units_committed: int
    units_pool_remaining: int
    units_delivered: int
    makeup_owed_units: int
    declined_by_family: bool
    status: str


class Provider(CommonFields):
    agency_name: str
    qualified_service_types: List[str]
    credential_expiry_date: str
    status: str
    suspension_reason_code: Optional[str]
    suspended_date: Optional[str]
    active_authorization_count: int


class ProviderAuthorization(CommonFields):
    ifsp_service_id: str
    provider_id: str
    start_date: str
    end_date: str
    authorized_units: int
    unit_rate_cents: int
    units_consumed: int
    units_released: int
    units_remaining: int
    status: str
    revoked_date: Optional[str]
    revocation_reason_code: Optional[str]


class ServiceVisit(CommonFields):
    provider_authorization_id: str
    makeup_for_visit_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    setting_code: str
    scheduled_units: int
    actual_units: Optional[int]
    actual_start: Optional[str]
    actual_end: Optional[str]
    session_note: Optional[str]
    documented_by_user_id: Optional[str]
    visit_status: str
    billing_status: str
    family_share_cents: int
    void_reason_code: Optional[str]


class CostShare(CommonFields):
    referral_id: str
    effective_month: str
    household_size: int
    declared_annual_gross_income_cents: int
    verified_annual_gross_income_cents: Optional[int]
    insurance_use_consent: bool
    insurance_policy_id: Optional[str]
    determined_by_user_id: str
    fpl_threshold_cents: int
    fpl_percent: float
    tier_code: str
    coinsurance_rate: float
    monthly_cap_cents: int
    assessed_monthly_fee_cents: int
    insurance_offset_cents: int
    final_monthly_fee_cents: Optional[int]
    effective_coinsurance_rate: float
    total_assessed_cents: int
    family_balance_cents: int
    family_waived_cents: int
    waiver_reason_code: Optional[str]
    month_accrued_cents: int
    status: str
    verification_date: Optional[str]


class ContactLog(TypedDict):
    """Append-only register: carries only ``id`` and ``created_at``."""

    id: str
    created_at: str
    referral_id: str
    contact_date: str
    contact_month: str
    contact_method: str
    contact_type: str
    summary: str
    qualifies_for_monthly_requirement: bool


class TransitionPlan(CommonFields):
    ifsp_id: str
    target_conference_date: str
    conference_held_date: Optional[str]
    transition_steps_count: int
    lea_code: Optional[str]
    notification_date: Optional[str]
    family_opt_out: bool
    opt_out_signed_date: Optional[str]
    notification_lead_days: Optional[int]
    notification_compliance: Optional[str]
    status: str
