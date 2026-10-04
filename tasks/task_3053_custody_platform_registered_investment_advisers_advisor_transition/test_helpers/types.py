"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ADVISOR_OPERATIONS_LEAD = "AdvisorOperationsLead"
    ADVISOR_SUPPORT_ANALYST = "AdvisorSupportAnalyst"
    CUSTODY_OPERATIONS_OFFICER = "CustodyOperationsOfficer"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    INVESTMENT_COMMITTEE_CHAIR = "InvestmentCommitteeChair"
    CLIENT = "Client"


class CustodyAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class FirmPosture(str, Enum):
    OPEN = "OPEN"
    LIMITED = "LIMITED"
    SUSPENDED = "SUSPENDED"
    FROZEN = "FROZEN"


class SupervisionEvidenceStatus(str, Enum):
    CLEAR = "CLEAR"
    DEFICIENT = "DEFICIENT"
    UNKNOWN = "UNKNOWN"


class EntitlementCode(str, Enum):
    TRADING_AUTHORIZATION = "TRADING_AUTHORIZATION"
    MONEY_MOVEMENT = "MONEY_MOVEMENT"
    MODEL_MANAGEMENT = "MODEL_MANAGEMENT"
    BILLING = "BILLING"
    ALTERNATIVE_ASSETS = "ALTERNATIVE_ASSETS"
    DATA_FEED = "DATA_FEED"
    API_ACCESS = "API_ACCESS"


class EntitlementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class HouseholdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BILLING_HELD = "BILLING_HELD"
    CLOSED = "CLOSED"


class AccountType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    JOINT = "JOINT"
    TRUST = "TRUST"
    IRA = "IRA"
    ROTH_IRA = "ROTH_IRA"
    ENTITY = "ENTITY"


class AccountStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class HouseholdingConsent(str, Enum):
    OP_IN = "OP_IN"
    OP_OUT = "OP_OUT"
    NONE = "NONE"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SUBMITTED = "SUBMITTED"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    BASIS_REVIEW = "BASIS_REVIEW"
    CREDITED = "CREDITED"


class TransferMethod(str, Enum):
    ACAT = "ACAT"
    DIRECT_ROLLOVER = "DIRECT_ROLLOVER"
    DTC_NON_ACAT = "DTC_NON_ACAT"


