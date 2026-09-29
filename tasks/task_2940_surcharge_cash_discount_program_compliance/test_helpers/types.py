"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    MERCHANT_OPERATOR = "MerchantOperator"
    NETWORK_AUDITOR = "NetworkAuditor"
    STATE_REGULATOR = "StateRegulator"
    TERMINAL_AGENT = "TerminalAgent"


class AgEnforcementPosture(str, Enum):
    PERMISSIVE = "PERMISSIVE"
    MONITORED = "MONITORED"
    RESTRICTIVE = "RESTRICTIVE"


class CostDocumentationState(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ProgramType(str, Enum):
    SURCHARGE = "SURCHARGE"
    CASH_DISCOUNT = "CASH_DISCOUNT"


class ConsistencyScope(str, Enum):
    BRAND_LEVEL = "BRAND_LEVEL"
    PRODUCT_LEVEL = "PRODUCT_LEVEL"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REGISTRATION = "PENDING_REGISTRATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REMEDIATION = "REMEDIATION"
    DISABLED = "DISABLED"
    WITHDRAWN = "WITHDRAWN"


class DisableReason(str, Enum):
    NONE = "NONE"
    JURISDICTION_PROHIBITION = "JURISDICTION_PROHIBITION"
    REGISTRATION_REVOKED = "REGISTRATION_REVOKED"
    REMEDIATION_ORDER = "REMEDIATION_ORDER"
    OPERATOR_SUSPENSION = "OPERATOR_SUSPENSION"


class CardBrand(str, Enum):
    VISA = "VISA"
    MASTERCARD = "MASTERCARD"
    DISCOVER = "DISCOVER"
    AMEX = "AMEX"


class ProductTier(str, Enum):
    ALL = "ALL"
    CONSUMER_CREDIT = "CONSUMER_CREDIT"
    COMMERCIAL_CREDIT = "COMMERCIAL_CREDIT"
    REWARDS_CREDIT = "REWARDS_CREDIT"


class CaptureProductTier(str, Enum):
    CONSUMER_CREDIT = "CONSUMER_CREDIT"
    COMMERCIAL_CREDIT = "COMMERCIAL_CREDIT"
    REWARDS_CREDIT = "REWARDS_CREDIT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CardFunding(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    PREPAID = "PREPAID"


class RegistrationState(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EFFECTIVE = "EFFECTIVE"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class RegistrationDecision(str, Enum):
    ACKNOWLEDGE = "ACKNOWLEDGE"
    REJECT = "REJECT"
    REVOKE = "REVOKE"


class ArtifactType(str, Enum):
    ENTRY_SIGNAGE = "ENTRY_SIGNAGE"
    POS_SIGNAGE = "POS_SIGNAGE"
    RECEIPT_TEMPLATE = "RECEIPT_TEMPLATE"
    PRICE_LIST_POSTING = "PRICE_LIST_POSTING"


class ArtifactState(str, Enum):
    DRAFT = "DRAFT"
    ATTESTED = "ATTESTED"
    EXPIRED = "EXPIRED"


class ExpiredReason(str, Enum):
    NONE = "NONE"
    REMEDIATION_ORDER = "REMEDIATION_ORDER"
    PROGRAM_WITHDRAWN = "PROGRAM_WITHDRAWN"


class TerminalState(str, Enum):
    PROVISIONED = "PROVISIONED"
    CONFIGURED = "CONFIGURED"
    ENFORCING = "ENFORCING"
    QUARANTINED = "QUARANTINED"
    DISABLED = "DISABLED"


class QuarantineReason(str, Enum):
    NONE = "NONE"
    OPERATOR_ACTION = "OPERATOR_ACTION"
    PROGRAM_SUSPENDED = "PROGRAM_SUSPENDED"
    PROGRAM_DISABLED = "PROGRAM_DISABLED"
    DISCLOSURE_EXPIRED = "DISCLOSURE_EXPIRED"


class TerminalAction(str, Enum):
    ENFORCE = "ENFORCE"
    QUARANTINE = "QUARANTINE"
    RESTORE = "RESTORE"


class ProgramStatusAction(str, Enum):
    SUSPEND = "SUSPEND"
    RESUME = "RESUME"
    WITHDRAW = "WITHDRAW"


class TransactionOutcome(str, Enum):
    APPROVED_WITH_SURCHARGE = "APPROVED_WITH_SURCHARGE"
    APPROVED_NO_SURCHARGE = "APPROVED_NO_SURCHARGE"
    APPROVED_CASH_DISCOUNT = "APPROVED_CASH_DISCOUNT"


class ComplaintSource(str, Enum):
    NETWORK = "NETWORK"
    ATTORNEY_GENERAL = "ATTORNEY_GENERAL"
    CARDHOLDER = "CARDHOLDER"


class AllegationType(str, Enum):
    UNDISCLOSED_SURCHARGE = "UNDISCLOSED_SURCHARGE"
    DEBIT_SURCHARGED = "DEBIT_SURCHARGED"
    CAP_EXCEEDED = "CAP_EXCEEDED"
    MISSING_RECEIPT_LINE = "MISSING_RECEIPT_LINE"
    PROHIBITED_JURISDICTION = "PROHIBITED_JURISDICTION"
    PRICE_POSTING_MISSING = "PRICE_POSTING_MISSING"


class InvestigationState(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class RemediationState(str, Enum):
    NONE = "NONE"
    PLAN_REQUIRED = "PLAN_REQUIRED"
    PLAN_SUBMITTED = "PLAN_SUBMITTED"
    PLAN_ACCEPTED = "PLAN_ACCEPTED"
    CLOSED = "CLOSED"


class InvestigationAction(str, Enum):
    REVIEW = "REVIEW"
    SUBSTANTIATE = "SUBSTANTIATE"
    DISMISS = "DISMISS"


class RemediationAction(str, Enum):
    SUBMIT_PLAN = "SUBMIT_PLAN"
    ACCEPT_PLAN = "ACCEPT_PLAN"
    CLOSE = "CLOSE"


class RefundState(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class Jurisdiction(TypedDict):
    id: str
    state_code: str
    surcharge_permitted: bool
    surcharge_cap_pct: Optional[float]
    cash_discount_permitted: bool
    price_posting_required: bool
    disclosure_signage_required: bool
    receipt_line_item_required: bool
    ag_enforcement_posture: str
    law_change_count: int
    last_law_change_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Merchant(TypedDict):
    id: str
    jurisdiction_id: str
    legal_name: str
    mcc: str
    active_cost_documentation_id: Optional[str]
    gross_surcharge_collected_cents: int
    net_surcharge_collected_cents: int
    enforcing_terminal_count: int
    created_at: str
    updated_at: str
    version: int


class CostDocumentation(TypedDict):
    id: str
    merchant_id: str
    base_mdr_pct: float
    assessment_pct: float
    per_item_fee_cents: int
    average_ticket_cents: int
    documented_cost_pct: float
    evidence_uri: str
    state: str
    attested_by_user_id: str
    effective_from: str
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurchargeProgram(TypedDict):
    id: str
    merchant_id: str
    jurisdiction_id: str
    cost_documentation_id: str
    program_type: str
    consistency_scope: str
    status: str
    disable_reason: str
    effective_cap_pct: float
    disclosure_ready: bool
    network_exposure_score: float
    ag_exposure_score: float
    cost_documentation_pinned_at: str
    activated_at: Optional[str]
    activated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BrandRateRule(TypedDict):
    id: str
    program_id: str
    brand: str
    product_tier: str
    rate_pct: float
    effective_from: str
    effective_to: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class NetworkRegistration(TypedDict):
    id: str
    program_id: str
    network: str
    registration_ref: str
    state: str
    submitted_at: str
    notice_days: int
    earliest_effective_at: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    effective_at: Optional[str]
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureArtifact(TypedDict):
    id: str
    program_id: str
    artifact_type: str
    content_hash: str
    state: str
    effective_from: Optional[str]
    expires_at: Optional[str]
    attested_at: Optional[str]
    attested_by_user_id: Optional[str]
    expired_reason: str
    created_at: str
    updated_at: str
    version: int


class Terminal(TypedDict):
    id: str
    merchant_id: str
    program_id: Optional[str]
    serial_number: str
    state: str
    debit_exclusion_enabled: bool
    bin_table_version: Optional[str]
    quarantine_reason: str
    last_configured_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    """A captured sale is an immutable event: it carries id and created_at only."""

    id: str
    terminal_id: str
    program_id: str
    card_brand: str
    card_funding: str
    product_tier: str
    base_amount_cents: int
    applied_rate_pct: float
    surcharge_amount_cents: int
    cash_discount_amount_cents: int
    cash_price_cents: int
    total_amount_cents: int
    receipt_line_present: bool
    outcome: str
    occurred_at: str
    refunded_surcharge_cents: int
    created_at: str


class ComplaintCase(TypedDict):
    id: str
    program_id: str
    source: str
    allegation_type: str
    narrative: str
    investigation_state: str
    remediation_state: str
    received_at: str
    response_due_at: str
    filed_by_user_id: str
    reviewed_by_user_id: Optional[str]
    plan_summary: Optional[str]
    refund_total_cents: int
    created_at: str
    updated_at: str
    version: int


class RemediationRefund(TypedDict):
    id: str
    complaint_case_id: str
    transaction_id: str
    refund_amount_cents: int
    state: str
    created_by_user_id: str
    issued_by_user_id: Optional[str]
    issued_at: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
