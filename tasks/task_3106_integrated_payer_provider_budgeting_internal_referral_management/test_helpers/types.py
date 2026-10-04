"""Domain types for the integrated payer-provider budgeting API.

Entity TypedDicts carry the fields the PRD declares for each resource. All
fifteen resources are declared with common fields present, so every TypedDict
carries ``id``, ``created_at``, ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum value sets ─────────────────────────

class RegionPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PlanProduct(str, Enum):
    COMMERCIAL_HMO = "COMMERCIAL_HMO"
    MEDICARE_ADVANTAGE = "MEDICARE_ADVANTAGE"
    MEDICAID_MANAGED = "MEDICAID_MANAGED"
    DUAL_ELIGIBLE = "DUAL_ELIGIBLE"


class BenefitTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ReferralType(str, Enum):
    INTERNAL = "INTERNAL"
    OUTSIDE_NETWORK = "OUTSIDE_NETWORK"


class ReferralStatus(str, Enum):
    PENDING_TRIAGE = "PENDING_TRIAGE"
    AUTHORIZED = "AUTHORIZED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    EXPIRED = "EXPIRED"
    HELD = "HELD"


class AppointmentType(str, Enum):
    ROUTINE = "ROUTINE"
    SPECIALTY = "SPECIALTY"
    URGENT = "URGENT"
    FOLLOW_UP = "FOLLOW_UP"


class FulfillmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AccessStatus(str, Enum):
    WITHIN_ACCESS_TARGET = "WITHIN_ACCESS_TARGET"
    BREACHED_ACCESS_TARGET = "BREACHED_ACCESS_TARGET"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PENDED = "PENDED"
    ADJUDICATED = "ADJUDICATED"
    PAID = "PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"


class BudgetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class CapacityPlanStatus(str, Enum):
    PLANNING = "PLANNING"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACTIVE = "ACTIVE"
    ADJUSTED = "ADJUSTED"
    FROZEN = "FROZEN"


class ReferentialIntegrationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    BOUND = "BOUND"
    ENROLLED = "ENROLLED"
    CONTRACTED = "CONTRACTED"
    TERMINATED = "TERMINATED"


class QualityMetricStatus(str, Enum):
    MEASURING = "MEASURING"
    FINALIZED = "FINALIZED"
    REMEDIATION = "REMEDIATION"
    REOPENED = "REOPENED"


class AlertStatus(str, Enum):
    RAISED = "RAISED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class UserRole(str, Enum):
    REGIONAL_FINANCE_OFFICER = "RegionalFinanceOfficer"
    UTILIZATION_REVIEWER = "UtilizationReviewer"
    ACCESS_SCHEDULER = "AccessScheduler"
    QUALITY_REVIEW_BOARD = "QualityReviewBoard"
    BUDGET_APPROPRIATIONS_COMMITTEE = "BudgetAppropriationsCommittee"
    CARE_TEAM_MEMBER = "CareTeamMember"
    PROVIDER = "Provider"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts (all carry common fields) ──────

class Region(TypedDict, total=False):
    id: str
    name: str
    state_codes: List[str]
    posture: str
    margin_target_pct: float
    capitation_index: float
    premium_revenue_cents: int
    employed_delivery_cost_cents: int
    outside_services_spend_cents: int
    operating_margin_cents: int
    computed_margin_cents: int
    referential_integration_credit_cents: int
    open_alert_count: int
    staffing_and_facility_cents: int
    capacity_budget_appointments: int
    capacity_committed_appointments: int
    access_breach_pct: float
    quality_composite_score: float
    member_count: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    region_id: str
    member_ref: str
    attributed_provider_id: str
    plan_product: str
    benefit_tier: str
    risk_score: float
    coverage_effective_date: str
    capitation_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CareSite(TypedDict, total=False):
    id: str
    region_id: str
    site_name: str
    site_type: str
    licensed_beds: int
    staffing_fte_budget: float
    staffing_fte_filled: float
    facility_investment_budget_cents: int
    facility_investment_spent_cents: int
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict, total=False):
    id: str
    care_site_id: str
    region_id: str
    specialty: str
    appointment_slots_budgeted: int
    appointment_slots_committed: int
    wait_threshold_days: int
    accepting_internal_referrals: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    care_site_id: str
    region_id: str
    provider_name: str
    specialty: str
    compensation_model: str
    base_component_cents: int
    panel_size_target: int
    panel_size_assigned: int
    quality_score: float
    panel_capitation_component_cents: int
    quality_bonus_cents: int
    volume_component_cents: int
    comp_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NetworkService(TypedDict, total=False):
    id: str
    region_id: str
    service_code: str
    service_name: str
    availability_status: str
    available_provider_count: int
    capacity_note: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    department_id: str
    provider_id: str
    member_id: str
    referral_id: str
    appointment_type: str
    start_utc: str
    duration_minutes: int
    wait_days: float
    fulfillment_status: str
    access_status: str
    hold_status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    member_id: str
    requesting_department_id: str
    target_department_id: str
    service_code: str
    referral_type: str
    external_contract_count: int
    authorization_exception: bool
    exception_reason: str
    appeal_rounds: int
    effective_decision_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OutsideServiceClaim(TypedDict, total=False):
    id: str
    member_id: str
    region_id: str
    vendor_name: str
    service_code: str
    claim_type: str
    emergency_flag: bool
    billed_amount_cents: int
    provisional_liability_cents: int
    final_liability_cents: int
    submitted_at: str
    adjudicated_at: str
    appeal_rounds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RegionalBudget(TypedDict, total=False):
    id: str
    region_id: str
    period: str
    premium_revenue_cents: int
    employed_delivery_cost_cents: int
    staffing_budget_cents: int
    outside_services_budget_cents: int
    outside_services_committed_cents: int
    facility_investment_cents: int
    division_deductible_cents: int
    division_deductible_original_cents: int
    system_deductible_cents: int
    ort_contract_rate: float
    division_liability_cents: int
    net_liability_cents: int
    operating_margin_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityPlan(TypedDict, total=False):
    id: str
    region_id: str
    department_id: str
    period: str
    budgeted_slots: int
    committed_slots: int
    supply_shortfall_slots: int
    panel_target: int
    recalculation_epoch: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MemberTransfer(TypedDict, total=False):
    id: str
    member_id: str
    from_region_id: str
    to_region_id: str
    effective_utc: str
    benefit_difference_cents: int
    network_difference_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityMetric(TypedDict, total=False):
    id: str
    region_id: str
    metric_code: str
    period: str
    target_value: float
    measured_value: float
    weighted_component_score: float
    accountable_provider_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReferentialIntegration(TypedDict, total=False):
    id: str
    region_id: str
    integration_type: str
    risk_sharing_model: str
    bound_effective_date: str
    cost_reporting_basis_cents: int
    shared_savings_rate: float
    per_diem_days: int
    per_diem_rate_cents: int
    per_diem_cap_cents: int
    interim_claim_count: int
    settlement_account_cents: int
    settlement_posted_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AlertNotification(TypedDict, total=False):
    id: str
    region_id: str
    alert_type: str
    severity: str
    payload_ref_type: str
    payload_ref_id: str
    raised_at: str
    status: str
    created_at: str
    updated_at: str
    version: int