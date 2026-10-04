"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, TypedDict


class AgencyStatus(str, Enum):
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class AgentStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    APPOINTED = "APPOINTED"
    ACTIVE = "ACTIVE"
    TRANSITIONING = "TRANSITIONING"
    PENDING_TERMINATION = "PENDING_TERMINATION"
    TERMINATED = "TERMINATED"


class LicenseStatus(str, Enum):
    NOT_LICENSED = "NOT_LICENSED"
    LICENSED = "LICENSED"
    EXPIRED = "EXPIRED"


class PolicyStatus(str, Enum):
    OPEN = "OPEN"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"
    TRANSFERRED = "TRANSFERRED"


class ProductLine(str, Enum):
    AUTO = "AUTO"
    HOME = "HOME"
    LIFE = "LIFE"


class AgreementType(str, Enum):
    EXCLUSIVE_AGENT = "EXCLUSIVE_AGENT"
    TEAM_MEMBER = "TEAM_MEMBER"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    TRANSITIONING = "TRANSITIONING"


class StaffStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class CampaignType(str, Enum):
    LEAD_PROGRAM = "LEAD_PROGRAM"
    BRAND = "BRAND"
    COMMUNITY = "COMMUNITY"


class CampaignStatus(str, Enum):
    PLANNED = "PLANNED"
    PARTICIPATED = "PARTICIPATED"
    CANCELLED = "CANCELLED"


class ParticipationPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class BookTransferStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCORED = "SCORED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    CONSUMED = "CONSUMED"


class RequiredAction(str, Enum):
    PROCEED = "PROCEED"
    MARKET_ANALYSIS_REQUIRED = "MARKET_ANALYSIS_REQUIRED"
    REJECT = "REJECT"


class ApplicationValueTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class PerformanceStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    BEHIND = "BEHIND"
    AT_RISK = "AT_RISK"


class CreationChannel(str, Enum):
    DIGITAL = "DIGITAL"
    FIELD = "FIELD"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    APPOINTING_EXECUTIVE = "AppointingExecutive"
    FIELD_MANAGER = "FieldManager"
    AGENCY_PRINCIPAL = "AgencyPrincipal"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    REGULATORY_BOARD = "RegulatoryBoard"
    STAFF_MEMBER = "StaffMember"


# ─── Entity shapes (PRD §2.4 / §3) ────────────────────
# Top-level records carry id + created_at + updated_at + version.

class Agency(TypedDict, total=False):
    id: str
    agency_code: str
    name: str
    region_code: str
    market_need_score: int
    status: str
    book_open_count: int
    annualized_commission_cents: int
    exposure_inforce_cents: int
    agency_level_units: int
    agency_paid_claims_cents: int
    loss_ratio: float
    growth_new_pct: float
    performance_status: str
    agency_valuation_cents: int
    term_start_date: str
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    full_name: str
    state_code: str
    market_need_score: int
    license_status: str
    license_expiry_date: str
    state_market_need_acknowledged: bool
    status: str
    agency_id: str
    is_new_agent: bool
    appointment_date: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    policy_number: str
    product_line: str
    annual_premium_cents: int
    is_new_business: bool
    status: str
    holder_agent_id: str
    owner_agency_id: str
    book_transfer_id: str
    first_written_at: str
    paid_claims_cents: int
    sub_producer_released_commission_cents: int
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict, total=False):
    id: str
    agent_id: str
    agency_id: str
    agreement_type: str
    status: str
    commission_schedule: dict
    marketing_allowance_pool_cents: int
    marketing_allowance_spent_cents: int
    allowance_carryover_cents: int
    license_verified_at: str
    termination_initiated_at: str
    termination_value_cents: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    role_title: str
    allocation_units: int
    agency_id: str
    sponsoring_agreement_id: str
    status: str
    allocated_agent_id: str
    assignment_start_date: str
    assignment_end_date: str
    created_at: str
    updated_at: str
    version: int


class MarketingCampaign(TypedDict, total=False):
    id: str
    agency_id: str
    campaign_type: str
    marketing_allowance_cents: int
    expected_leads: int
    status: str
    participation_posture: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    policy_id: str
    claim_amount_cents: int
    policy_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BookTransfer(TypedDict, total=False):
    id: str
    agent_id: str
    from_agency_id: str
    to_agency_id: str
    successor_agent_id: str
    transferred_policy_count: int
    retained_policy_count: int
    retention_pct: float
    retention_met: bool
    settlement_payable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# LicenseRecord is immutable after posting: only id + created_at (PRD §2.4).
class LicenseRecord(TypedDict, total=False):
    id: str
    full_name: str
    state_code: str
    product_lines: List[str]
    license_expiry_date: str
    created_at: str


class AppointmentApplication(TypedDict, total=False):
    id: str
    state_code: str
    market_need_score: int
    candidate_assessment_score: int
    market_odds_score: int
    status: str
    required_action: str
    appointment_priority: int
    application_value_tier: str
    creation_channel: str
    agent_id: str
    closure_note: str
    created_at: str
    updated_at: str
    version: int