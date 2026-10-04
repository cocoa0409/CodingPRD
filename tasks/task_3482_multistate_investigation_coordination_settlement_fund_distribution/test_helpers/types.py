"""Domain types: entity TypedDicts, status enums, role enum.

All resources in this API carry the four common system-managed properties
(id, created_at, updated_at, version) per PRD §2.5.
"""
from enum import Enum
from typing import Dict, List, Optional, TypedDict


# ── Roles (PRD §2.1) ──────────────────────────────────────────────────────
class UserRole(str, Enum):
    COMMITTEE_CHAIR = "CommitteeChair"
    LEAD_STATE_AG = "LeadStateAG"
    PARTICIPATING_STATE_AG = "ParticipatingStateAG"
    DEFENDANT_COUNSEL = "DefendantCounsel"
    FUND_ADMINISTRATOR = "FundAdministrator"
    STATE_LEGISLATURE = "StateLegislature"
    COMPLIANCE_MONITOR = "ComplianceMonitor"


# ── Enums ─────────────────────────────────────────────────────────────────
class AppropriationRule(str, Enum):
    PREAPPROPRIATED = "PREAPPROPRIATED"
    CERTIFICATION_REQUIRED = "CERTIFICATION_REQUIRED"
    GENERAL_FUND_ONLY = "GENERAL_FUND_ONLY"


class InvestigationPhase(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    DISCOVERY = "DISCOVERY"
    NEGOTIATION = "NEGOTIATION"
    SETTLEMENT_PENDING = "SETTLEMENT_PENDING"
    SETTLED = "SETTLED"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"


class ParticipationStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class CiaStatus(str, Enum):
    NOT_EXECUTED = "NOT_EXECUTED"
    EXECUTED = "EXECUTED"


class CiaTier(str, Enum):
    STANDARD = "STANDARD"
    RESTRICTED = "RESTRICTED"
    LEAD_ONLY = "LEAD_ONLY"


class CommitteeRole(str, Enum):
    MEMBER = "MEMBER"
    LEAD = "LEAD"


class DemandStatus(str, Enum):
    ISSUED = "ISSUED"
    CONSOLIDATED = "CONSOLIDATED"


class ResponseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    FULFILLED = "FULFILLED"


class AllocationBasis(str, Enum):
    POPULATION = "POPULATION"
    HARM_MEASURE = "HARM_MEASURE"
    NEGOTIATED = "NEGOTIATED"


class SettlementTermStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    TERMS_AGREED = "TERMS_AGREED"
    SIGN_ON_OPEN = "SIGN_ON_OPEN"
    EXECUTED = "EXECUTED"
    COLLAPSED = "COLLAPSED"
    CLOSED_OUT = "CLOSED_OUT"


class FundStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    FUNDED = "FUNDED"
    DISBURSING = "DISBURSING"
    DISBURSED = "DISBURSED"


class SignOnDecision(str, Enum):
    SIGNED = "SIGNED"
    DECLINED = "DECLINED"


class SignOnStatus(str, Enum):
    SIGNED = "SIGNED"
    DECLINED = "DECLINED"
    LOCKED = "LOCKED"
    LAPSED = "LAPSED"


class AllocationLineStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    DISBURSING = "DISBURSING"
    DISBURSED = "DISBURSED"
    REVERTED = "REVERTED"


class UseCode(str, Enum):
    PROGRAM = "PROGRAM"
    GENERAL_FUND = "GENERAL_FUND"
    RESTITUTION_ADMIN = "RESTITUTION_ADMIN"


class DisbursementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CERTIFIED = "CERTIFIED"
    RELEASED = "RELEASED"
    HELD = "HELD"
    REVERTED = "REVERTED"


class ClaimantStatus(str, Enum):
    REGISTERED = "REGISTERED"
    VALIDATED = "VALIDATED"
    DENIED = "DENIED"
    LAPSED = "LAPSED"
    PAID = "PAID"


class MonitoringPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_COMPLIANT = "CLOSED_COMPLIANT"
    CLOSED_BREACH = "CLOSED_BREACH"


class FindingOutcome(str, Enum):
    COMPLIANT = "COMPLIANT"
    BREACH = "BREACH"


# ── Entity TypedDicts ─────────────────────────────────────────────────────
class StateOffice(TypedDict, total=False):
    id: str
    state_code: str
    population: int
    harm_measure_cents: int
    appropriation_rule: str
    created_at: str
    updated_at: str
    version: int


class Investigation(TypedDict, total=False):
    id: str
    title: str
    target_name: str
    summary: str
    phase: str
    opened_at: Optional[str]
    settled_at: Optional[str]
    active_settlement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Participation(TypedDict, total=False):
    id: str
    investigation_id: str
    state_office_id: str
    status: str
    cia_status: str
    cia_tier: Optional[str]
    committee_role: str
    invited_at: str
    cia_executed_at: Optional[str]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Demand(TypedDict, total=False):
    id: str
    participation_id: str
    scope_text: str
    status: str
    issued_at: str
    consolidated_at: Optional[str]
    consolidated_response_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsolidatedResponse(TypedDict, total=False):
    id: str
    investigation_id: str
    demand_ids: List[str]
    coverage_summary: str
    status: str
    submitted_at: str
    accepted_at: Optional[str]
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SignOnEntry(TypedDict, total=False):
    state_office_id: str
    state_code: str
    decision: str
    status: str
    decided_at: str


class Settlement(TypedDict, total=False):
    id: str
    investigation_id: str
    monetary_total_cents: int
    restitution_reserve_cents: int
    allocation_basis: str
    negotiated_shares: Optional[Dict[str, int]]
    injunctive_terms: List[str]
    term_status: str
    fund_status: str
    negotiation_round: int
    counter_total_cents: Optional[int]
    sign_on_opened_at: Optional[str]
    sign_on_deadline: Optional[str]
    executed_at: Optional[str]
    sign_ons: List[SignOnEntry]
    provisional_distributable_cents: int
    provisional_weight_bps_by_state: Dict[str, int]
    distributable_cents: Optional[int]
    lead_cost_cents: Optional[int]
    compliance_hold: bool
    deposited_cents: int
    released_cents: int
    reverted_cents: int
    restitution_reserve_balance_cents: int
    restitution_computed: bool
    restitution_remainder_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AllocationLine(TypedDict, total=False):
    id: str
    settlement_id: str
    state_office_id: str
    state_code: str
    basis_value_snapshot: int
    weight_bps: int
    share_cents: int
    lead_bonus_cents: int
    gross_share_cents: int
    disbursed_cents: int
    reverted_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    allocation_line_id: str
    amount_cents: int
    use_code: str
    status: str
    requested_at: str
    certified_at: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claimant(TypedDict, total=False):
    id: str
    settlement_id: str
    state_code: str
    contact_ref: str
    claimed_loss_cents: int
    validated_loss_cents: Optional[int]
    estimated_payout_cents: Optional[int]
    payout_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict, total=False):
    term_index: int
    outcome: str
    note: Optional[str]
    filed_at: str


class MonitoringPeriod(TypedDict, total=False):
    id: str
    settlement_id: str
    period_index: int
    window_start: str
    window_end: str
    findings: List[Finding]
    breach_count: int
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Composite world returned by fixtures: keyed collections of the entities a
# multi-step setup has built (offices and participations keyed by state code).
class World(TypedDict, total=False):
    offices: Dict[str, StateOffice]
    investigation: Investigation
    participations: Dict[str, Participation]
    demands: Dict[str, Demand]
    response: ConsolidatedResponse
    settlement: Settlement
    lines: List[AllocationLine]
