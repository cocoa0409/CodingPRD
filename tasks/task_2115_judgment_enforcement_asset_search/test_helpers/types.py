"""Domain types for the Judgment Enforcement API: status enums, entity shapes, roles."""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD section 2.1 — exactly six roles, spellings fixed)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CASE_MANAGER = "CaseManager"
    ASSET_INVESTIGATOR = "AssetInvestigator"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CREDITOR = "Creditor"
    DEBTOR = "Debtor"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class JudgmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SATISFIED = "SATISFIED"
    EXPIRED = "EXPIRED"


class EnforcementPosture(str, Enum):
    NONE = "NONE"
    LIEN_PERFECTED = "LIEN_PERFECTED"
    ENFORCING = "ENFORCING"
    STAYED = "STAYED"


class ApplicationOrder(str, Enum):
    STATUTORY_ORDER = "STATUTORY_ORDER"
    PRINCIPAL_FIRST = "PRINCIPAL_FIRST"


class LocateStatus(str, Enum):
    UNLOCATED = "UNLOCATED"
    LOCATED = "LOCATED"
    STALE = "STALE"


class CountyFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RECORDED = "RECORDED"
    REJECTED = "REJECTED"
    RELEASED = "RELEASED"
    LAPSED = "LAPSED"


class FilingType(str, Enum):
    ABSTRACT_OF_JUDGMENT = "ABSTRACT_OF_JUDGMENT"
    JUDGMENT_LIEN = "JUDGMENT_LIEN"


class AssetFindingStatus(str, Enum):
    OPEN = "OPEN"
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    EXHAUSTED = "EXHAUSTED"


class AssetType(str, Enum):
    REAL_PROPERTY = "REAL_PROPERTY"
    BANK_ACCOUNT = "BANK_ACCOUNT"
    EMPLOYMENT = "EMPLOYMENT"
    VEHICLE = "VEHICLE"


class AssetSource(str, Enum):
    SKIP_TRACE = "SKIP_TRACE"
    PUBLIC_RECORD = "PUBLIC_RECORD"
    CREDIT_HEADER = "CREDIT_HEADER"
    DEBTOR_EXAM = "DEBTOR_EXAM"


class EnforcementActionStatus(str, Enum):
    DRAFT = "DRAFT"
    WRIT_REQUESTED = "WRIT_REQUESTED"
    SERVED = "SERVED"
    SUSPENDED = "SUSPENDED"
    COLLECTED = "COLLECTED"
    RELEASED = "RELEASED"
    QUASHED = "QUASHED"


class ActionType(str, Enum):
    WAGE_GARNISHMENT = "WAGE_GARNISHMENT"
    BANK_LEVY = "BANK_LEVY"


class ExemptionClaimStatus(str, Enum):
    FILED = "FILED"
    OPPOSED = "OPPOSED"
    SUSTAINED = "SUSTAINED"
    OVERRULED = "OVERRULED"
    DEFAULTED = "DEFAULTED"


class ClaimType(str, Enum):
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"
    SOCIAL_SECURITY = "SOCIAL_SECURITY"
    WAGE_CAP = "WAGE_CAP"
    HOMESTEAD = "HOMESTEAD"


class ExaminationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SERVED = "SERVED"
    HELD = "HELD"
    NO_SHOW = "NO_SHOW"


class SubpoenaStatus(str, Enum):
    NOT_ISSUED = "NOT_ISSUED"
    ISSUED = "ISSUED"
    SERVED = "SERVED"
    EXPIRED = "EXPIRED"


class SubpoenaRecipientType(str, Enum):
    DEBTOR = "DEBTOR"
    THIRD_PARTY_BANK = "THIRD_PARTY_BANK"
    EMPLOYER = "EMPLOYER"


class ExaminationOutcome(str, Enum):
    HELD = "HELD"
    NO_SHOW = "NO_SHOW"
    CONTINUED = "CONTINUED"


class SettlementOfferStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    COUNTERED = "COUNTERED"


class OfferedBy(str, Enum):
    CREDITOR = "CREDITOR"
    DEBTOR = "DEBTOR"


