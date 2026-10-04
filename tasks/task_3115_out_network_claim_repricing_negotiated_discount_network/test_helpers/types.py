"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class ClaimType(str, Enum):
    PROFESSIONAL = "PROFESSIONAL"
    FACILITY = "FACILITY"
    ANCILLARY = "ANCILLARY"
    EMERGENCY = "EMERGENCY"


class NetworkStatus(str, Enum):
    IN_NETWORK = "IN_NETWORK"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"
    EMERGENCY_OON = "EMERGENCY_OON"


class Methodology(str, Enum):
    CONTRACTED_NETWORK = "CONTRACTED_NETWORK"
    REFERENCE_BASED = "REFERENCE_BASED"
    PERCENT_OF_MEDICARE = "PERCENT_OF_MEDICARE"
    UCR = "UCR"
    NEGOTIATION_REQUIRED = "NEGOTIATION_REQUIRED"
    NEGOTIATED = "NEGOTIATED"


class PayerClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ClaimStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PENDING_LINES = "PENDING_LINES"
    PRICED = "PRICED"
    SETTLED = "SETTLED"
    FINALIZED = "FINALIZED"


class ClaimLineStatus(str, Enum):
    PENDING = "PENDING"
    PRICED = "PRICED"
    VOID = "VOID"


class DeterminationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class NegotiationCaseStatus(str, Enum):
    OPEN = "OPEN"
    OFFER_PENDING = "OFFER_PENDING"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class SettlementStatus(str, Enum):
    PENDING_SIGNATURES = "PENDING_SIGNATURES"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class OpenNegotiationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AGREED = "AGREED"
    EXPIRED = "EXPIRED"
    SUPERSEDED_BY_IDR = "SUPERSEDED_BY_IDR"


class IdrStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DECIDED_PAYER = "DECIDED_PAYER"
    DECIDED_PROVIDER = "DECIDED_PROVIDER"
    DISMISSED = "DISMISSED"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RE_REVIEWED_UPHELD = "RE_REVIEWED_UPHELD"
    RE_REVIEWED_ADJUSTED = "RE_REVIEWED_ADJUSTED"
    DENIED = "DENIED"


class FeedBatchStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class ReportStatus(str, Enum):
    PUBLISHED = "PUBLISHED"


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    PAYER_ADMIN = "PayerAdmin"
    PAYER_REP = "PayerRep"
    PROVIDER_REP = "ProviderRep"
    NETWORK_ADMIN = "NetworkAdmin"
    FEED_OPERATOR = "FeedOperator"
    IDR_ENTITY = "IdrEntity"


# --- Entity TypedDicts ---
# common_fields: true — id + created_at + updated_at + version

class PayerClient(TypedDict, total=False):
    id: str
    payer_name: str
    status: str
    fee_percent: float
    fee_cap_cents_per_claim: int
    minimum_invoice_cents: int
    transparency_reporting_enabled: bool
    created_at: str
    updated_at: str
    version: int


class RepricingPolicy(TypedDict, total=False):
    id: str
    payer_client_id: str
    claim_type: str
    network_status: str
    methodology: str
    percent_of_medicare: Optional[float]
    rbp_markup_percent: Optional[float]
    ucr_percentile: Optional[int]
    priority: int
    status: str
    rounding_order: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    npi: str
    legal_name: str
    tin: str
    created_at: str
    updated_at: str
    version: int


class NetworkAgreement(TypedDict, total=False):
    id: str
    network_name: str
    provider_id: str
    discount_percent: float
    effective_start: str
    effective_end: str
    balance_billing_prohibited: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only rate rows carry ONLY id + created_at

class MedicareFeeScheduleEntry(TypedDict, total=False):
    id: str
    procedure_code: str
    region_code: str
    base_rate_cents: int
    geographic_adjustment_factor: float
    effective_year: int
    created_at: str


class UsualCustomaryRate(TypedDict, total=False):
    id: str
    procedure_code: str
    region_code: str
    percentile_50_cents: int
    percentile_80_cents: int
    created_at: str


class Claim(TypedDict, total=False):
    id: str
    payer_client_id: str
    provider_id: str
    external_claim_ref: str
    claim_type: str
    network_status: str
    service_date: str
    billed_amount_cents: int
    patient_responsibility_cents: int
    nsa_flag: bool
    methodology_used: Optional[str]
    allowed_amount_cents: Optional[int]
    payer_liability_cents: Optional[int]
    savings_cents: Optional[int]
    rbp_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict, total=False):
    id: str
    claim_id: str
    procedure_code: str
    quantity_units: int
    unit_charge_cents: int
    region_code: str
    allowed_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepricingDetermination(TypedDict, total=False):
    id: str
    claim_id: str
    methodology: str
    policy_id: Optional[str]
    agreement_id: Optional[str]
    supersedes_determination_id: Optional[str]
    input_snapshot: Any
    computation_trace: list
    defensibility_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class NegotiationCase(TypedDict, total=False):
    id: str
    claim_id: str
    opened_by_role: str
    round_count: int
    current_offer_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementAgreement(TypedDict, total=False):
    id: str
    negotiation_case_id: str
    claim_id: str
    settled_amount_cents: int
    payer_signed_at: Optional[str]
    provider_signed_at: Optional[str]
    balance_billing_prohibited: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class OpenNegotiation(TypedDict, total=False):
    id: str
    claim_id: str
    initiated_by: str
    initiated_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IdrSubmission(TypedDict, total=False):
    id: str
    claim_id: str
    open_negotiation_id: str
    payer_offer_cents: int
    provider_offer_cents: int
    qpa_cents: int
    submitted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProviderAppeal(TypedDict, total=False):
    id: str
    claim_id: str
    determination_id: str
    appeal_reason: str
    appeal_window_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimFeedBatch(TypedDict, total=False):
    id: str
    payer_client_id: str
    feed_type: str
    record_count: int
    received_at: str
    sla_due_at: str
    processed_at: Optional[str]
    sla_met: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeInvoice(TypedDict, total=False):
    id: str
    payer_client_id: str
    claim_ids: List[str]
    gross_fee_cents: int
    aggregate_fee_cents: int
    transparency_report_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransparencyReport(TypedDict, total=False):
    id: str
    fee_invoice_id: str
    total_billed_cents: int
    total_allowed_cents: int
    total_savings_cents: int
    total_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
