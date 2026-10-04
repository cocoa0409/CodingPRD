"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class TargetStatus(str, Enum):
    SCREENING = "SCREENING"
    VALUATION = "VALUATION"
    MUNICIPAL_REVIEW = "MUNICIPAL_REVIEW"
    REGULATORY_REVIEW = "REGULATORY_REVIEW"
    CLOSING = "CLOSING"
    INTEGRATED = "INTEGRATED"
    REJECTED = "REJECTED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class CapitalItemStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    SPLIT = "SPLIT"
    CANCELLED = "CANCELLED"


class ValuationCaseStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class ValuationEntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SELECTED = "SELECTED"
    NOT_SELECTED = "NOT_SELECTED"


class CouncilEventKind(str, Enum):
    PUBLIC_HEARING = "PUBLIC_HEARING"
    COUNCIL_VOTE = "COUNCIL_VOTE"
    REFERENDUM = "REFERENDUM"


class CouncilEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ApplicationStatus(str, Enum):
    PREPARED = "PREPARED"
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REMANDED = "REMANDED"


class AccountStatus(str, Enum):
    LEGACY = "LEGACY"
    MIGRATED = "MIGRATED"
    CONSOLIDATED = "CONSOLIDATED"
    ORPHANED = "ORPHANED"


class TransitionItemCategory(str, Enum):
    BILLING_RECORDS = "BILLING_RECORDS"
    DEPOSITS = "DEPOSITS"
    SERVICE_AGREEMENTS = "SERVICE_AGREEMENTS"
    METER_READS = "METER_READS"


class TransitionItemStatus(str, Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    BLOCKED = "BLOCKED"


class EmployeeStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    ASSUMED = "ASSUMED"
    WITHDRAWN = "WITHDRAWN"


class TariffCaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"


class UserRole(str, Enum):
    AcquisitionAnalyst = "AcquisitionAnalyst"
    EngineeringReviewer = "EngineeringReviewer"
    Appraiser = "Appraiser"
    MunicipalClerk = "MunicipalClerk"
    RegulatoryOfficer = "RegulatoryOfficer"
    Commissioner = "Commissioner"
    TransitionManager = "TransitionManager"
    HRDirector = "HRDirector"
    SystemAdmin = "SystemAdmin"


class AcquisitionTarget(TypedDict, total=False):
    id: str
    system_name: str
    municipality_name: str
    state_code: str
    system_type: str
    customer_count: int
    permitted_valuation_methods: List[str]
    status: str
    council_approved: bool
    filing_estimate_cents: int
    selected_value_cents: Optional[int]
    admitted_rate_base_cents: Optional[int]
    disallowed_premium_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ConditionAssessment(TypedDict, total=False):
    id: str
    target_id: str
    notes: str
    created_by_user_id: str
    revision_count: int
    status: str
    planning_estimate_cents: int
    filing_estimate_cents: int
    created_at: str
    updated_at: str
    version: int


class CapitalNeedItem(TypedDict, total=False):
    id: str
    assessment_id: str
    category: str
    horizon: str
    description: str
    cost_low_cents: int
    cost_high_cents: int
    midpoint_estimate_cents: int
    crews_required: int
    window_start: Optional[str]
    window_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ValuationCase(TypedDict, total=False):
    id: str
    target_id: str
    status: str
    selected_entry_id: Optional[str]
    selected_value_cents: Optional[int]
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ValuationEntry(TypedDict, total=False):
    id: str
    case_id: str
    method: str
    value_cents: int
    law_citation: str
    appraiser_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CouncilEvent(TypedDict, total=False):
    id: str
    target_id: str
    kind: str
    scheduled_start: str
    scheduled_end: str
    yes_votes: Optional[int]
    no_votes: Optional[int]
    yes_share_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryApplication(TypedDict, total=False):
    id: str
    target_id: str
    purchase_price_cents: int
    rate_base_method: str
    original_cost_less_depreciation_cents: Optional[int]
    filing_round: int
    status: str
    admitted_rate_base_cents: Optional[int]
    disallowed_premium_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CustomerAccount(TypedDict, total=False):
    id: str
    target_id: str
    account_ref: str
    deposit_cents: int
    ar_balance_cents: int
    status: str
    deposit_offset_cents: Optional[int]
    refund_cents: Optional[int]
    new_ar_balance_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TransitionItem(TypedDict, total=False):
    id: str
    target_id: str
    category: str
    status: str
    resolution_note: str
    created_at: str
    updated_at: str
    version: int


class EmployeeTransition(TypedDict, total=False):
    id: str
    target_id: str
    employee_ref: str
    years_of_service: int
    weekly_salary_cents: int
    union_covered: bool
    status: str
    severance_weeks: Optional[int]
    severance_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TariffCase(TypedDict, total=False):
    id: str
    target_id: str
    mode: str
    representative_old_bill_cents: int
    consolidated_monthly_bill_cents: int
    phase_in_years: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
