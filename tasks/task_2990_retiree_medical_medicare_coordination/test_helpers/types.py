"""TypedDict shapes for the nine PRD entities.

Every entity carries the four common fields id, created_at, updated_at and
version (PRD 2.4), so each shape inherits from CommonFields. total=False is
used throughout because the tests only assert the fields a given rule pins.
"""
from typing import Any, Dict, List, Optional, TypedDict

Json = Dict[str, Any]


class CommonFields(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int


class PlanYear(CommonFields, total=False):
    year: int
    status: str
    open_enrollment_start: str
    open_enrollment_end: str
    coverage_start: str
    hra_credit_pre_medicare_cents: int
    hra_credit_medicare_cents: int
    carryover_cap_pct: float
    premium_grace_period_days: int
    reinstatement_window_days: int
    notice_lead_days: int
    discount_rate_bps: int
    assumed_annual_subsidy_cents: int
    assumed_payment_years: int
    liability_method: Optional[str]
    measured_retiree_count: int
    epbo_total_cents: int
    apbo_total_cents: int
    service_cost_total_cents: int
    liability_valued_at: Optional[str]


class Retiree(CommonFields, total=False):
    full_name: str
    birth_date: str
    hire_date: str
    retirement_date: str
    credited_service_months: int
    eligibility_status: str
    medicare_status: str
    medicare_part_b_effective_date: Optional[str]
    other_group_coverage_employer_size: Optional[int]
    active_employment_flag: bool
    esrd_flag: bool
    esrd_entitlement_date: Optional[str]
    disability_entitlement_flag: bool
    grandfathered_group: str
    eligibility_points: int
    determination_sequence: int


class PlanOption(CommonFields, total=False):
    plan_year_id: str
    plan_code: str
    coverage_class: str
    monthly_premium_cents: int
    requires_medicare_part_b: bool
    allowed_grandfather_groups: List[str]
    subsidy_vehicle: str
    rx_gross_value_bps: int
    rx_net_value_bps: int
    status: str
    subsidy_certification_status: str
    gross_test_passed: bool
    net_test_passed: bool
    equivalence_margin_bps: Optional[int]
    attested_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    enrolled_count: int
    pending_change_type: Optional[str]
    pending_change_effective_date: Optional[str]
    pending_new_monthly_premium_cents: Optional[int]
    change_notice_issued_at: Optional[str]


class EligibilityDetermination(CommonFields, total=False):
    retiree_id: str
    plan_year_id: str
    rule_set_code: str
    grandfathered_group: str
    age_years_at_retirement: int
    service_years: int
    points: int
    outcome: str
    status: str
    created_by_user_id: str
    certified_by_user_id: Optional[str]
    appeal_reason: Optional[str]
    appeal_decided_by_user_id: Optional[str]
    appeal_decision: Optional[str]
    certified_at: Optional[str]


class ElectionEvent(CommonFields, total=False):
    retiree_id: str
    plan_year_id: str
    requested_plan_option_id: str
    event_type: str
    event_date: str
    submitted_at: str
    window_deadline: str
    coverage_effective_date: str
    status: str
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    denial_reason_code: Optional[str]
    resulting_enrollment_id: Optional[str]


class Enrollment(CommonFields, total=False):
    retiree_id: str
    plan_year_id: str
    plan_option_id: str
    election_event_id: str
    coverage_status: str
    billing_status: str
    coverage_effective_date: str
    coverage_end_date: Optional[str]
    payer_order: str
    msp_basis_code: str
    monthly_retiree_premium_cents: int
    consecutive_unpaid_periods: int
    delinquency_first_unpaid_period_start: Optional[str]
    lapse_date: Optional[str]
    reinstatement_deadline: Optional[str]
    reinstatement_count: int
    termination_reason: Optional[str]


class HraAccount(CommonFields, total=False):
    retiree_id: str
    plan_year_id: str
    prior_year_account_id: Optional[str]
    covered_months: int
    annual_credit_cents: int
    carryover_in_cents: int
    funded_cents: int
    available_balance_cents: int
    pending_hold_cents: int
    substantiated_paid_cents: int
    premium_offset_cents: int
    forfeited_cents: int
    status: str
    closed_at: Optional[str]


class ReimbursementClaim(CommonFields, total=False):
    hra_account_id: str
    expense_category: str
    service_date: str
    submitted_cents: int
    documentation_reference: Optional[str]
    provisional_eligible_cents: int
    eligible_cents: Optional[int]
    status: str
    substantiation_resubmit_count: int
    denial_reason_code: Optional[str]
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    paid_at: Optional[str]


class PremiumInvoice(CommonFields, total=False):
    enrollment_id: str
    billing_period_start: str
    billing_period_end: str
    base_premium_cents: int
    admin_fee_cents: int
    gross_premium_cents: int
    employer_subsidy_bps: int
    employer_subsidy_cents: int
    retiree_share_cents: int
    hra_applied_cents: int
    net_due_cents: int
    paid_cents: int
    due_date: str
    past_due_at: str
    status: str


class DailyRunResult(TypedDict, total=False):
    processed_invoice_count: int
    activated_enrollment_count: int
    suspended_enrollment_count: int
    lapsed_enrollment_count: int
    applied_plan_change_count: int
    recomputed_msp_count: int


class ClockState(TypedDict, total=False):
    current_utc: str


__all__ = [
    "Json",
    "CommonFields",
    "PlanYear",
    "Retiree",
    "PlanOption",
    "EligibilityDetermination",
    "ElectionEvent",
    "Enrollment",
    "HraAccount",
    "ReimbursementClaim",
    "PremiumInvoice",
    "DailyRunResult",
    "ClockState",
]
