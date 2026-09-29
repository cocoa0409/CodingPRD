"""Domain types for the Bank-Fintech Partnership Oversight API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_OFFICER = "ProgramOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    RISK_COMMITTEE = "RiskCommittee"
    INTERNAL_AUDIT = "InternalAudit"
    FINTECH_PARTNER = "FintechPartner"


class PartnerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    IN_DILIGENCE = "IN_DILIGENCE"
    DILIGENCE_PASSED = "DILIGENCE_PASSED"
    DILIGENCE_FAILED = "DILIGENCE_FAILED"
    CONTRACTED = "CONTRACTED"
    LIVE = "LIVE"
    WIND_DOWN = "WIND_DOWN"
    TERMINATED = "TERMINATED"


class OversightPosture(str, Enum):
    OPEN = "OPEN"
    HEIGHTENED = "HEIGHTENED"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class CapabilityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    UNRATED = "UNRATED"


class BusinessModel(str, Enum):
    LENDING = "LENDING"
    DEPOSIT_WALLET = "DEPOSIT_WALLET"
    CARD_ISSUING = "CARD_ISSUING"
    PAYMENT_FACILITATION = "PAYMENT_FACILITATION"


class FundingStage(str, Enum):
    SEED = "SEED"
    SERIES_A = "SERIES_A"
    SERIES_B_PLUS = "SERIES_B_PLUS"
    PUBLIC = "PUBLIC"


class DiligenceReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ReviewType(str, Enum):
    INITIAL = "INITIAL"
    RENEWAL = "RENEWAL"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_RISK_APPROVAL = "PENDING_RISK_APPROVAL"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class ResponsibilityOwner(str, Enum):
    BANK = "BANK"
    PARTNER = "PARTNER"
    SHARED = "SHARED"


class OversightRightsLevel(str, Enum):
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"
    FULL_ACCESS = "FULL_ACCESS"


class TerminationTrigger(str, Enum):
    COMPLAINT_RATE = "COMPLAINT_RATE"
    RESERVE_SHORTFALL = "RESERVE_SHORTFALL"
    SANCTIONS_EVENT = "SANCTIONS_EVENT"
    CONCENTRATION_CAP = "CONCENTRATION_CAP"
    GROWTH_BREACH = "GROWTH_BREACH"
    VOLUNTARY = "VOLUNTARY"


class CustodyAccountType(str, Enum):
    FBO_END_USER = "FBO_END_USER"
    RESERVE = "RESERVE"


class CustodyAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class MarketingReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class MaterialType(str, Enum):
    AD = "AD"
    DISCLOSURE = "DISCLOSURE"
    APP_SCREEN = "APP_SCREEN"
    EMAIL = "EMAIL"


class PlacementChannel(str, Enum):
    PAID_SOCIAL = "PAID_SOCIAL"
    SEARCH = "SEARCH"
    IN_APP = "IN_APP"
    DIRECT_MAIL = "DIRECT_MAIL"
    PARTNER_SITE = "PARTNER_SITE"


class DisclosureElement(str, Enum):
    APR = "APR"
    FEE_SCHEDULE = "FEE_SCHEDULE"
    FDIC_SIGNAGE = "FDIC_SIGNAGE"
    BANK_NAME = "BANK_NAME"
    PASS_THROUGH_INSURANCE = "PASS_THROUGH_INSURANCE"
    DISPUTE_RIGHTS = "DISPUTE_RIGHTS"


class RiskFlag(str, Enum):
    MISSING_APR = "MISSING_APR"
    MISSING_FDIC_SIGNAGE = "MISSING_FDIC_SIGNAGE"
    MISSING_DISPUTE_RIGHTS = "MISSING_DISPUTE_RIGHTS"


class ReconciliationStatus(str, Enum):
    UNRECONCILED = "UNRECONCILED"
    MATCHED = "MATCHED"
    VARIANCE_OPEN = "VARIANCE_OPEN"
    VARIANCE_CLEARED = "VARIANCE_CLEARED"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    FUNDED = "FUNDED"
    CLAWED_BACK = "CLAWED_BACK"


class ClawbackReason(str, Enum):
    RECONCILIATION_ERROR = "RECONCILIATION_ERROR"
    PARTNER_FRAUD = "PARTNER_FRAUD"
    RESERVE_BREACH = "RESERVE_BREACH"
    DUPLICATE_FUNDING = "DUPLICATE_FUNDING"


class LedgerEntryType(str, Enum):
    END_USER_CREDIT = "END_USER_CREDIT"
    END_USER_DEBIT = "END_USER_DEBIT"
    RESERVE_FUND = "RESERVE_FUND"
    RESERVE_RELEASE = "RESERVE_RELEASE"
    FEE = "FEE"
    CLAWBACK = "CLAWBACK"
    VARIANCE_ADJUSTMENT = "VARIANCE_ADJUSTMENT"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ROOT_CAUSE_ASSIGNED = "ROOT_CAUSE_ASSIGNED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"


class ComplaintChannel(str, Enum):
    CFPB_PORTAL = "CFPB_PORTAL"
    STATE_AG = "STATE_AG"
    SOCIAL = "SOCIAL"
    BANK_CALL_CENTER = "BANK_CALL_CENTER"
    PARTNER_APP = "PARTNER_APP"
    EMAIL = "EMAIL"


class ComplaintCategory(str, Enum):
    FEES = "FEES"
    DISCLOSURE = "DISCLOSURE"
    ACCOUNT_ACCESS = "ACCOUNT_ACCESS"
    UNAUTHORIZED_TRANSACTION = "UNAUTHORIZED_TRANSACTION"
    CREDIT_REPORTING = "CREDIT_REPORTING"
    SERVICING = "SERVICING"


class ComplaintSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RootCauseCode(str, Enum):
    DISCLOSURE_DEFECT = "DISCLOSURE_DEFECT"
    SYSTEM_OUTAGE = "SYSTEM_OUTAGE"
    FEE_CONFIG_ERROR = "FEE_CONFIG_ERROR"
    KYC_FRICTION = "KYC_FRICTION"
    VENDOR_ERROR = "VENDOR_ERROR"
    PARTNER_TRAINING_GAP = "PARTNER_TRAINING_GAP"


class AlertType(str, Enum):
    STRUCTURING = "STRUCTURING"
    VELOCITY = "VELOCITY"
    SANCTIONS_HIT = "SANCTIONS_HIT"
    ACH_RETURN_RATE = "ACH_RETURN_RATE"


class AlertDisposition(str, Enum):
    OPEN = "OPEN"
    PARTNER_RESPONSE_PENDING = "PARTNER_RESPONSE_PENDING"
    CLEARED = "CLEARED"
    SAR_FILED = "SAR_FILED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class WindDownPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    IN_EXECUTION = "IN_EXECUTION"
    COMPLETED = "COMPLETED"


class EndUserFundsDisposition(str, Enum):
    RETURN_TO_END_USERS = "RETURN_TO_END_USERS"
    TRANSFER_TO_SUCCESSOR_BANK = "TRANSFER_TO_SUCCESSOR_BANK"
    ESCHEAT = "ESCHEAT"


class WindDownMilestone(str, Enum):
    STOP_NEW_ACCOUNTS = "STOP_NEW_ACCOUNTS"
    NOTIFY_END_USERS = "NOTIFY_END_USERS"
    FINAL_SETTLEMENT = "FINAL_SETTLEMENT"
    RETURN_FUNDS = "RETURN_FUNDS"
    CLOSE_CUSTODY = "CLOSE_CUSTODY"


class Partner(TypedDict, total=False):
    id: str
    legal_name: str
    business_model: str
    funding_stage: str
    months_runway: int
    disclosed_complaints_per_10k: float
    end_user_account_count: int
    parent_partner_id: Optional[str]
    status: str
    oversight_posture: str
    capability_tier: str
    latest_composite_score: float
    complaint_rate_bps: int
    concentration_ratio_pct: float
    monthly_growth_pct: float
    growth_breach_count: int
    required_reserve_cents: int
    reserve_shortfall_cents: int
    consecutive_shortfall_cycles: int
    unreconciled_variance_cents: int
    open_sanctions_alert_count: int
    cumulative_paid_out_cents: int
    cumulative_bank_fee_cents: int
    total_complaint_count: int
    open_complaint_count: int
    escalated_complaint_count: int
    resolved_complaint_count: int
    withdrawn_complaint_count: int
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class DiligenceReview(TypedDict, total=False):
    id: str
    partner_id: str
    review_type: str
    business_model_score: int
    funding_score: int
    compliance_capability_score: int
    complaint_history_score: int
    effective_complaint_history_score: int
    composite_score: float
    tier: str
    status: str
    revision_round: int
    requested_info_items: List[str]
    submission_note: Optional[str]
    decision_note: Optional[str]
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramAgreement(TypedDict, total=False):
    id: str
    partner_id: str
    kyc_owner: str
    dispute_owner: str
    marketing_owner: str
    oversight_rights_level: str
    audit_access_notice_days: int
    termination_triggers: List[str]
    monthly_growth_cap_pct: float
    concentration_cap_pct: float
    max_end_user_balance_cents: int
    reserve_requirement_bps: int
    effective_date: str
    status: str
    revision_round: int
    executed_at: Optional[str]
    termination_trigger_fired: Optional[str]
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustodyAccount(TypedDict, total=False):
    id: str
    partner_id: str
    account_type: str
    status: str
    balance_cents: int
    frozen_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketingReview(TypedDict, total=False):
    id: str
    partner_id: str
    agreement_id: str
    material_type: str
    placement_channel: str
    disclosure_elements: List[str]
    apr_disclosed: bool
    fdic_signage_correct: bool
    effective_from: str
    effective_until: str
    risk_flags: List[str]
    status: str
    review_round: int
    change_requests: List[str]
    decision_note: Optional[str]
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict, total=False):
    id: str
    partner_id: str
    window_start: str
    window_end: str
    gross_settlement_cents: int
    interchange_cents: int
    returns_cents: int
    partner_reported_net_cents: int
    bank_reported_net_cents: Optional[int]
    variance_cents: int
    variance_adjustment_cents: int
    root_cause_note: Optional[str]
    reconciliation_status: str
    funding_status: str
    settlement_base_cents: int
    bank_fee_bps_applied: int
    bank_fee_cents: int
    reserve_funding_cents: int
    net_to_partner_cents: int
    shortfall_carry_cents: int
    funded_at: Optional[str]
    funding_reference: Optional[str]
    clawback_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# A LedgerEntry is immutable once written: it carries neither updated_at nor version.
class LedgerEntry(TypedDict, total=False):
    id: str
    partner_id: str
    custody_account_id: str
    entry_type: str
    amount_cents: int
    balance_after_cents: int
    effective_at: str
    sequence_no: int
    memo: str
    settlement_batch_id: Optional[str]
    reversal_of_entry_id: Optional[str]
    created_at: str


class Complaint(TypedDict, total=False):
    id: str
    partner_id: str
    channel: str
    category: str
    severity: str
    received_at: str
    narrative: str
    is_reg_e_dispute: bool
    handling_owner: str
    response_due_at: str
    status: str
    root_cause_code: Optional[str]
    investigation_note: Optional[str]
    escalation_count: int
    redress_cents: int
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransactionMonitoringAlert(TypedDict, total=False):
    id: str
    partner_id: str
    alert_type: str
    triggered_at: str
    transaction_volume_cents: int
    detection_note: str
    sla_due_at: str
    disposition: str
    disposition_note: Optional[str]
    sla_breach_count: int
    disposed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OversightCycle(TypedDict, total=False):
    id: str
    cycle_index: int
    cycle_label: str
    period_start: str
    period_end: str
    status: str
    closing_note: Optional[str]
    partners_frozen_count: int
    marketing_approvals_expired_count: int
    complaints_escalated_count: int
    alerts_reopened_count: int
    growth_breach_partner_count: int
    plans_completed_count: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WindDownPlan(TypedDict, total=False):
    id: str
    partner_id: str
    trigger_reason: str
    end_user_funds_disposition: str
    notice_days: int
    target_completion_date: str
    milestones: List[str]
    status: str
    revision_round: int
    residual_balance_cents: int
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OversightSummary(TypedDict, total=False):
    partner_id: str
    oversight_posture: str
    capability_tier: str
    complaint_rate_bps: int
    concentration_ratio_pct: float
    group_root_partner_id: str
    group_balance_cents: int
    bank_total_fbo_balance_cents: int
    required_reserve_cents: int
    reserve_shortfall_cents: int
    consecutive_shortfall_cycles: int
    growth_breach_count: int
    unreconciled_variance_cents: int
    open_sanctions_alert_count: int
    systemic_root_cause_code: Optional[str]
    last_closed_cycle_index: Optional[int]
