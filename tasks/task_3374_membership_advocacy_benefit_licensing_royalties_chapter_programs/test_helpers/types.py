"""Domain types: entity TypedDicts, status enums, role enum.

Field names and status vocabularies follow the PRD exactly. Every resource
carries the common system-managed fields id / created_at / updated_at /
version (PRD common resource properties).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MEMBER_SERVICES_AGENT = "MemberServicesAgent"
    MEMBER = "Member"
    PROVIDER_MANAGER = "ProviderManager"
    GOVERNANCE_OFFICER = "GovernanceOfficer"
    OVERSIGHT_ANALYST = "OversightAnalyst"
    FINANCE_CONTROLLER = "FinanceController"
    STANDARDS_REVIEWER = "StandardsReviewer"
    CHAPTER_COORDINATOR = "ChapterCoordinator"
    ADVOCACY_DIRECTOR = "AdvocacyDirector"


class HouseholdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class MemberRole(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class MembershipTermStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RENEWED = "RENEWED"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    DECEASED = "DECEASED"


class ProviderStatus(str, Enum):
    APPLICANT = "APPLICANT"
    LICENSED = "LICENSED"
    SUSPENDED = "SUSPENDED"


class ProductCategory(str, Enum):
    INSURANCE_HEALTH = "INSURANCE_HEALTH"
    INSURANCE_AUTO = "INSURANCE_AUTO"
    INSURANCE_LIFE = "INSURANCE_LIFE"
    FINANCIAL_SERVICES = "FINANCIAL_SERVICES"
    TRAVEL_SERVICES = "TRAVEL_SERVICES"
    HOME_SERVICES = "HOME_SERVICES"


class LicenseAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    TERMINATED = "TERMINATED"


class AgreementAction(str, Enum):
    ACTIVATE = "ACTIVATE"
    PROBATE = "PROBATE"
    REINSTATE = "REINSTATE"
    TERMINATE = "TERMINATE"


class RoyaltyStatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class ComplaintCategory(str, Enum):
    PRODUCT_QUALITY = "PRODUCT_QUALITY"
    BILLING = "BILLING"
    SERVICE = "SERVICE"
    CLAIMS = "CLAIMS"


class ComplaintSeverity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class ComplaintAction(str, Enum):
    OPEN_REVIEW = "OPEN_REVIEW"
    RESOLVE = "RESOLVE"
    ESCALATE = "ESCALATE"


class LegalEntityKind(str, Enum):
    MEMBERSHIP_ORG = "MEMBERSHIP_ORG"
    FOUNDATION = "FOUNDATION"
    LOBBY_ARM = "LOBBY_ARM"


class FundTransferStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"


class TransferDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class AdCategory(str, Enum):
    TRAVEL = "TRAVEL"
    INSURANCE = "INSURANCE"
    HEALTH = "HEALTH"
    FINANCE = "FINANCE"
    RETAIL = "RETAIL"
    TOBACCO = "TOBACCO"
    FIREARMS = "FIREARMS"
    POLITICAL = "POLITICAL"


class AdBookingStatus(str, Enum):
    BOOKED = "BOOKED"


class CourseKind(str, Enum):
    TAX_PREP = "TAX_PREP"
    DRIVER_SAFETY = "DRIVER_SAFETY"


class CourseSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"


class CampaignLevel(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"


class CampaignStatus(str, Enum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class MobilizationChannel(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    MAIL = "MAIL"


class Household(TypedDict):
    id: str
    state_code: str
    auto_renew_enabled: bool
    status: str
    primary_member_id: str
    secondary_member_id: Optional[str]
    lifetime_collected_cents: int
    lifetime_refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    household_id: str
    full_name: str
    date_of_birth: str
    role_in_household: str
    benefit_marketing_opt_out: bool
    age_years: int
    in_good_standing: bool
    created_at: str
    updated_at: str
    version: int


class MembershipTerm(TypedDict):
    id: str
    household_id: str
    term_years: int
    is_renewal: bool
    start_date: str
    end_date: str
    purchased_at: str
    paid_cents: int
    refunded_cents: int
    cancel_reason: Optional[str]
    cancelled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    legal_name: str
    status: str
    royalty_balance_cents: int
    escalations_trailing_12mo: int
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict):
    id: str
    provider_id: str
    product_category: str
    effective_from: str
    effective_to: str
    status: str
    probation_count: int
    escalations_trailing_12mo: int
    recognized_royalty_cents: int
    provisional_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    license_agreement_id: str
    period_year: int
    period_quarter: int
    reported_sales_cents: int
    audited_sales_cents: Optional[int]
    provisional_royalty_cents: int
    final_royalty_cents: Optional[int]
    delta_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    member_id: str
    license_agreement_id: str
    category: str
    severity: str
    description: str
    status: str
    filed_at: str
    escalated_at: Optional[str]
    resolution_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LegalEntity(TypedDict):
    id: str
    kind: str
    display_name: str
    balance_cents: int
    created_at: str
    updated_at: str
    version: int


class FundTransfer(TypedDict):
    id: str
    from_entity_id: str
    to_entity_id: str
    amount_cents: int
    purpose: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    from_balance_after_cents: Optional[int]
    to_balance_after_cents: Optional[int]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Publication(TypedDict):
    id: str
    title: str
    publication_date: str
    min_cpm_cents: int
    max_cpm_cents: int
    circulation_count: int
    created_at: str
    updated_at: str
    version: int


class AdBooking(TypedDict):
    id: str
    publication_id: str
    advertiser_name: str
    category: str
    agreed_cpm_cents: int
    estimated_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Chapter(TypedDict):
    id: str
    name: str
    state_code: str
    city: str
    created_at: str
    updated_at: str
    version: int


class CourseSession(TypedDict):
    id: str
    chapter_id: str
    course_kind: str
    instructor_name: str
    start_time: str
    end_time: str
    capacity: int
    enrolled_member_ids: List[str]
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    title: str
    level: str
    state_code: Optional[str]
    issue_area: str
    start_date: str
    end_date: str
    sponsor_entity_id: str
    computed_status: str
    created_at: str
    updated_at: str
    version: int


class MobilizationEvent(TypedDict):
    id: str
    campaign_id: str
    channel: str
    audience_spec: dict
    audience_count: int
    created_at: str
    updated_at: str
    version: int
