"""Domain types: entity TypedDicts, status enums, role enum.

Entities that carry the full identity quartet (`id`, `created_at`, `updated_at`,
`version`) are declared with those four fields. Append-mostly rows — an
appointment line and a revenue ledger entry — carry only `id` and `created_at`.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    MANAGER = "Manager"
    CUSTOMER_SERVICE = "CustomerService"
    PLATFORM_ADMIN = "PlatformAdmin"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class CampaignChannel(str, Enum):
    SEARCH = "SEARCH"
    YARD_SIGN = "YARD_SIGN"
    REFERRAL = "REFERRAL"
    DIRECT_MAIL = "DIRECT_MAIL"
    ORGANIC = "ORGANIC"


class TaskCategory(str, Enum):
    HVAC = "HVAC"
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    APPLIANCE = "APPLIANCE"
    GENERAL = "GENERAL"


class TechnicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_SHIFT = "ON_SHIFT"
    ON_JOB = "ON_JOB"
    OFF_SHIFT = "OFF_SHIFT"


class PerformanceStatus(str, Enum):
    CLEAR = "CLEAR"
    COACHING = "COACHING"
    PROBATION = "PROBATION"


class PerformanceGrade(str, Enum):
    DOES_NOT_MEET = "DOES_NOT_MEET"
    MEETS = "MEETS"
    EXCEEDS = "EXCEEDS"
    OUTSTANDING = "OUTSTANDING"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DispatchStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    DISPATCHED = "DISPATCHED"
    IN_SERVICE = "IN_SERVICE"
    RELEASED = "RELEASED"


class PricingStatus(str, Enum):
    NOT_QUOTED = "NOT_QUOTED"
    AUTO_QUOTED = "AUTO_QUOTED"
    OVERRIDE_PENDING = "OVERRIDE_PENDING"
    QUOTE_APPROVED = "QUOTE_APPROVED"
    QUOTE_REJECTED = "QUOTE_REJECTED"


class LineStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SOLD = "SOLD"
    DECLINED = "DECLINED"


class OptionTier(str, Enum):
    GOOD = "GOOD"
    BETTER = "BETTER"
    BEST = "BEST"


class OverrideStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AgreementStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class CoachingStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    COACHING_ASSIGNED = "COACHING_ASSIGNED"
    REVIEWED = "REVIEWED"


class LedgerEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    REVERSAL = "REVERSAL"


# ---------------------------------------------------------------- TypedDicts
class Branch(TypedDict, total=False):
    id: str
    name: str
    postal_code: str
    daily_dispatch_capacity_hours: float
    capacity_consumed_hours: float
    membership_count_active: int
    created_at: str
    updated_at: str
    version: int


class MembershipPlan(TypedDict, total=False):
    id: str
    name: str
    annual_price_cents: int
    included_service_visit_count: int
    maintenance_visit_interval_days: int
    included_labor_discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    name: str
    channel: str
    spend_cents: int
    attributed_job_count: int
    attributed_revenue_cents: int
    conversion_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int


class PricebookTask(TypedDict, total=False):
    id: str
    code: str
    revision: int
    category: str
    display_name: str
    required_skill_code: str
    estimated_hours: float
    flat_rate_cents: int
    status: str
    published_at_utc: Optional[str]
    options: List[dict]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    home_branch_id: str
    name: str
    postal_code: str
    skill_codes: List[str]
    shift_segments: List[dict]
    daily_capacity_hours: float
    status: str
    performance_status: str
    sales_coaching_strike_count: int
    scheduled_hours: float
    dispatched_hours: float
    technician_revenue_ledger_cents: int
    revenue_window_cents: int
    performance_grade: str
    created_at: str
    updated_at: str
    version: int


# Append-mostly: carries ONLY id and created_at — no updated_at, no version.
class RevenueLedgerEntry(TypedDict, total=False):
    id: str
    technician_id: str
    appointment_id: str
    entry_type: str
    amount_cents: int
    running_total_cents: int
    recorded_at_utc: str
    created_at: str


class Appointment(TypedDict, total=False):
    id: str
    branch_id: str
    technician_id: Optional[str]
    membership_agreement_id: Optional[str]
    membership_visit_sequence_number: Optional[int]
    campaign_id: Optional[str]
    call_record_id: Optional[str]
    customer_name: str
    postal_code: str
    window_start_utc: str
    window_end_utc: str
    estimated_hours: float
    labor_base_cents: int
    quoted_price_cents: int
    authorization_required: bool
    current_pricebook_version_id: Optional[str]
    repriced_at: Optional[str]
    load_units_trace: List[int]
    sold_price_cents: int
    pricing_status: str
    status: str
    dispatch_status: str
    created_at: str
    updated_at: str
    version: int


# Append-mostly: carries ONLY id and created_at — no updated_at, no version.
class AppointmentLine(TypedDict, total=False):
    id: str
    appointment_id: str
    pricebook_task_id: str
    option_tier: Optional[str]
    status: str
    flat_rate_cents: int
    sold_price_cents: int
    created_at: str


class PricebookOverrideRequest(TypedDict, total=False):
    id: str
    appointment_id: str
    original_quote_cents: int
    requested_price_cents: int
    max_approved_price_cents: int
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MembershipAgreement(TypedDict, total=False):
    id: str
    membership_plan_id: str
    branch_id: str
    homeowner_name: str
    homeowner_postal_code: str
    status: str
    term_months: int
    agreement_start_utc: Optional[str]
    annual_price_cents: int
    collected_amount_cents: int
    revenue_recognized_cents: int
    unearned_revenue_balance_cents: int
    visits_fulfilled_count: int
    created_at: str
    updated_at: str
    version: int


class MembershipVisit(TypedDict, total=False):
    id: str
    membership_agreement_id: str
    branch_id: str
    sequence_number: int
    scheduled_date: str
    status: str
    completed_appointment_id: Optional[str]
    completed_at_utc: Optional[str]
    deferred_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class CallRecord(TypedDict, total=False):
    id: str
    campaign_id: str
    cs_user_id: str
    started_at_utc: str
    duration_seconds: int
    recording_uri: str
    coaching_status: str
    attributed_appointment_id: Optional[str]
    coached_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncentiveStatement(TypedDict, total=False):
    gross_component_cents: int
    clamped_component_cents: int
    charge_cents: int
    incentive_cents: int


class PerformanceReview(TypedDict, total=False):
    window_start_utc: str
    window_end_utc: str
    window_revenue_cents: int
    grade: str


# Convenience alias used by callers that want a plain dict payload.
Payload = dict[str, Any]


def as_dict(entity: Any) -> dict:
    """Return a plain dict view of a response entity."""
    return entity if isinstance(entity, dict) else dict(entity)