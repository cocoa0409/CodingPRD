"""Domain types for the reinsurance broker placement API (PRD §3).

Status enums, the role enum and one TypedDict per resource type. Resources that
carry ``updated_at``/``version`` are separated from the two append-only evidence
records (contract documents and renewal reports) which carry only ``id`` and
``created_at`` per PRD §2.5.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BROKER_PLACEMENT_LEAD = "BrokerPlacementLead"
    BROKER_ACTUARY = "BrokerActuary"
    BROKER_ACCOUNTANT = "BrokerAccountant"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CEDENT_UNDERWRITER = "CedentUnderwriter"
    REINSURER_UNDERWRITER = "ReinsurerUnderwriter"


# --------------------------------------------------------------------------
# Enumerations (PRD §3)
# --------------------------------------------------------------------------
class CedentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FinancialRating(str, Enum):
    A_PLUS = "A_PLUS"
    A = "A"
    B_PLUS = "B_PLUS"
    B = "B"


class SecurityRating(str, Enum):
    AAA = "AAA"
    AA = "AA"
    A = "A"
    BBB = "BBB"
    BB = "BB"


class SecurityStatus(str, Enum):
    APPROVED = "APPROVED"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class LineOfBusiness(str, Enum):
    PROPERTY = "PROPERTY"
    CASUALTY = "CASUALTY"
    MARINE = "MARINE"
    MOTOR = "MOTOR"


class SigndownMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    LEAD_PROTECTED = "LEAD_PROTECTED"


class PlacementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMISSION_READY = "SUBMISSION_READY"
    IN_MARKET = "IN_MARKET"
    FIRM_ORDER = "FIRM_ORDER"
    BOUND = "BOUND"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class DocumentationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SLIP_ISSUED = "SLIP_ISSUED"
    WORDING_DRAFTED = "WORDING_DRAFTED"
    WORDING_AGREED = "WORDING_AGREED"
    EXECUTED = "EXECUTED"
    CERTAINTY_BREACHED = "CERTAINTY_BREACHED"


class ExposureSubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTUARY_REVIEW = "ACTUARY_REVIEW"
    SIGNED_OFF = "SIGNED_OFF"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class SignoffDecision(str, Enum):
    SIGNED_OFF = "SIGNED_OFF"
    REJECTED = "REJECTED"


class LayerType(str, Enum):
    QUOTA_SHARE = "QUOTA_SHARE"
    EXCESS_OF_LOSS = "EXCESS_OF_LOSS"
    CATASTROPHE = "CATASTROPHE"


class LayerStatus(str, Enum):
    OPEN = "OPEN"
    IN_MARKET = "IN_MARKET"
    PARTIALLY_PLACED = "PARTIALLY_PLACED"
    FULLY_PLACED = "FULLY_PLACED"
    OVERSUBSCRIBED = "OVERSUBSCRIBED"
    SIGNED_DOWN = "SIGNED_DOWN"
    BOUND = "BOUND"
    LAPSED = "LAPSED"


class MarketSubmissionStatus(str, Enum):
    SENT = "SENT"
    QUOTED = "QUOTED"
    DECLINED = "DECLINED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class QuoteStatus(str, Enum):
    QUOTED = "QUOTED"
    COUNTERED = "COUNTERED"
    REQUOTED = "REQUOTED"
    FIRM_ORDER = "FIRM_ORDER"
    DECLINED = "DECLINED"
    LAPSED = "LAPSED"
    BOUND = "BOUND"


class SigningLineStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    SIGNED = "SIGNED"
    BOUND = "BOUND"
    RELEASED = "RELEASED"


class ReleaseReason(str, Enum):
    WITHDRAWN_BY_BROKER = "WITHDRAWN_BY_BROKER"
    SECURITY_FAILURE = "SECURITY_FAILURE"
    SIGNDOWN_ZEROED = "SIGNDOWN_ZEROED"
    PROGRAM_WITHDRAWN = "PROGRAM_WITHDRAWN"


class DocumentType(str, Enum):
    SLIP = "SLIP"
    WORDING_DRAFT = "WORDING_DRAFT"
    AGREED_WORDING = "AGREED_WORDING"
    EXECUTED_CONTRACT = "EXECUTED_CONTRACT"


class DisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    DISCLOSED = "DISCLOSED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"


class DisclosureDecision(str, Enum):
    ACKNOWLEDGE = "ACKNOWLEDGE"
    REJECT = "REJECT"


class TransactionType(str, Enum):
    CEDENT_RECEIPT = "CEDENT_RECEIPT"
    CLAIM_COLLECTION = "CLAIM_COLLECTION"
    REMITTANCE_REVERSAL = "REMITTANCE_REVERSAL"
    REINSURER_REMITTANCE = "REINSURER_REMITTANCE"
    BROKERAGE_DEDUCTION = "BROKERAGE_DEDUCTION"
    REINSTATEMENT_PREMIUM = "REINSTATEMENT_PREMIUM"
    CEDENT_PAYOUT = "CEDENT_PAYOUT"


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    HELD = "HELD"
    REVERSED = "REVERSED"


class HoldReason(str, Enum):
    CONTRACT_CERTAINTY_BREACHED = "CONTRACT_CERTAINTY_BREACHED"


class AdvocacyStatus(str, Enum):
    NOTIFIED = "NOTIFIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DISPUTED = "DISPUTED"
    ADVOCACY_NEGOTIATION = "ADVOCACY_NEGOTIATION"
    ADVOCACY_ARBITRATION = "ADVOCACY_ARBITRATION"
    RESOLVED = "RESOLVED"
    COLLECTED = "COLLECTED"
    WITHDRAWN = "WITHDRAWN"


class AdvocacyRoute(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    ARBITRATION = "ARBITRATION"


class DisputeReason(str, Enum):
    EXCLUSION_APPLIES = "EXCLUSION_APPLIES"
    LATE_NOTIFICATION = "LATE_NOTIFICATION"
    AGGREGATION_DISAGREEMENT = "AGGREGATION_DISAGREEMENT"
    WORDING_AMBIGUITY = "WORDING_AMBIGUITY"


class DisputeStatus(str, Enum):
    RAISED = "RAISED"
    UPHELD = "UPHELD"
    WITHDRAWN = "WITHDRAWN"
    SETTLED_PARTIAL = "SETTLED_PARTIAL"


class DisputeResolution(str, Enum):
    UPHELD = "UPHELD"
    WITHDRAWN = "WITHDRAWN"
    SETTLED_PARTIAL = "SETTLED_PARTIAL"


# --------------------------------------------------------------------------
# Resources carrying id + created_at + updated_at + version (PRD §2.5)
# --------------------------------------------------------------------------
class Cedent(TypedDict):
    id: str
    name: str
    domicile_code: str
    financial_rating: str
    status: str
    suspension_reason: Optional[str]
    settled_receipts_minor: int
    outstanding_reinstatement_premium_minor: int
    created_at: str
    updated_at: str
    version: int


class Reinsurer(TypedDict):
    id: str
    name: str
    security_rating: str
    capacity_limit_minor: int
    max_line_pct: float
    lead_authorised: bool
    security_status: str
    committed_capacity_minor: int
    available_capacity_minor: int
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    cedent_id: str
    prior_program_id: Optional[str]
    program_name: str
    line_of_business: str
    underwriting_year: int
    inception_date: str
    expiry_date: str
    currency_code: str
    estimated_premium_income_minor: int
    brokerage_pct: float
    signdown_method: str
    placement_status: str
    documentation_status: str
    contract_certainty_deadline: str
    disclosure_acknowledged: bool
    gross_written_premium_minor: int
    brokerage_earned_minor: int
    net_remittance_minor: int
    rounding_residue_minor: int
    fiduciary_holding_minor: int
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExposureSubmission(TypedDict):
    id: str
    program_id: str
    package_label: str
    exposure_records_count: int
    data_quality_flags_count: int
    historical_years_supplied: int
    cat_model_version: str
    loss_history_completeness_pct: float
    actuarial_report_attached: bool
    completeness_score: float
    status: str
    actuary_signoff_user_id: Optional[str]
    signed_off_at: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Layer(TypedDict):
    id: str
    program_id: str
    layer_label: str
    layer_type: str
    attachment_minor: int
    limit_minor: int
    cession_pct: float
    base_rate_pct: float
    subject_premium_base_minor: int
    expected_loss_cost_minor: int
    reinstatements_total: int
    reinstatement_premium_pct: float
    sublimit_minor: int
    ceding_commission_pct: float
    excluded_perils: List[str]
    quoted_gross_premium_minor: int
    written_line_total_pct: float
    signed_line_total_pct: float
    limit_eroded_minor: int
    reinstatements_used: int
    incurred_ceded_minor: int
    loss_ratio_pct: Optional[float]
    provisional_ceding_commission_minor: Optional[int]
    final_ceding_commission_minor: Optional[int]
    ceding_commission_delta_minor: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketSubmission(TypedDict):
    id: str
    layer_id: str
    reinsurer_id: str
    response_deadline: str
    submitted_by_user_id: str
    sent_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    market_submission_id: str
    layer_id: str
    reinsurer_id: str
    offered_line_pct: float
    quoted_rate_pct: float
    ceding_commission_pct: float
    reinstatements_offered: int
    sublimit_minor: int
    additional_exclusions: List[str]
    is_lead: bool
    expires_at: str
    negotiation_round: int
    last_counter_note: Optional[str]
    accepted_line_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class SigningLine(TypedDict):
    id: str
    layer_id: str
    quote_id: str
    reinsurer_id: str
    written_line_pct: float
    signed_line_pct: Optional[float]
    effective_line_pct: float
    committed_capacity_minor: int
    status: str
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BrokerageDisclosure(TypedDict):
    id: str
    program_id: str
    brokerage_pct: float
    contingent_commission_pct: float
    market_service_fee_minor: int
    disclosed_by_user_id: Optional[str]
    acknowledged_by_user_id: Optional[str]
    decision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FiduciaryTransaction(TypedDict):
    id: str
    program_id: str
    signing_line_id: Optional[str]
    reverses_transaction_id: Optional[str]
    txn_type: str
    amount_minor: int
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    value_date: Optional[str]
    hold_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimAdvocacy(TypedDict):
    id: str
    layer_id: str
    claim_reference: str
    event_date: str
    gross_claim_minor: int
    ceded_claim_minor: int
    disputed_minor: int
    collected_minor: int
    collectible_minor: int
    advocacy_route: Optional[str]
    arbitration_cost_minor: int
    reinstatement_triggered: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CessionDispute(TypedDict):
    id: str
    claim_advocacy_id: str
    signing_line_id: str
    disputed_minor: int
    dispute_reason: str
    settled_minor: Optional[int]
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only evidence records: only id + created_at (PRD §2.5)
# --------------------------------------------------------------------------
class ContractDocument(TypedDict):
    id: str
    program_id: str
    document_type: str
    wording_reference: str
    issued_at: str
    days_from_inception: int
    filed_by_user_id: str
    created_at: str


class RenewalReport(TypedDict):
    id: str
    program_id: str
    current_rate_on_line_pct: float
    prior_rate_on_line_pct: Optional[float]
    rate_change_pct: Optional[float]
    exposure_change_pct: Optional[float]
    risk_adjusted_rate_change_pct: Optional[float]
    placement_efficiency_pct: float
    market_condition_index: Optional[float]
    generated_by_user_id: str
    as_of: str
    created_at: str
