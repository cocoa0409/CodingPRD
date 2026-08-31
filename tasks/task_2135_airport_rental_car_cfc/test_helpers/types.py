"""Domain types for the Airport Rental Car CFC service.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    FACILITY_ADMIN = "FacilityAdmin"
    CONCESSIONAIRE_OPERATOR = "ConcessionaireOperator"
    AUDIT_OFFICER = "AuditOfficer"
    FINANCE_OFFICER = "FinanceOfficer"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------

class BondCoverageStatus(str, Enum):
    SATISFIED = "SATISFIED"
    DEFICIENT = "DEFICIENT"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DELINQUENT = "DELINQUENT"
    COVENANT_BREACH = "COVENANT_BREACH"


class RentTier(str, Enum):
    MAG_FLOOR = "MAG_FLOOR"
    PERCENTAGE = "PERCENTAGE"


class RentSettlementBasis(str, Enum):
    CUMULATIVE_YTD = "CUMULATIVE_YTD"
    MONTHLY_STANDALONE = "MONTHLY_STANDALONE"


class SpaceClass(str, Enum):
    COUNTER = "COUNTER"
    READY_RETURN = "READY_RETURN"


class CounterAssignmentStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class FleetAllocationStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    RELEASED = "RELEASED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_AUDIT = "UNDER_AUDIT"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class RemittanceBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class RemittanceStatus(str, Enum):
    PENDING = "PENDING"
    DELINQUENT = "DELINQUENT"
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"


class ObligationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FUNDED = "FUNDED"
    PAID = "PAID"
    DEFERRED = "DEFERRED"


class ShuttlePeriodStatus(str, Enum):
    OPEN = "OPEN"
    ALLOCATED = "ALLOCATED"


class AllocationBasis(str, Enum):
    TRANSACTION_DAYS = "TRANSACTION_DAYS"
    GROSS_REVENUE = "GROSS_REVENUE"


class ProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    FUNDED = "FUNDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class DisbursementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version (PRD §2.4)
# --------------------------------------------------------------------------

class Facility(TypedDict):
    id: str
    code: str
    name: str
    cfc_rate_per_transaction_day_cents: int
    ds_reserve_requirement_cents: int
    om_reserve_requirement_cents: int
    capital_fund_cap_cents: int
    overflow_lot_stalls: int
    overflow_daily_surcharge_cents: int
    remittance_grace_days: int
    trust_lifetime_received_cents: int
    trust_debt_service_reserve_cents: int
    trust_debt_service_funded_cents: int
    trust_om_reserve_cents: int
    trust_capital_fund_cents: int
    trust_unallocated_cents: int
    trust_encumbered_cents: int
    trust_disbursed_cents: int
    bond_coverage_status: str
    funded_obligation_count: int
    overflow_stalls_allocated: int
    overflow_stalls_available: int
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class Concessionaire(TypedDict):
    id: str
    facility_id: str
    legal_name: str
    brand_code: str
    contact_email: str
    agreement_count: int
    created_at: str
    updated_at: str
    version: int


class ConcessionAgreement(TypedDict):
    id: str
    facility_id: str
    concessionaire_id: str
    contract_year_index: int
    term_start_date: str
    term_end_date: str
    mag_annual_cents: int
    percentage_rent_rate_bps: int
    rent_settlement_basis: str
    contract_status: str
    compliance_status: str
    gross_revenue_ytd_cents: int
    transaction_days_ytd: int
    accepted_report_count: int
    percentage_rent_accrued_cents: int
    rent_billed_to_date_cents: int
    last_installment_cents: int
    rent_tier: str
    mag_shortfall_cents: int
    counter_units_assigned: int
    fleet_stalls_allocated: int
    created_at: str
    updated_at: str
    version: int


class CounterSpace(TypedDict):
    id: str
    facility_id: str
    terminal_code: str
    space_label: str
    space_class: str
    active_assignment_id: Optional[str]
    assignment_count: int
    created_at: str
    updated_at: str
    version: int


class CounterAssignment(TypedDict):
    id: str
    agreement_id: str
    counter_space_id: str
    effective_start_date: str
    effective_end_date: str
    status: str
    released_on_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FleetParkingZone(TypedDict):
    id: str
    facility_id: str
    zone_label: str
    stall_capacity: int
    stalls_allocated: int
    stalls_available: int
    created_at: str
    updated_at: str
    version: int


class FleetAllocation(TypedDict):
    id: str
    agreement_id: str
    zone_id: str
    start_date: str
    end_date: str
    stalls_requested: int
    allow_overflow: bool
    zone_stalls_granted: int
    overflow_stalls_granted: int
    inclusive_days: int
    overflow_surcharge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransactionDayReport(TypedDict):
    id: str
    agreement_id: str
    period_year: int
    period_month: int
    reported_gross_revenue_cents: int
    reported_on_airport_transaction_days: int
    audited_gross_revenue_cents: Optional[int]
    audited_on_airport_transaction_days: Optional[int]
    revenue_variance_cents: Optional[int]
    variance_assessment_cents: int
    period_rent_installment_cents: int
    status: str
    audited_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    submission_count: int
    created_at: str
    updated_at: str
    version: int


class CfcRemittance(TypedDict):
    id: str
    agreement_id: str
    report_id: str
    remittance_basis: str
    expected_amount_cents: int
    amount_received_cents: int
    shortfall_cents: int
    due_date: str
    status: str
    allocated_to_debt_service_cents: int
    allocated_to_om_cents: int
    allocated_to_capital_cents: int
    allocated_to_unallocated_cents: int
    created_at: str
    updated_at: str
    version: int


class DebtServiceObligation(TypedDict):
    id: str
    facility_id: str
    series_label: str
    due_date: str
    amount_due_cents: int
    coverage_requirement_bps: int
    coverage_ratio_at_funding: Optional[float]
    funded_from_reserve_cents: int
    auto_funded: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ShuttleCostPeriod(TypedDict):
    id: str
    facility_id: str
    period_year: int
    period_month: int
    total_cost_cents: int
    allocation_basis: str
    total_basis_value: int
    allocated_total_cents: int
    line_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalProject(TypedDict):
    id: str
    facility_id: str
    predecessor_project_id: Optional[str]
    project_name: str
    budget_cents: int
    disbursed_cents: int
    encumbered_cents: int
    draw_request_count: int
    rejected_draw_count: int
    funding_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalDisbursement(TypedDict):
    id: str
    project_id: str
    amount_cents: int
    memo: Optional[str]
    requested_by_user_id: str
    authorized_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrueUpSettlement(TypedDict):
    id: str
    agreement_id: str
    contract_year_index: int
    final_percentage_rent_cents: int
    mag_cents: int
    rent_billed_cents: int
    audit_assessment_cents: int
    base_true_up_cents: int
    credit_bps: int
    shuttle_credit_cents: int
    net_true_up_cents: int
    amount_paid_cents: int
    issued_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Immutable ledger line — carries ONLY id and created_at (PRD §2.4)
# --------------------------------------------------------------------------

class ShuttleCostAllocation(TypedDict):
    id: str
    shuttle_period_id: str
    agreement_id: str
    basis_value: int
    share_bps: int
    floor_cents: int
    remainder_rank: int
    amount_cents: int
    created_at: str
