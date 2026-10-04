"""Domain types for the Healthcare Claims Clearinghouse API.

Entity TypedDicts, status enumerations and the role enumeration. Mutable
resources carry the full common quartet (id, created_at, updated_at, version);
append-only artifacts (pricing tiers, edit rules, posting files, outage
notifications) carry only id and created_at.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    CLEARINGHOUSE_OPS = "ClearinghouseOps"
    PROVIDER_ADMIN = "ProviderAdmin"
    PAYER_OPERATOR = "PayerOperator"


class ProviderStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class BillingModel(str, Enum):
    PROVIDER_FUNDED = "PROVIDER_FUNDED"
    PAYER_FUNDED = "PAYER_FUNDED"
    HYBRID = "HYBRID"


class VolumeTierCode(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class CredentialStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class PricingModel(str, Enum):
    PAYER_FUNDED = "PAYER_FUNDED"
    PROVIDER_FUNDED = "PROVIDER_FUNDED"
    SHARED = "SHARED"


class ConnectivityStatus(str, Enum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


class TierAppliesTo(str, Enum):
    CLAIM = "CLAIM"
    ELIGIBILITY = "ELIGIBILITY"
    REMITTANCE = "REMITTANCE"


class TransactionType(str, Enum):
    CLAIMS_837 = "CLAIMS_837"
    REMITTANCE_835 = "REMITTANCE_835"
    ELIGIBILITY_270 = "ELIGIBILITY_270"


class EnrollmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAYER_REVIEW = "PAYER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    RE_SUBMITTED = "RE_SUBMITTED"


class ClaimAcceptanceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    ACCEPTED = "ACCEPTED"
    REJECTED_CLEARINGHOUSE = "REJECTED_CLEARINGHOUSE"
    FORWARDED = "FORWARDED"
    ACKNOWLEDGED_BY_PAYER = "ACKNOWLEDGED_BY_PAYER"
    REJECTED_BY_PAYER = "REJECTED_BY_PAYER"


class ClaimAdjudicationStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    PAID = "PAID"
    DENIED = "DENIED"
    PARTIAL = "PARTIAL"


class RemittanceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    POSTED = "POSTED"
    FAILED_POSTING = "FAILED_POSTING"
    VOIDED = "VOIDED"


class PostingFileStatus(str, Enum):
    GENERATING = "GENERATING"
    READY = "READY"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class InquiryStatus(str, Enum):
    PENDING = "PENDING"
    RESPONDED = "RESPONDED"
    TIMED_OUT = "TIMED_OUT"
    QUEUED_OUTAGE = "QUEUED_OUTAGE"


class OutageSeverity(str, Enum):
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class OutageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    VOID = "VOID"


class RuleSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class Provider(TypedDict, total=False):
    id: str
    legal_name: str
    tax_identification_number: str
    national_provider_identifier: str
    billing_model: str
    volume_tier_code: str
    status: str
    activated_at: Optional[str]
    trailing_billable_units_3m: int
    account_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class SubmitterCredential(TypedDict, total=False):
    id: str
    provider_id: str
    submitter_id: str
    trading_partner_agreement_ref: str
    effective_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payer(TypedDict, total=False):
    id: str
    payer_id_code: str
    display_name: str
    claims_lead_time_days: int
    remittance_lead_time_days: int
    eligibility_lead_time_seconds: int
    pricing_model: str
    shared_provider_pct: Optional[float]
    connectivity_status: str
    monthly_minimum_cents: int
    created_at: str
    updated_at: str
    version: int


class PayerPricingTier(TypedDict, total=False):
    id: str
    payer_id: str
    applies_to: str
    volume_floor: int
    volume_ceiling: Optional[int]
    rate_cents: int
    created_at: str


class PayerEditRule(TypedDict, total=False):
    id: str
    payer_id: str
    rule_code: str
    applies_to: str
    severity: str
    expression: str
    effective_from: str
    effective_to: Optional[str]
    created_at: str


class PayerEnrollment(TypedDict, total=False):
    id: str
    provider_id: str
    payer_id: str
    transaction_type: str
    status: str
    submitted_at: Optional[str]
    payer_decision_due_at: Optional[str]
    payer_decision_due_at_calendar: Optional[str]
    approved_at: Optional[str]
    rejection_reason: Optional[str]
    decision_round: int
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict, total=False):
    cpt_code: str
    units: int
    unit_charge_cents: int


class EditFailure(TypedDict, total=False):
    rule_code: str
    severity: str
    message: str


class RejectionPayload(TypedDict, total=False):
    origin: str
    rule_codes: List[str]
    message: str


class Claim(TypedDict, total=False):
    id: str
    provider_id: str
    payer_id: str
    submitter_credential_id: str
    patient_control_number: str
    idempotency_key: str
    service_date: str
    total_charge_cents: int
    diagnosis_codes: List[str]
    rendering_npi: str
    subscriber_id: str
    lines: List[ClaimLine]
    acceptance_status: str
    adjudication_status: str
    edit_failures: List[EditFailure]
    forwarded_at: Optional[str]
    payer_response_due_at: Optional[str]
    payer_response_due_at_calendar: Optional[str]
    rejection_payload: Optional[RejectionPayload]
    created_at: str
    updated_at: str
    version: int


class RemittanceAdvice(TypedDict, total=False):
    id: str
    claim_id: str
    payer_id: str
    check_number: str
    paid_amount_cents: int
    adjustment_amount_cents: int
    patient_responsibility_cents: int
    denial_reason_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PostingFile(TypedDict, total=False):
    id: str
    remittance_advice_id: str
    generated_at: str
    line_count: int
    total_posted_cents: int
    status: str
    created_at: str


class EligibilityInquiry(TypedDict, total=False):
    id: str
    provider_id: str
    payer_id: str
    subscriber_id: str
    service_type_code: str
    idempotency_key: str
    status: str
    requested_at: str
    deadline_at: str
    responded_at: Optional[str]
    benefit_summary: Optional[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class ConnectivityOutage(TypedDict, total=False):
    id: str
    payer_id: str
    started_at: str
    ended_at: Optional[str]
    severity: str
    affects_transaction_types: List[str]
    status: str
    notified_provider_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class UsageInvoice(TypedDict, total=False):
    id: str
    provider_id: str
    period_yyyy_mm: str
    claim_units: int
    eligibility_units: int
    remittance_units: int
    billable_units: int
    gross_fee_cents: int
    monthly_minimum_applied_cents: int
    amount_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OutageNotification(TypedDict, total=False):
    id: str
    outage_id: str
    provider_id: str
    sent_at: str
    channel: str
    payload_summary: str
    created_at: str