class BasisConfidenceGrade(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class ModelStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REBALANCING = "REBALANCING"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class BlockStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    EXECUTED = "EXECUTED"
    ALLOCATED = "ALLOCATED"
    SETTLED = "SETTLED"
    UNALLOCATED = "UNALLOCATED"


class AllocationSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class AllocationStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    REBATED = "REBATED"
    SETTLED = "SETTLED"


class BillingRunStatus(str, Enum):
    SETTLED = "SETTLED"
    INVOICE_MISMATCH = "INVOICE_MISMATCH"
    REOPENED = "REOPENED"
    VOIDED = "VOIDED"


class FeeVariant(str, Enum):
    HOUSEHOLD_AGGREGATED = "HOUSEHOLD_AGGREGATED"
    PER_ACCOUNT = "PER_ACCOUNT"


class CreditStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    APPLIED = "APPLIED"


class AlternativeAcceptanceStatus(str, Enum):
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class MovementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class MovementType(str, Enum):
    ACH_DISBURSEMENT = "ACH_DISBURSEMENT"
    WIRE = "WIRE"
    JOURNAL = "JOURNAL"
    CHECK = "CHECK"


class InstructionType(str, Enum):
    THIRD_PARTY_DISBURSEMENT = "THIRD_PARTY_DISBURSEMENT"
    WIRE = "WIRE"
    JOURNAL = "JOURNAL"


class InstructionVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class EvidenceRequirementCode(str, Enum):
    QUALIFIED_CUSTODIAN = "QUALIFIED_CUSTODIAN"
    SURPRISE_EXAMINATION = "SURPRISE_EXAMINATION"
    CLIENT_NOTIFICATION = "CLIENT_NOTIFICATION"
    TWO_PARTY_AUTHORIZATION = "TWO_PARTY_AUTHORIZATION"
    FEE_DISCLOSURE = "FEE_DISCLOSURE"
    ANNUAL_ATTESTATION = "ANNUAL_ATTESTATION"
    STANDING_INSTRUCTION_AUTHORIZATION = "STANDING_INSTRUCTION_AUTHORIZATION"
    FEE_CREDIT_DISCLOSURE = "FEE_CREDIT_DISCLOSURE"


class EvidenceStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"
    WAIVED = "WAIVED"
    LAPSED = "LAPSED"


class FeedType(str, Enum):
    POSITIONS = "POSITIONS"
    TRANSACTIONS = "TRANSACTIONS"
    BALANCES = "BALANCES"
    FEES = "FEES"
    ALTERNATIVES = "ALTERNATIVES"


class ProvisionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    THROTTLED = "THROTTLED"
    REVOKED = "REVOKED"


class BatchKind(str, Enum):
    ACCOUNTS = "ACCOUNTS"
    TRANSFERS = "TRANSFERS"
    LOTS = "LOTS"
    EVIDENCE = "EVIDENCE"


class BatchStatus(str, Enum):
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"


class AdminActionKind(str, Enum):
    REGULATORY_FREEZE = "REGULATORY_FREEZE"
    DEFICIENCY_NOTICE = "DEFICIENCY_NOTICE"


class AdminActionStatus(str, Enum):
    UNACKNOWLEDGED = "UNACKNOWLEDGED"
    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class InvariantCode(str, Enum):
    CUSTODY_AGREEMENT_CONSISTENCY = "CUSTODY_AGREEMENT_CONSISTENCY"
    TRANSFER_BASIS_CONSERVATION = "TRANSFER_BASIS_CONSERVATION"
    HOUSEHOLD_FEE_BASIS_RECONCILIATION = "HOUSEHOLD_FEE_BASIS_RECONCILIATION"
    CASCADE_ECONOMIC_EFFECT = "CASCADE_ECONOMIC_EFFECT"


class InvariantStatus(str, Enum):
    HOLDING = "HOLDING"
    BROKEN = "BROKEN"


class EnvelopeMode(str, Enum):
    WARN = "WARN"
    ENFORCED = "ENFORCED"


class BundleStatus(str, Enum):
    ASSEMBLING = "ASSEMBLING"
    GENERATED = "GENERATED"
    INCOMPLETE = "INCOMPLETE"
    SEALED = "SEALED"


# All entities carry id + created_at + updated_at + version.
class AdvisorFirm(TypedDict):
    id: str
    legal_name: str
    crd_number: str
    home_state_code: str
    custody_agreement_status: str
    firm_posture: str
    posture_reason_code: Optional[str]
    agreement_executed_at: Optional[str]
    supervision_evidence_status: str
    entitlement_count: int
    household_fee_basis_total_cents: int
    created_at: str
    updated_at: str
    version: int


class CustodyAgreement(TypedDict):
    id: str
    firm_id: str
    agreement_status: str
    adviser_crd_number: str
    drafted_by_user_id: Optional[str]
    executed_by_user_id: Optional[str]
    signed_at: Optional[str]
    countersignature_hash: Optional[str]
    superseded_by_agreement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdvisorFirmEntitlement(TypedDict):
    id: str
    firm_id: str
    entitlement_code: str
    requested_custody_agreement_id: str
    entitlement_status: str
    effective_from: Optional[str]
    payload_integrity_verified: bool
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict):
    id: str
    firm_id: str
    household_name: str
    household_status: str
    household_fee_basis_cents: int
    household_annual_fee_cents: int
    billing_period_number: int
    created_at: str
    updated_at: str
    version: int


class HouseholdAccount(TypedDict):
    id: str
    household_id: str
    firm_id: str
    account_number: str
    account_type: str
    account_status: str
    market_value_cents: int
    account_fee_basis_cents: int
    billable: bool
    householding_consent: str
    last_listed_cents: Optional[int]
    last_listed_at: Optional[str]
    model_portfolio_id: Optional[str]
    billed_period_count: int
    created_at: str
    updated_at: str
    version: int


class AssetTransfer(TypedDict):
    id: str
    receiving_account_id: str
    firm_id: str
    transfer_status: str
    delivering_firm_name: str
    method: str
    sent_basis_confidence: Optional[str]
    carryover_cents: Optional[int]
    cost_basis_complete: Optional[bool]
    rejected_reason_code: Optional[str]
    credited_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferLot(TypedDict):
    id: str
    transfer_id: str
    symbol: str
    quantity_micros: int
    sent_cost_basis_cents: Optional[int]
    lot_inventory_date: str
    valuation_price_micros: int
    basis_appraisal_cents: Optional[int]
    suspected_double_basis: Optional[bool]
    basis_confidence_grade: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModelPortfolio(TypedDict):
    id: str
    firm_id: str
    model_name: str
    model_status: str
    approval_round_number: int
    drift_approved_at: Optional[str]
    target_weight_total_bps: int
    created_at: str
    updated_at: str
    version: int


