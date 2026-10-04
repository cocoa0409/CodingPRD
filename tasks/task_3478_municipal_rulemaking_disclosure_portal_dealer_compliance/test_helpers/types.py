"""Domain types: entity shapes, status enums, and the role enum.

Field names and enum spellings are exactly those of PRD.md sections 3 and 4.
Primary resources carry ``id``, ``created_at``, ``updated_at`` and ``version``
(PRD section 2.8); the two append-only record families - exam attempts and
solicitation records - carry only ``id`` and ``created_at``, and their shapes
here deliberately omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Optional, TypedDict


# --- Roles (PRD section 2.1) -------------------------------------------------

class UserRole(str, Enum):
    """The eleven roles, spelled exactly as the contract names them."""

    SYSTEM_ADMIN = "SystemAdmin"
    RULEMAKING_OFFICER = "RulemakingOfficer"
    REGULATOR = "Regulator"
    PORTAL_OPERATOR = "PortalOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    EXAM_ADMIN = "ExamAdmin"
    LICENSING_OFFICER = "LicensingOfficer"
    ISSUER_REP = "IssuerRep"
    DEALER_REP = "DealerRep"
    MARKET_DATA_SUBSCRIBER = "MarketDataSubscriber"
    PUBLIC_READER = "PublicReader"


# Roles whose X-User-ID must equal the id of the acting Organization
# (PRD section 2.1). Every other role is opaque.
ENTITY_BACKED_ROLES = (UserRole.ISSUER_REP.value, UserRole.DEALER_REP.value)

OPAQUE_ROLES = tuple(r.value for r in UserRole if r.value not in ENTITY_BACKED_ROLES)

ALL_ROLES = tuple(r.value for r in UserRole)


# --- Enumerations used by entity fields --------------------------------------

class OrgType(str, Enum):
    ISSUER = "ISSUER"
    OBLIGATED_PERSON = "OBLIGATED_PERSON"
    BROKER_DEALER = "BROKER_DEALER"
    MUNICIPAL_ADVISOR = "MUNICIPAL_ADVISOR"


class OrgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"


class RuleCategory(str, Enum):
    DEALER_CONDUCT = "DEALER_CONDUCT"
    ADVISOR_CONDUCT = "ADVISOR_CONDUCT"
    DISCLOSURE = "DISCLOSURE"
    TRADE_REPORTING = "TRADE_REPORTING"
    MARKET_DATA = "MARKET_DATA"
    QUALIFICATION = "QUALIFICATION"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN_FOR_COMMENT = "OPEN_FOR_COMMENT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DISAPPROVED = "DISAPPROVED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class Sentiment(str, Enum):
    SUPPORT = "SUPPORT"
    OPPOSE = "OPPOSE"
    NEUTRAL = "NEUTRAL"


class CommentLetterStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PUBLISHED = "PUBLISHED"
    DISMISSED = "DISMISSED"


class SubmissionType(str, Enum):
    OFFICIAL_STATEMENT = "OFFICIAL_STATEMENT"
    ANNUAL_FINANCIAL = "ANNUAL_FINANCIAL"
    EVENT_NOTICE = "EVENT_NOTICE"
    VOLUNTARY = "VOLUNTARY"


class EventCategory(str, Enum):
    PAYMENT_DEFAULT = "PAYMENT_DEFAULT"
    RATING_CHANGE = "RATING_CHANGE"
    BOND_CALL = "BOND_CALL"
    MERGER_ANNOUNCEMENT = "MERGER_ANNOUNCEMENT"
    MATERIAL_LITIGATION = "MATERIAL_LITIGATION"
    OTHER = "OTHER"


class SubmissionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PUBLISHED = "PUBLISHED"
    DEFICIENT = "DEFICIENT"


class Timeliness(str, Enum):
    TIMELY = "TIMELY"
    LATE = "LATE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ProfessionalClass(str, Enum):
    MUNICIPAL_DEALER_REP = "MUNICIPAL_DEALER_REP"
    MUNICIPAL_ADVISOR_REP = "MUNICIPAL_ADVISOR_REP"
    MUNICIPAL_PRINCIPAL = "MUNICIPAL_PRINCIPAL"


class QualificationStatus(str, Enum):
    UNQUALIFIED = "UNQUALIFIED"
    QUALIFIED = "QUALIFIED"
    CE_DUE = "CE_DUE"
    LAPSED = "LAPSED"


class Standing(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SeriesCode(str, Enum):
    MSRB_50 = "MSRB_50"
    MSRB_52 = "MSRB_52"
    MSRB_53 = "MSRB_53"
    MSRB_54 = "MSRB_54"


class ExamResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class TradeType(str, Enum):
    INTER_DEALER = "INTER_DEALER"
    CUSTOMER_BUY = "CUSTOMER_BUY"
    CUSTOMER_SELL = "CUSTOMER_SELL"


class TradeStatus(str, Enum):
    DISSEMINATED = "DISSEMINATED"
    CANCELLED = "CANCELLED"


class ProductCode(str, Enum):
    TRADE_REALTIME = "TRADE_REALTIME"
    TRADE_HISTORICAL = "TRADE_HISTORICAL"
    DISCLOSURE_ARCHIVE = "DISCLOSURE_ARCHIVE"


class LicenseScope(str, Enum):
    INTERNAL = "INTERNAL"
    DISPLAY = "DISPLAY"
    REDISTRIBUTION = "REDISTRIBUTION"


class SubscriptionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    REJECTED = "REJECTED"


class ExaminingAuthority(str, Enum):
    DEALER_EXAM_AUTHORITY = "DEALER_EXAM_AUTHORITY"
    ADVISOR_EXAM_AUTHORITY = "ADVISOR_EXAM_AUTHORITY"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    REFERRED = "REFERRED"
    CLOSED_ACTION_TAKEN = "CLOSED_ACTION_TAKEN"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"


class CompensationType(str, Enum):
    FIXED = "FIXED"
    HOURLY = "HOURLY"
    CONTINGENT = "CONTINGENT"


# --- Entity shapes ------------------------------------------------------------
# Fields mirror the PRD section 3 narratives. Mutable resources carry the four
# common properties of PRD section 2.8; the append-only families carry only
# ``id`` and ``created_at``.
#
# TypedDicts are descriptive, not exhaustive: computed fields that the PRD
# guarantees on the resource are listed so tests can rely on them.


class Organization(TypedDict, total=False):
    id: str
    org_code: str
    name: str
    org_type: str
    status: str
    suspended_reason: Optional[str]
    late_report_count: int
    compliance_posture: str
    published_par_total: int
    active_professional_count: int
    created_at: str
    updated_at: str
    version: int


class RuleProposal(TypedDict, total=False):
    id: str
    rule_code: str
    title: str
    body: str
    category: str
    supersedes_proposal_id: Optional[str]
    status: str
    expedited: bool
    comment_period_days: int
    comment_window_start: Optional[str]
    comment_window_end: Optional[str]
    comment_round: int
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision_reason: Optional[str]
    approval_at: Optional[str]
    effective_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommentLetter(TypedDict, total=False):
    id: str
    proposal_id: str
    author_name: str
    body: str
    sentiment: str
    status: str
    moderation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureSubmission(TypedDict, total=False):
    id: str
    issuer_org_id: str
    submission_type: str
    event_category: Optional[str]
    event_occurred_at: Optional[str]
    period_start: Optional[str]
    period_end: Optional[str]
    document_uri: str
    cusip: str
    status: str
    timeliness: str
    deficiency_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MunicipalProfessional(TypedDict, total=False):
    id: str
    full_name: str
    employer_org_id: str
    professional_class: str
    qualification_status: str
    standing: str
    qualified_at: Optional[str]
    ce_cycle_end: Optional[str]
    ce_grace_end: Optional[str]
    ce_credits_total: float
    ce_ethics_credits: float
    may_transact: bool
    created_at: str
    updated_at: str
    version: int


class ExamAttempt(TypedDict, total=False):
    # Append-only event record: carries only id and created_at (PRD section 2.8).
    id: str
    professional_id: str
    series_code: str
    score: int
    result: str
    created_at: str


class TradeReport(TypedDict, total=False):
    id: str
    dealer_org_id: str
    cusip: str
    trade_type: str
    par_amount: int
    price: float
    executed_at: str
    reported_at: str
    late_flag: bool
    seconds_late: int
    published_par: int
    capped_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DataSubscription(TypedDict, total=False):
    id: str
    product_code: str
    licensee_org_id: str
    subscriber_principal: str
    license_scope: str
    seats: int
    status: str
    monthly_fee_cents: int
    annual_invoice_cents: int
    created_at: str
    updated_at: str
    version: int


class EnforcementReferral(TypedDict, total=False):
    id: str
    rule_code: str
    subject_org_id: Optional[str]
    subject_professional_id: Optional[str]
    violation_summary: str
    examining_authority: str
    status: str
    created_by_user_id: str
    referred_at: Optional[str]
    closed_by_user_id: Optional[str]
    closure_notes: Optional[str]
    guidance_text: Optional[str]
    needs_rule_review: bool
    created_at: str
    updated_at: str
    version: int


class SolicitationRecord(TypedDict, total=False):
    # Append-only event record: carries only id and created_at (PRD section 2.8).
    id: str
    advisor_org_id: str
    municipal_entity_name: str
    compensation_type: str
    compensation_cents: int
    disclosure_provided: bool
    created_at: str


class ClockSetResult(TypedDict, total=False):
    # Non-resource response of the clock-setting operation (PRD section 2.4).
    current_utc: str
    epoch_effects: int


class DataFeedResult(TypedDict, total=False):
    # Non-resource response of the licensed feed pull (PRD section 3.7).
    product_code: str
    subscription_id: str
    record_count: int
