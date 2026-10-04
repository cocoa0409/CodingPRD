"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    POLICYHOLDER = "Policyholder"
    AGENT = "Agent"
    PARTNER_PLATFORM = "PartnerPlatform"
    UNDERWRITER = "Underwriter"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    FINANCE_OFFICER = "FinanceOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class Disposition(str, Enum):
    ADMIT = "ADMIT"
    REFER = "REFER"
    DECLINE = "DECLINE"


class Channel(str, Enum):
    DIRECT = "DIRECT"
    AGENT = "AGENT"
    PARTNER = "PARTNER"


class SignalType(str, Enum):
    SOS_MATCH = "SOS_MATCH"
    PROPERTY_PIN = "PROPERTY_PIN"
    LOSS_HISTORY = "LOSS_HISTORY"
    FRAUD_SCREEN = "FRAUD_SCREEN"


class SignalStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    STALE = "STALE"


class QuoteStatus(str, Enum):
    CLASSIFYING = "CLASSIFYING"
    QUOTED = "QUOTED"
    REFERRED = "REFERRED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    BOUND = "BOUND"
    SUPERSEDED = "SUPERSEDED"


class PolicyStatus(str, Enum):
    BOUND = "BOUND"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    NON_RENEWAL_PENDING = "NON_RENEWAL_PENDING"
    NON_RENEWED = "NON_RENEWED"
    RENEWED = "RENEWED"


class EndorsementType(str, Enum):
    COVERAGE_ADJUST = "COVERAGE_ADJUST"
    ADDITIONAL_INSURED = "ADDITIONAL_INSURED"
    LIMIT_CHANGE = "LIMIT_CHANGE"
    CLASS_RECODE = "CLASS_RECODE"


class EndorsementStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    VOID = "VOID"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class TriageTier(str, Enum):
    FAST_TRACK = "FAST_TRACK"
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"


class ReferralDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ReasonCode(str, Enum):
    APPETITE_CHANGE = "APPETITE_CHANGE"
    RISK_ESCALATION = "RISK_ESCALATION"
    CARRIER_WITHDRAWAL = "CARRIER_WITHDRAWAL"


class Line(str, Enum):
    GL = "GL"
    PL = "PL"
    TOOLS = "TOOLS"


# --- common_fields entities: id + created_at + updated_at + version ---

class AppetiteRule(TypedDict, total=False):
    id: str
    keyword: str
    class_code: str
    disposition: str
    effective_from: str
    effective_to: str
    is_enabled: bool
    priority_rank: int
    created_at: str
    updated_at: str
    version: int


class ClassCode(TypedDict, total=False):
    id: str
    code: str
    description: str
    eligible_lines: list
    base_rates_cents: dict
    risk_factor: float
    appetite_active: bool
    created_at: str
    updated_at: str
    version: int


class BusinessAccount(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    channel: str
    partner_tenant: Optional[str]
    account_credit_cents: int
    open_claim_count: int
    claims_free_flag: bool
    created_at: str
    updated_at: str
    version: int


class RiskSignalReport(TypedDict, total=False):
    id: str
    business_account_id: str
    signal_type: str
    severity: int
    status: str
    detail: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    business_account_id: str
    channel_partner_id: Optional[str]
    class_code_id: str
    raw_description: str
    selected_lines: list
    exposure_units: int
    requested_effective_at: str
    uw_answers: dict
    risk_score: int
    annual_premium_cents: int
    premium_basis_hash: str
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    quote_id: str
    business_account_id: str
    class_code_id: str
    term_start: str
    term_end: str
    term_day_count: int
    exposure_units: int
    base_annual_premium_cents: int
    earned_premium_cents: int
    open_claim_count: int
    renewal_window_start: str
    non_renewal_notice_sent_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Endorsement(TypedDict, total=False):
    id: str
    policy_id: str
    endorsement_type: str
    effective_at: str
    new_exposure_units: Optional[int]
    added_lines: Optional[list]
    removed_lines: Optional[list]
    ai_holder_name: Optional[str]
    premium_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    policy_id: str
    endorsement_id: str
    holder_name: str
    issued_at: str
    certificate_no: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    policy_id: str
    reported_by: str
    loss_occurred_at: str
    description: str
    claim_amount_cents: int
    triage_tier: str
    evidence_count: int
    adjuster_owner: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class UnderwriterReferral(TypedDict, total=False):
    id: str
    quote_id: str
    assigned_underwriter: str
    decision: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NonRenewalNotice(TypedDict, total=False):
    id: str
    policy_id: str
    reason_code: str
    sent_at: str
    days_before_term_end: int
    created_at: str
    updated_at: str
    version: int


# --- append-only entities: ONLY id + created_at (no updated_at, no version) ---

class ClaimEvidence(TypedDict, total=False):
    id: str
    claim_id: str
    photo_ref: str
    exif_taken_at: str
    file_size_bytes: int
    created_at: str


class AuditEvent(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    entity_type: str
    entity_id: str
    action: str
    before_snapshot: dict
    after_snapshot: dict
    created_at: str
