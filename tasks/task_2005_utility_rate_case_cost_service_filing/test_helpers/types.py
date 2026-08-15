"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class RateCaseStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    DEFICIENT = "DEFICIENT"
    ACCEPTED = "ACCEPTED"
    DISCOVERY = "DISCOVERY"
    HEARING = "HEARING"
    SETTLEMENT = "SETTLEMENT"
    ORDER_PENDING = "ORDER_PENDING"
    DECIDED = "DECIDED"
    RATES_IMPLEMENTED = "RATES_IMPLEMENTED"
    COMPLIANCE_MONITORING = "COMPLIANCE_MONITORING"
    CLOSED = "CLOSED"


class IntervenorStatus(str, Enum):
    PARTY = "PARTY"
    WITHDRAWN = "WITHDRAWN"


class TestYearEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"


class AdjustmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class RateBaseItemStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    AUDITED = "AUDITED"
    EXCEPTION = "EXCEPTION"


class DataRequestStatus(str, Enum):
    ISSUED = "ISSUED"
    OBJECTED = "OBJECTED"
    RESPOND_REQUIRED = "RESPOND_REQUIRED"
    OVERDUE = "OVERDUE"
    RESPONDED = "RESPONDED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class SettlementProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_NEGOTIATION = "UNDER_NEGOTIATION"
    ASSENTED = "ASSENTED"
    RECOMMENDED = "RECOMMENDED"
    ADOPTED = "ADOPTED"
    REMANDED = "REMANDED"
    SUPERSEDED = "SUPERSEDED"


class SettlementSignatoryStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    DECLINED = "DECLINED"
    RESCINDED = "RESCINDED"
    VOID = "VOID"


class RegulatoryAssetStatus(str, Enum):
    DEFERRED = "DEFERRED"
    APPROVED_FOR_AMORTIZATION = "APPROVED_FOR_AMORTIZATION"
    AMORTIZING = "AMORTIZING"
    FULLY_AMORTIZED = "FULLY_AMORTIZED"
    DISALLOWED = "DISALLOWED"


class AmortizationEntryStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class TariffRateStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class ComplianceFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REMANDED = "REMANDED"
    SUPERSEDED = "SUPERSEDED"


class UserRole(str, Enum):
    UTILITY_FILER = "UtilityFiler"
    COMMISSION_STAFF = "CommissionStaff"
    INTERVENOR_REP = "IntervenorRep"
    ALJ = "ALJ"


class Tier(TypedDict):
    up_to_kwh: Optional[int]
    rate_mills: int


class RateCase(TypedDict, total=False):
    id: str
    case_number: str
    utility_name: str
    test_year_start: str
    test_year_end: str
    return_on_rate_base_bp: int
    proposed_revenue_requirement_cents: int
    allocation_method: str
    discovery_close_at: Optional[str]
    authorized_revenue_requirement_cents: Optional[int]
    present_revenue_total_cents: int
    revenue_requirement_as_filed_cents: int
    revenue_requirement_as_audited_cents: int
    revenue_at_approved_rates_cents: int
    overdue_data_request_count: int
    assented_proposal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Intervenor(TypedDict, total=False):
    id: str
    rate_case_id: str
    party_name: str
    representative_name: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TestYearEntry(TypedDict, total=False):
    id: str
    rate_case_id: str
    account_code: str
    category: str
    booked_amount_cents: int
    adjusted_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Adjustment(TypedDict, total=False):
    id: str
    rate_case_id: str
    test_year_entry_id: str
    amount_cents: int
    reason: str
    proposed_by_user_id: str
    verified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RateBaseItem(TypedDict, total=False):
    id: str
    rate_case_id: str
    label: str
    plant_in_service_cents: int
    accumulated_depreciation_cents: int
    working_capital_cents: int
    accumulated_deferred_taxes_cents: int
    net_rate_base_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerClass(TypedDict, total=False):
    id: str
    rate_case_id: str
    class_code: str
    customer_count: int
    monthly_kwh_per_customer: int
    annual_kwh: int
    coincident_peak_kw: int
    average_demand_kw: int
    present_customer_charge_cents: int
    present_tiers: List[Tier]
    present_revenue_cents: int
    allocated_cost_cents: int
    approved_revenue_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DataRequest(TypedDict, total=False):
    id: str
    rate_case_id: str
    issuer_kind: str
    issuing_intervenor_id: Optional[str]
    subject: str
    body: str
    referenced_adjustment_id: Optional[str]
    issued_at: str
    response_due_at: str
    extended_due_at: Optional[str]
    response_text: Optional[str]
    objection_reason: Optional[str]
    ruling: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementProposal(TypedDict, total=False):
    id: str
    rate_case_id: str
    round_number: int
    proposed_revenue_requirement_cents: int
    terms: str
    signature_count: int
    required_signature_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementSignatory(TypedDict, total=False):
    id: str
    settlement_proposal_id: str
    intervenor_id: str
    signed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryAsset(TypedDict, total=False):
    id: str
    rate_case_id: str
    asset_name: str
    principal_cents: int
    incurrence_start: str
    incurrence_end: str
    amortization_months: int
    monthly_base_cents: int
    final_month_cents: int
    amortized_to_date_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AmortizationEntry(TypedDict, total=False):
    id: str
    regulatory_asset_id: str
    rate_case_id: str
    period_index: int
    amount_cents: int
    posted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TariffRate(TypedDict, total=False):
    id: str
    rate_case_id: str
    customer_class_id: str
    label: str
    proposed_customer_charge_cents: int
    proposed_tiers: List[Tier]
    effective_start: str
    effective_end: Optional[str]
    proposed_revenue_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceFiling(TypedDict, total=False):
    id: str
    rate_case_id: str
    period_label: str
    actual_revenue_by_class: List[Dict[str, Any]]
    actual_total_revenue_cents: int
    true_up_delta_cents: int
    true_up_action: str
    class_true_up_lines: List[Dict[str, Any]]
    supersedes_filing_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