class OfferKind(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    INSTALLMENT = "INSTALLMENT"


class InstallmentAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class PaymentStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class PaymentSource(str, Enum):
    DEBTOR_DIRECT = "DEBTOR_DIRECT"
    GARNISHMENT = "GARNISHMENT"
    LEVY = "LEVY"
    SETTLEMENT = "SETTLEMENT"


class AdjudicationOutcome(str, Enum):
    RECORDED = "RECORDED"
    REJECTED = "REJECTED"


class RulingOutcome(str, Enum):
    SUSTAINED = "SUSTAINED"
    OVERRULED = "OVERRULED"


# --------------------------------------------------------------------------
# Entity shapes.  All eleven object types carry the full common set
# (id, created_at, updated_at, version) per PRD section 2.4.
# --------------------------------------------------------------------------
class Creditor(TypedDict):
    id: str
    name: str
    contact_email: str
    active_judgment_count: int
    created_at: str
    updated_at: str
    version: int


class Debtor(TypedDict):
    id: str
    full_name: str
    state_code: str
    head_of_household: bool
    weekly_disposable_earnings_cents: int
    locate_status: str
    skip_trace_count: int
    last_skip_trace_on: Optional[str]
    no_show_count: int
    recoverability_score: int
    certified_recoverability_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Judgment(TypedDict):
    id: str
    creditor_id: str
    debtor_id: str
    court_case_number: str
    state_code: str
    original_principal_cents: int
    interest_rate_bps: int
    entered_on: str
    filing_costs_cents: int
    expires_on: str
    status: str
    enforcement_posture: str
    application_order: str
    principal_balance_cents: int
    accrued_interest_cents: int
    costs_balance_cents: int
    total_payoff_cents: int
    gross_exposure_cents: int
    accrued_through_on: str
    collected_to_date_cents: int
    forgiven_cents: int
    contingency_fee_cents: int
    net_to_creditor_cents: int
    renewal_count: int
    renewal_dates: List[str]
    active_enforcement_count: int
    open_offer_count: int
    perfected_county_count: int
    created_at: str
    updated_at: str
    version: int


class CountyFiling(TypedDict):
    id: str
    judgment_id: str
    county_code: str
    state_code: str
    filing_type: str
    fee_cents: int
    status: str
    submitted_on: Optional[str]
    recorded_on: Optional[str]
    lien_expires_on: Optional[str]
    priority_rank: Optional[int]
    rejection_count: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssetFinding(TypedDict):
    id: str
    judgment_id: str
    asset_type: str
    institution_name: str
    identifier_last4: str
    estimated_value_cents: int
    source: str
    status: str
    available_cents: int
    frozen_cents: int
    swept_cents: int
    verified_by_user_id: Optional[str]
    verified_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict):
    id: str
    judgment_id: str
    asset_finding_id: str
    action_type: str
    status: str
    writ_requested_on: Optional[str]
    writ_requested_by_user_id: Optional[str]
    served_on: Optional[str]
    expires_on: Optional[str]
    weekly_withholding_cents: int
    levy_hold_cents: int
    collected_cents: int
    sheriff_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ExemptionClaim(TypedDict):
    id: str
    enforcement_action_id: str
    claim_type: str
    claimed_amount_cents: int
    status: str
    filed_on: str
    filing_deadline_on: str
    opposition_deadline_on: str
    opposed_on: Optional[str]
    opposed_by_user_id: Optional[str]
    ruled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DebtorExamination(TypedDict):
    id: str
    judgment_id: str
    scheduled_at: str
    status: str
    served_on: Optional[str]
    outcome_recorded_on: Optional[str]
    continuance_count: int
    subpoena_status: str
    subpoena_recipient_type: Optional[str]
    subpoena_recipient_name: Optional[str]
    subpoena_service_deadline_on: str
    created_at: str
    updated_at: str
    version: int


class SettlementOffer(TypedDict):
    id: str
    judgment_id: str
    offered_by: str
    kind: str
    amount_cents: int
    installment_count: int
    monthly_cents: int
    min_acceptable_cents: int
    application_order_concession: str
    responds_to_offer_id: Optional[str]
    round_number: int
    status: str
    expires_at: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InstallmentAgreement(TypedDict):
    id: str
    judgment_id: str
    settlement_offer_id: str
    total_cents: int
    installment_count: int
    monthly_cents: int
    final_installment_cents: int
    first_due_on: str
    application_order_concession: str
    paid_to_date_cents: int
    missed_count: int
    reinstatement_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    judgment_id: str
    installment_agreement_id: Optional[str]
    enforcement_action_id: Optional[str]
    amount_cents: int
    received_on: str
    source: str
    status: str
    applied_to_costs_cents: int
    applied_to_interest_cents: int
    applied_to_principal_cents: int
    contingency_fee_cents: int
    reversal_reason: Optional[str]
    reversed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int
