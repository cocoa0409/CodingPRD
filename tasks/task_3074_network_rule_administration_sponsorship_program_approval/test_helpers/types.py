"""Domain types: entity TypedDicts, status enums, role enum.

Field and status names follow the PRD exactly. Entities whose lifecycle is
append-only carry only ``id`` and ``created_at`` as common fields.
"""
from enum import Enum
from typing import Any, List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    NETWORK_OPERATOR = "NetworkOperator"
    SPONSORSHIP_MANAGER = "SponsorshipManager"
    RULES_ADMINISTRATOR = "RulesAdministrator"
    DISPUTE_ANALYST = "DisputeAnalyst"
    PRICING_ANALYST = "PricingAnalyst"
    FRAUD_ANALYST = "FraudAnalyst"
    SETTLEMENT_OPERATOR = "SettlementOperator"
    CERTIFICATION_ENGINEER = "CertificationEngineer"
    MEMBER = "Member"


# ─── Status enums ─────────────────────────────────────────────────────────

class MemberStatus(str, Enum):
    APPLICATION = "APPLICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class MemberKind(str, Enum):
    ISSUER = "ISSUER"
    ACQUIRER = "ACQUIRER"
    BOTH = "BOTH"


class Region(str, Enum):
    NA = "NA"
    EU = "EU"
    APAC = "APAC"
    LATAM = "LATAM"
    CEMEA = "CEMEA"


class ParticipantStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class MerchantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class FraudMonitoringStatus(str, Enum):
    NOT_MONITORED = "NOT_MONITORED"
    UNDER_MONITORING = "UNDER_MONITORING"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    EXEMPTED = "EXEMPTED"


class BinRangeStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class ProgramStatus(str, Enum):
    REGISTERED = "REGISTERED"
    UNDER_CERTIFICATION = "UNDER_CERTIFICATION"
    APPROVED = "APPROVED"
    PRODUCTION_ENABLED = "PRODUCTION_ENABLED"
    RETIRED = "RETIRED"


class ProgramType(str, Enum):
    CARD_PRODUCT = "CARD_PRODUCT"
    WALLET = "WALLET"
    COMMERCIAL = "COMMERCIAL"


class CertificationScope(str, Enum):
    NEW_PRODUCT = "NEW_PRODUCT"
    WALLET = "WALLET"
    COMBINED = "COMBINED"


class CertificationTestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class NetworkRuleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class RuleScope(str, Enum):
    GLOBAL = "GLOBAL"
    NA = "NA"
    EU = "EU"
    APAC = "APAC"
    LATAM = "LATAM"
    CEMEA = "CEMEA"


class ViolationSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class RuleViolationStatus(str, Enum):
    CITED = "CITED"
    ASSESSED = "ASSESSED"
    APPEALED = "APPEALED"
    CONFIRMED = "CONFIRMED"
    WAIVED = "WAIVED"


class DisputeCaseStatus(str, Enum):
    OPENED = "OPENED"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    DECIDED = "DECIDED"
    ARBITRATION_REQUESTED = "ARBITRATION_REQUESTED"
    ARBITRATION_DECIDED = "ARBITRATION_DECIDED"
    CLOSED = "CLOSED"


class DisputeSide(str, Enum):
    ISSUER = "ISSUER"
    ACQUIRER = "ACQUIRER"


class EvidenceType(str, Enum):
    TRANSACTION_RECORD = "TRANSACTION_RECORD"
    PROOF_OF_DELIVERY = "PROOF_OF_DELIVERY"
    REFUND_POLICY = "REFUND_POLICY"
    CARDHOLDER_LETTER = "CARDHOLDER_LETTER"
    OTHER = "OTHER"


class TransactionType(str, Enum):
    CARD_PRESENT = "CARD_PRESENT"
    CARD_NOT_PRESENT = "CARD_NOT_PRESENT"
    ECOM_TOKENIZED = "ECOM_TOKENIZED"
    RECURRING = "RECURRING"


class DataQualityTier(str, Enum):
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"
    PREMIUM = "PREMIUM"


class InterchangeRateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class FraudCaseStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class RemediationSubjectType(str, Enum):
    MERCHANT = "MERCHANT"
    ACQUIRER = "ACQUIRER"


class RemediationPlanStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"


class FraudProgramCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class SettlementWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"


class SettlementLineStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    REVERSED = "REVERSED"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Every resource except dispute evidence carries id, created_at, updated_at
# and version. Dispute evidence is append-only: id and created_at only.

class Member(TypedDict, total=False):
    id: str
    legal_name: str
    member_kind: str
    region: str
    status: str
    suspension_reason: Optional[str]
    settled_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    name: str
    sponsor_member_id: str
    program_name: str
    status: str
    fraud_attributed_count: int
    created_at: str
    updated_at: str
    version: int


class Merchant(TypedDict, total=False):
    id: str
    participant_id: Optional[str]
    acquirer_member_id: Optional[str]
    mcc: str
    region: str
    declared_monthly_volume_cents: int
    status: str
    fraud_monitoring_status: str
    created_at: str
    updated_at: str
    version: int


class BinRange(TypedDict, total=False):
    id: str
    bin_prefix: str
    issuer_member_id: str
    status: str
    assigned_program_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    name: str
    program_type: str
    product_code: str
    owner_member_id: str
    status: str
    approved_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CertificationTest(TypedDict, total=False):
    id: str
    program_id: str
    scope: str
    status: str
    failure_reason: Optional[str]
    evaluated_program_version: int
    created_at: str
    updated_at: str
    version: int


class FineTier(TypedDict, total=False):
    min_amount_minor: int
    max_amount_minor: Optional[int]
    fine_cents: int


class NetworkRule(TypedDict, total=False):
    id: str
    rule_code: str
    title: str
    body: str
    region_scope: str
    regional_override_of_rule_id: Optional[str]
    effective_from: str
    status: str
    fine_schedule: List[FineTier]
    created_at: str
    updated_at: str
    version: int


class RuleViolation(TypedDict, total=False):
    id: str
    rule_id: str
    subject_member_id: str
    severity: str
    transaction_amount_minor: int
    status: str
    fine_cents: Optional[int]
    assessed_by_id: Optional[str]
    cited_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisputeCase(TypedDict, total=False):
    id: str
    reason_code: str
    issuer_member_id: str
    acquirer_member_id: str
    merchant_id: str
    transaction_amount_cents: int
    currency: str
    status: str
    winning_side: Optional[str]
    filing_clock: str
    created_at: str
    updated_at: str
    version: int


class DisputeEvidence(TypedDict, total=False):
    # Append-only: only id + created_at as common fields.
    id: str
    created_at: str
    dispute_case_id: str
    submitted_by_member_id: str
    evidence_type: str
    document_ref: str
    submitted_at: str


class InterchangeRate(TypedDict, total=False):
    id: str
    merchant_category: str
    transaction_type: str
    data_quality_tier: str
    rate_basis_points: int
    fixed_fee_cents: int
    region_scope: str
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FraudCase(TypedDict, total=False):
    id: str
    merchant_id: str
    reported_by_member_id: str
    fraud_amount_cents: int
    status: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationPlan(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    fraud_program_cycle_id: str
    actions: List[str]
    status: str
    due_at: str
    approved_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudProgramCycle(TypedDict, total=False):
    id: str
    cycle_label: str
    period_start: str
    period_end: str
    evaluated_at: Optional[str]
    status: str
    merchants_flagged: int
    acquirers_flagged: int
    created_at: str
    updated_at: str
    version: int


class SettlementWindow(TypedDict, total=False):
    id: str
    window_date: str
    opens_at: str
    closes_at: str
    status: str
    total_settled_cents: int
    created_at: str
    updated_at: str
    version: int


class SettlementLine(TypedDict, total=False):
    id: str
    window_id: str
    from_member_id: str
    to_member_id: str
    amount_cents: int
    currency: str
    reference: str
    status: str
    committed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PositionEntry(TypedDict, total=False):
    member_id: str
    net_cents: int


class PositionsRead(TypedDict, total=False):
    positions: List[PositionEntry]
    total_check_cents: int


class QuoteResult(TypedDict, total=False):
    fee_cents: int
    qualified_tier: str
    rate_basis_points: int
    applied_rate_id: str
