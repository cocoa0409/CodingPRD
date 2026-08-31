"""Domain types for the Workforce Reduction & WARN Act Compliance API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    RESTRUCTURING_LEAD = "RestructuringLead"
    EMPLOYMENT_COUNSEL = "EmploymentCounsel"
    BENEFITS_ADMINISTRATOR = "BenefitsAdministrator"
    SEPARATING_EMPLOYEE = "SeparatingEmployee"
    SYSTEM_ADMIN = "SystemAdmin"


class CriteriaStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"


class ApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_LEGAL_REVIEW = "IN_LEGAL_REVIEW"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"


class WarnStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    THRESHOLD_PENDING = "THRESHOLD_PENDING"
    NOTICES_ISSUED = "NOTICES_ISSUED"
    NOTICE_PERIOD_SATISFIED = "NOTICE_PERIOD_SATISFIED"


class WarnTriggerStatus(str, Enum):
    NONE = "NONE"
    MASS_LAYOFF = "MASS_LAYOFF"
    PLANT_CLOSING = "PLANT_CLOSING"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING_SEPARATION = "PENDING_SEPARATION"
    SEPARATED = "SEPARATED"


class BenefitContinuationStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class OutplacementTier(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class DemographicCode(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"


class SelectionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SELECTED = "SELECTED"
    EXEMPTED = "EXEMPTED"
    RESCINDED = "RESCINDED"
    SEPARATED = "SEPARATED"


class NoticeDeliveryStatus(str, Enum):
    NOT_DELIVERED = "NOT_DELIVERED"
    DELIVERED = "DELIVERED"


class Jurisdiction(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"


class AnalysisStatus(str, Enum):
    COMPUTED = "COMPUTED"
    FLAGGED = "FLAGGED"
    CLEARED = "CLEARED"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"


class AnalysisMethod(str, Enum):
    IMPACT_RATIO = "IMPACT_RATIO"
    STANDARD_DEVIATION = "STANDARD_DEVIATION"


class DisclosureStatus(str, Enum):
    ATTACHED = "ATTACHED"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOID = "VOID"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"
    EFFECTIVE = "EFFECTIVE"
    EXPIRED = "EXPIRED"


class OfferVariant(str, Enum):
    STANDARD = "STANDARD"
    ENHANCED_RELEASE = "ENHANCED_RELEASE"


class RestrictionStatus(str, Enum):
    RESTRICTED = "RESTRICTED"
    WAIVED = "WAIVED"
    RELEASED = "RELEASED"


class TriggerType(str, Enum):
    NONE = "NONE"
    MASS_LAYOFF = "MASS_LAYOFF"
    PLANT_CLOSING = "PLANT_CLOSING"


class ScriptCode(str, Enum):
    MANAGER_SCRIPT_STANDARD = "MANAGER_SCRIPT_STANDARD"
    MANAGER_SCRIPT_REMOTE = "MANAGER_SCRIPT_REMOTE"
    MANAGER_SCRIPT_UNION = "MANAGER_SCRIPT_UNION"


class Decision(str, Enum):
    SELECT = "SELECT"
    EXEMPT = "EXEMPT"


class LegalDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"


# --- Entity shapes -------------------------------------------------------
# Every resource carries id + created_at.  All of them except WarnRule also
# carry updated_at + version.


class ReductionPlan(TypedDict):
    id: str
    name: str
    decisional_unit_name: str
    selection_criteria: List[dict]
    criteria_status: str
    approval_status: str
    warn_status: str
    severance_budget_cents: int
    severance_reserve_cents: int
    benefit_liability_cents: int
    selected_count: int
    pool_count: int
    earliest_separation_date: Optional[str]
    owbpa_required: bool
    owbpa_consideration_days: int
    required_notice_days: int
    notice_deadline_utc: Optional[str]
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    legal_return_count: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    name: str
    state_code: str
    is_single_site: bool
    roster_count: int
    active_headcount: int
    pending_separation_count: int
    separated_count: int
    federal_loss_count: int
    state_loss_count: int
    warn_trigger_status: str
    required_notice_days: int
    window_start_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    site_id: str
    full_name: str
    job_title: str
    birth_date: str
    hire_date: str
    annual_base_cents: int
    weekly_hours: float
    demographic_code: str
    monthly_premium_cents: int
    employment_status: str
    is_part_time: bool
    separation_date: Optional[str]
    age_at_separation: Optional[int]
    years_of_service: Optional[int]
    release_signed: bool
    benefit_continuation_status: str
    benefit_subsidy_months: int
    benefit_subsidy_cents: int
    outplacement_tier: str
    created_at: str
    updated_at: str
    version: int


class Selection(TypedDict):
    id: str
    plan_id: str
    employee_id: str
    proposed_separation_date: str
    criterion_scores: List[dict]
    composite_score: float
    status: str
    exemption_reason: Optional[str]
    rescind_reason: Optional[str]
    notice_status: str
    notice_script_code: Optional[str]
    notice_delivered_utc: Optional[str]
    notice_days_before_separation: Optional[int]
    short_notice_acknowledged: bool
    created_at: str
    updated_at: str
    version: int


# WarnRule is immutable configuration: id + created_at only, no updated_at
# and no version.
class WarnRule(TypedDict):
    id: str
    jurisdiction: str
    state_code: str
    rule_code: str
    min_loss_count: int
    min_percent: float
    absolute_count: int
    notice_days: int
    window_days: int
    counts_part_time: bool
    min_service_days: int
    required_content_codes: List[str]
    created_at: str


class AdverseImpactAnalysis(TypedDict):
    id: str
    plan_id: str
    method: str
    status: str
    pool_count: int
    selected_count: int
    focal_class_code: Optional[str]
    focal_pool_count: int
    focal_selected_count: int
    focal_rate: float
    reference_rate: float
    impact_ratio: Optional[float]
    standard_deviations: Optional[float]
    shortfall_count: int
    small_sample_suppressed: bool
    justification: Optional[str]
    cleared_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OwbpaDisclosure(TypedDict):
    id: str
    plan_id: str
    decisional_unit_name: str
    eligible_count: int
    selected_count: int
    non_selected_count: int
    min_age: Optional[int]
    max_age: Optional[int]
    age_bands: List[dict]
    consideration_days: int
    snapshot_selected_count: int
    snapshot_pool_count: int
    status: str
    generated_utc: str
    created_at: str
    updated_at: str
    version: int


class WarnNotice(TypedDict):
    id: str
    plan_id: str
    site_id: str
    jurisdiction: str
    content_codes: List[str]
    applied_rule_code: str
    employment_loss_count: int
    workforce_count: int
    loss_percent: float
    threshold_met: bool
    trigger_type: str
    required_notice_days: int
    window_start_date: Optional[str]
    window_end_date: Optional[str]
    notice_deadline_utc: Optional[str]
    status: str
    issued_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeveranceOffer(TypedDict):
    id: str
    selection_id: str
    plan_id: str
    owbpa_disclosure_id: Optional[str]
    variant: str
    weekly_rate_cents: int
    weeks_awarded: float
    base_severance_cents: int
    notice_shortfall_days: int
    notice_pay_offset_cents: int
    benefit_subsidy_months: int
    benefit_subsidy_cents: int
    outplacement_fee_cents: int
    total_separation_cost_cents: int
    consideration_days_applied: int
    status: str
    issue_count: int
    issued_utc: Optional[str]
    signed_utc: Optional[str]
    revoked_utc: Optional[str]
    consideration_deadline_utc: Optional[str]
    revocation_deadline_utc: Optional[str]
    blocking_window_end_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PositionRestriction(TypedDict):
    id: str
    employee_id: str
    site_id: str
    job_title: str
    restriction_status: str
    restricted_until_utc: str
    waiver_reason: Optional[str]
    waived_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
