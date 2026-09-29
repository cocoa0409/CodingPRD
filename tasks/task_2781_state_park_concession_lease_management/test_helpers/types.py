"""Domain types for the State Park Concession Lease Management API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import Optional, TypedDict


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────
class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    CONCESSION_SPECIALIST = "ConcessionSpecialist"
    CONTRACTING_OFFICER = "ContractingOfficer"
    EVALUATION_PANELIST = "EvaluationPanelist"
    AUDITOR_GENERAL = "AuditorGeneral"
    CONCESSIONAIRE = "Concessionaire"


ALL_ROLES = [r.value for r in UserRole]


# ─── Status enums ──────────────────────────────────────────────────────────
class ParkStatus(str, Enum):
    OPERATING = "OPERATING"
    CLOSED = "CLOSED"


class OpportunityStatus(str, Enum):
    DRAFT = "DRAFT"
    ANALYSIS_COMPLETE = "ANALYSIS_COMPLETE"
    APPROVED_FOR_SOLICITATION = "APPROVED_FOR_SOLICITATION"
    SOLICITED = "SOLICITED"
    AWARDED = "AWARDED"


class ProspectusStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"
    AWARDED = "AWARDED"


class OfferorStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    DEBARRED = "DEBARRED"


class ProposalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SCORED = "SCORED"
    SELECTED = "SELECTED"
    NOT_SELECTED = "NOT_SELECTED"
    WITHDRAWN = "WITHDRAWN"


class LeaseContractStatus(str, Enum):
    PENDING_EXECUTION = "PENDING_EXECUTION"
    ACTIVE = "ACTIVE"
    HOLDOVER = "HOLDOVER"
    EXPIRED = "EXPIRED"
    CLOSED_OUT = "CLOSED_OUT"
    TERMINATED_DEFAULT = "TERMINATED_DEFAULT"


class LeaseComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"
    DEFAULT = "DEFAULT"


class BondStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PARTIALLY_DRAWN = "PARTIALLY_DRAWN"
    INSUFFICIENT = "INSUFFICIENT"
    RELEASED = "RELEASED"


class ImprovementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    VESTED_IN_AGENCY = "VESTED_IN_AGENCY"
    COMPENSABLE = "COMPENSABLE"
    WITHDRAWN = "WITHDRAWN"


class OperatingPlanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    RESTATED = "RESTATED"


class ReconciliationStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    SETTLED = "SETTLED"
    CREDIT_ISSUED = "CREDIT_ISSUED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class AuditStatus(str, Enum):
    OPENED = "OPENED"
    FIELDWORK = "FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CONTESTED = "CONTESTED"
    FINAL = "FINAL"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"


class ComplianceActionStatus(str, Enum):
    NOTICE_ISSUED = "NOTICE_ISSUED"
    CURE_ACCEPTED = "CURE_ACCEPTED"
    BOND_DRAW_ORDERED = "BOND_DRAW_ORDERED"
    RESCINDED = "RESCINDED"


class ComplianceActionOrigin(str, Enum):
    AGENCY_ISSUED = "AGENCY_ISSUED"
    SYSTEM_ISSUED = "SYSTEM_ISSUED"


# ─── Entity shapes (PRD §2.5: most records carry id/created_at/updated_at/version;
#     the panel score sheet carries only id and created_at) ──────────────────
class Park(TypedDict):
    id: str
    name: str
    region_code: str
    annual_visitation: int
    comparable_lodging_rate_cents: int
    comparable_meal_rate_cents: int
    comparable_activity_rate_cents: int
    open_closure_window_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConcessionOpportunity(TypedDict):
    id: str
    park_id: str
    title: str
    service_category: str
    required_capital_investment_cents: int
    comparable_gross_receipts_cents: Optional[int]
    market_capture_pct: Optional[float]
    estimated_annual_gross_receipts_cents: Optional[int]
    analyst_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Prospectus(TypedDict):
    id: str
    opportunity_id: str
    minimum_franchise_fee_pct: float
    minimum_annual_guarantee_cents: int
    term_years: int
    submission_deadline: str
    weight_experience: int
    weight_operating_plan: int
    weight_capital_investment: int
    weight_financial_capacity: int
    weight_fee_offer: int
    scoring_mode: str
    min_technical_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Offeror(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    bond_capacity_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict):
    id: str
    prospectus_id: str
    offeror_id: str
    offered_franchise_fee_pct: float
    proposed_capital_investment_cents: int
    proposed_annual_guarantee_cents: int
    experience_years: int
    financial_capacity_ratio: float
    revision_round: int
    evaluation_count: int
    composite_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProposalEvaluation(TypedDict):
    # Append-only and immutable (PRD §2.5): no updated_at, no version.
    id: str
    proposal_id: str
    panelist_user_id: str
    score_experience: int
    score_operating_plan: int
    score_capital_investment: int
    score_financial_capacity: int
    score_fee_offer: int
    created_at: str


class Lease(TypedDict):
    id: str
    park_id: str
    prospectus_id: str
    offeror_id: str
    selected_proposal_id: str
    predecessor_lease_id: Optional[str]
    performance_bond_id: str
    awarded_by_user_id: str
    executed_by_user_id: Optional[str]
    base_fee_pct: float
    minimum_annual_guarantee_cents: int
    capital_investment_obligation_cents: int
    term_years: int
    term_start: str
    term_end: str
    required_bond_amount_cents: int
    agency_maintenance_scope: str
    insurance_expires_on: Optional[str]
    carrier_name: Optional[str]
    capital_investment_completed_cents: int
    reported_receipts_ytd_cents: int
    remitted_fee_ytd_cents: int
    maintenance_reserve_balance_cents: int
    outstanding_fee_balance_cents: int
    possessory_interest_value_cents: Optional[int]
    transfer_settlement_net_cents: Optional[int]
    transfer_settlement_deficiency_cents: Optional[int]
    contract_status: str
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceBond(TypedDict):
    id: str
    lease_id: str
    required_amount_cents: int
    surety_name: Optional[str]
    penal_sum_cents: Optional[int]
    available_balance_cents: int
    drawn_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalImprovement(TypedDict):
    id: str
    lease_id: str
    park_id: str
    description: str
    funding_source: str
    proposed_cost_cents: int
    approved_cost_cents: Optional[int]
    actual_cost_cents: Optional[int]
    useful_life_years: int
    construction_window_start: str
    construction_window_end: str
    in_service_date: Optional[str]
    ownership_at_expiration: str
    unamortized_value_cents: Optional[int]
    deficiency_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OperatingPlan(TypedDict):
    id: str
    lease_id: str
    season_start: str
    season_end: str
    service_level: str
    max_lodging_rate_cents: int
    max_meal_rate_cents: int
    max_activity_rate_cents: int
    deficiency_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GrossReceiptsReport(TypedDict):
    id: str
    lease_id: str
    operating_plan_id: str
    period_start: str
    period_end: str
    lodging_receipts_cents: int
    food_beverage_receipts_cents: int
    retail_receipts_cents: int
    activity_receipts_cents: int
    total_receipts_cents: int
    assessed_fee_cents: int
    maintenance_reserve_due_cents: int
    remittance_received_cents: Optional[int]
    restated_receipts_cents: Optional[int]
    rejection_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeReconciliation(TypedDict):
    id: str
    lease_id: str
    audit_engagement_id: Optional[str]
    superseded_by_id: Optional[str]
    lease_year_number: int
    lease_year_start: str
    lease_year_end: str
    annual_gross_receipts_cents: int
    annual_fee_due_cents: int
    mag_applied_cents: int
    remitted_total_cents: int
    base_delta_cents: int
    penalty_cents: int
    interest_cents: int
    additional_fee_due_cents: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditEngagement(TypedDict):
    id: str
    lease_id: str
    audit_period_start: str
    audit_period_end: str
    scope_note: str
    reported_gross_receipts_cents: Optional[int]
    adjusted_gross_receipts_cents: Optional[int]
    underreport_pct: Optional[float]
    penalty_applies: bool
    finding_note: Optional[str]
    contest_basis: Optional[str]
    withdrawal_basis: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceAction(TypedDict):
    id: str
    lease_id: str
    reconciliation_id: Optional[str]
    action_type: str
    origin: str
    deficiency_note: str
    cure_deadline: str
    cure_note: Optional[str]
    draw_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