class ModelTarget(TypedDict):
    id: str
    model_id: str
    symbol: str
    target_weight_bps: int
    created_at: str
    updated_at: str
    version: int


class BlockOrder(TypedDict):
    id: str
    firm_id: str
    model_id: str
    symbol: str
    side: str
    total_requested_share_micros: int
    executed_share_micros: int
    execution_price_micros: int
    block_status: str
    unallocated_share_micros: Optional[int]
    preview_notional_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BlockAllocation(TypedDict):
    id: str
    block_order_id: str
    account_id: str
    requested_share_micros: int
    share_micros: Optional[int]
    allocation_rank: int
    allocated_cost_cents: Optional[int]
    average_price_micros: Optional[int]
    fee_rebate_cents: Optional[int]
    allocation_status: str
    created_at: str
    updated_at: str
    version: int


class FeeBillingRun(TypedDict):
    id: str
    firm_id: str
    household_id: str
    period_start_date: str
    period_end_date: str
    period_days: int
    billing_run_status: str
    fee_basis_snapshot_cents: int
    fee_variant_used: str
    gross_fee_cents: int
    credit_applied_cents: int
    net_fee_cents: int
    stated_invoice_cents: int
    settlement_evidence_hash: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeCredit(TypedDict):
    id: str
    household_id: str
    credit_cents: int
    earned_on_date: str
    credit_status: str
    applied_to_billing_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AlternativeAssetHolding(TypedDict):
    id: str
    account_id: str
    asset_name: str
    asset_acceptance_status: str
    unit_count: int
    stated_value_cents: int
    accepted_value_cents: Optional[int]
    haircut_pct: Optional[int]
    valuation_floor_cents: int
    valuation_as_of_date: str
    valuation_age_days: Optional[int]
    stale_valuation: Optional[bool]
    fee_basis_eligible: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class MoneyMovementInstruction(TypedDict):
    id: str
    account_id: str
    standing_instruction_id: str
    amount_cents: int
    movement_type: str
    movement_status: str
    authorization_note: str
    jurisdiction_withholding_required: Optional[bool]
    withheld_cents: Optional[int]
    net_disbursed_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StandingInstruction(TypedDict):
    id: str
    account_id: str
    instruction_type: str
    payee_name: str
    periodic_limit_cents: int
    verification_status: str
    verification_token: str
    verified_at: Optional[str]
    round_trip_days: Optional[int]
    consumed_period_cents: int
    created_at: str
    updated_at: str
    version: int


class CustodyRulesEvidence(TypedDict):
    id: str
    firm_id: str
    requirement_code: str
    requirement_status: str
    critical: bool
    drafted_by_user_id: Optional[str]
    accepted_by_user_id: Optional[str]
    evidence_document_hash: Optional[str]
    submitted_at: Optional[str]
    evidence_round_number: int
    created_at: str
    updated_at: str
    version: int


class DataFeedProvision(TypedDict):
    id: str
    firm_id: str
    feed_type: str
    provision_status: str
    provisioned_records_count: int
    delivery_endpoint_host: str
    throttle_reason_code: Optional[str]
    last_delivered_at: Optional[str]
    delivered_count: int
    created_at: str
    updated_at: str
    version: int


class OnboardingBatch(TypedDict):
    id: str
    firm_id: str
    batch_kind: str
    batch_status: str
    chunk_size: Optional[int]
    requested_item_count: int
    dispatched_item_count: int
    skipped_duplicate_count: int
    created_at: str
    updated_at: str
    version: int


class AdminActionLog(TypedDict):
    id: str
    firm_id: str
    admin_action_kind: str
    admin_action_status: str
    admin_action_detail: str
    acknowledged_note: Optional[str]
    acknowledged_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SystemConfig(TypedDict):
    id: str
    config_key: str
    database_invariant_enforcement: str
    platform_fee_enabled: bool
    created_at: str
    updated_at: str
    version: int


class DatabaseInvariant(TypedDict):
    id: str
    firm_id: str
    invariant_code: str
    invariant_status: str
    expected_total_cents: int
    observed_total_cents: int
    breach_detail_code: Optional[str]
    last_evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExaminationBundle(TypedDict):
    id: str
    firm_id: str
    period_start_date: str
    period_end_date: str
    bundle_status: str
    missing_evidence_codes: List[str]
    sealed_evidence_hash: Optional[str]
    generated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int