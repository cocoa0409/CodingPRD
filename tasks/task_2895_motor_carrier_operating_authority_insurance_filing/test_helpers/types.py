"""Typed shapes for the Motor Carrier Operating Authority API.

The enum tuples and TypedDicts mirror the entity definitions of PRD S2.4 and
S3.  Note the S2.4 split: most resources carry the full system-managed set
(``id``, ``created_at``, ``updated_at``, ``version``) while ``ProcessAgent``
and ``FeeLedgerEntry`` are immutable once written and therefore carry only
``id`` and ``created_at`` — no ``updated_at`` and no ``version`` at all.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing_extensions is optional
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore


# ---------------------------------------------------------------------------
# Roles (S2.1)
# ---------------------------------------------------------------------------
ROLE_CARRIER_REP = "CarrierRep"
ROLE_INSURANCE_FILER = "InsuranceFiler"
ROLE_VETTING_ANALYST = "VettingAnalyst"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_REGISTRY_ADMIN = "RegistryAdmin"

ALL_ROLES = (
    ROLE_CARRIER_REP,
    ROLE_INSURANCE_FILER,
    ROLE_VETTING_ANALYST,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_REGISTRY_ADMIN,
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
UNIFIED_REGISTRATION_STATUSES = ("NOT_REGISTERED", "REGISTERED")
ENTRANT_STATUSES = ("NEW_ENTRANT", "PERMANENT")
COMPLIANCE_RISK_VARIANTS = ("NONE", "SELF_REPORTED", "AUDITED")

APPLICATION_KINDS = ("NEW", "NAME_CHANGE", "REINSTATEMENT", "SUCCESSOR_IN_INTEREST")
TRANSPORTATION_TYPES = (
    "FOR_HIRE_PROPERTY",
    "HOUSEHOLD_GOODS",
    "PASSENGER",
    "PROPERTY_BROKER",
    "FREIGHT_FORWARDER",
)
APPLICATION_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "RETURNED_FOR_CORRECTION",
    "PUBLISHED",
    "GRANTED",
    "DENIED",
)
VETTING_DISPOSITIONS = ("RETURN", "PUBLISH", "DENY")

AUTHORITY_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED", "REVOKED", "RESCINDED")
INSURANCE_STATUSES = ("NOT_FILED", "PARTIAL", "FILED", "LAPSED")
SUSPENSION_REASONS = (
    "NONE",
    "INSURANCE_LAPSE",
    "DESIGNATION_GAP",
    "SAFETY_AUDIT_FAILURE",
    "AUDIT_WINDOW_MISSED",
)
NEW_ENTRANT_AUDIT_STATUSES = ("NOT_REQUIRED", "PENDING", "PASSED", "FAILED", "MISSED")

DESIGNATION_STATUSES = ("ACTIVE", "REVOKED")

FILING_TYPES = ("BIPD", "CARGO", "SURETY_BOND", "TRUST_FUND")
FILING_STATUSES = ("ACTIVE", "CANCELLED")

PROCEEDING_REASONS = ("INSURANCE_LAPSE", "SAFETY_AUDIT_FAILURE", "AUDIT_WINDOW_MISSED")
PROCEEDING_STATUSES = ("NOTICE_ISSUED", "CURED", "REVOKED")

AUDIT_STATUSES = ("SCHEDULED", "PASSED", "FAILED", "MISSED")

COMMODITY_CLASSES = (
    "GENERAL_FREIGHT",
    "HOUSEHOLD_GOODS",
    "HAZMAT_BULK",
    "HAZMAT_NONBULK",
    "PASSENGERS",
)
CONTRACT_STATUSES = ("ACTIVE", "SUSPENDED_BY_AUTHORITY", "TERMINATED")
LIABILITY_VARIANTS = ("NONE", "SUSPENSION_ESTIMATE", "SETTLED_ACTUAL")

SHIPMENT_STATUSES = ("TENDERED", "IN_TRANSIT", "DELIVERED", "EMBARGOED", "DIVERTED")
PRE_EMBARGO_STATUSES = ("NONE", "TENDERED", "IN_TRANSIT")

LEDGER_ENTRY_TYPES = (
    "FILING_FEE_DEBIT",
    "FILING_FEE_REVERSAL_CREDIT",
    "FEE_PAYMENT_CREDIT",
)


# ---------------------------------------------------------------------------
# Common field sets (S2.4)
# ---------------------------------------------------------------------------
class MutableRecord(TypedDict, total=False):
    """The full system-managed set carried by ten of the twelve resources."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableRecord(TypedDict, total=False):
    """Only ``id`` and ``created_at`` — ProcessAgent and FeeLedgerEntry."""

    id: str
    created_at: str


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
class Carrier(MutableRecord, total=False):
    legal_name: str
    dba_name: Optional[str]
    domicile_state: str
    self_reported_vehicle_count: int
    self_reported_driver_count: int
    self_reported_oos_rate_pct: float
    usdot_number: str
    unified_registration_status: str
    entrant_status: str
    compliance_risk_score: Optional[float]
    compliance_risk_variant: str
    audited_oos_rate_pct: Optional[float]
    fee_balance_cents: int
    fees_assessed_total_cents: int
    fees_reversed_total_cents: int
    fees_paid_total_cents: int
    active_authority_count: int
    biennial_update_due_at: str
    last_biennial_update_at: Optional[str]
    biennial_delinquent: bool


class AuthorityApplication(MutableRecord, total=False):
    carrier_id: str
    application_kind: str
    transportation_type: str
    requested_operating_states: List[str]
    predecessor_authority_id: Optional[str]
    passenger_seating_capacity: Optional[int]
    proposed_legal_name: Optional[str]
    hazmat_endorsement_requested: bool
    hazmat_bulk_capable: bool
    status: str
    submission_count: int
    required_bipd_limit_cents: int
    required_cargo_limit_cents: int
    required_bond_limit_cents: int
    filing_fee_cents: int
    filing_fee_breakdown: Optional[Dict[str, int]]
    vetting_findings: Optional[str]
    vetted_by_user_id: Optional[str]
    published_by_user_id: Optional[str]
    published_at: Optional[str]
    denied_reason: Optional[str]


class OperatingAuthority(MutableRecord, total=False):
    carrier_id: str
    application_id: str
    docket_number: str
    transportation_type: str
    hazmat_endorsed: bool
    hazmat_bulk_capable: bool
    passenger_seating_capacity: Optional[int]
    required_bipd_limit_cents: int
    required_cargo_limit_cents: int
    required_bond_limit_cents: int
    required_jurisdictions: List[str]
    publication_at: str
    activation_eligible_at: str
    authority_status: str
    insurance_status: str
    designated_state_count: int
    designation_coverage_complete: bool
    suspension_reason: str
    active_contract_count: int
    suspended_contract_count: int
    new_entrant_audit_status: str
    new_entrant_audit_deadline_at: Optional[str]
    activated_at: Optional[str]
    suspended_at: Optional[str]
    revoked_at: Optional[str]
    rescinded_at: Optional[str]


class ProcessAgent(ImmutableRecord, total=False):
    company_name: str
    coverage_states: List[str]
    blanket_agent: bool


class ProcessAgentDesignation(MutableRecord, total=False):
    authority_id: str
    process_agent_id: str
    state_code: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    revoked_at: Optional[str]


class Insurer(MutableRecord, total=False):
    company_name: str
    naic_code: str
    authorized_states: List[str]


class InsuranceFiling(MutableRecord, total=False):
    authority_id: str
    insurer_id: str
    filing_type: str
    coverage_limit_cents: int
    policy_number: str
    effective_at: str
    cancellation_effective_at: Optional[str]
    status: str
    meets_required_minimum: bool
    supersedes_filing_id: Optional[str]


class RevocationProceeding(MutableRecord, total=False):
    authority_id: str
    reason: str
    status: str
    notice_issued_at: str
    cure_deadline_at: str
    cured_at: Optional[str]
    revoked_at: Optional[str]
    replacement_policy_number: Optional[str]


class SafetyAudit(MutableRecord, total=False):
    carrier_id: str
    status: str
    audit_window_opens_at: str
    audit_deadline_at: str
    result_recorded_at: Optional[str]
    audited_oos_rate_pct: Optional[float]
    audited_driver_violation_count: Optional[int]
    audited_vehicle_defect_count: Optional[int]
    acute_violation_count: Optional[int]
    audit_score: Optional[float]


class CustomerContract(MutableRecord, total=False):
    authority_id: str
    shipper_name: str
    commodity_class: str
    monthly_committed_revenue_cents: int
    term_start_at: str
    term_end_at: str
    status: str
    embargoed_shipment_count: int
    disruption_liability_cents: int
    disruption_liability_variant: str
    suspended_at: Optional[str]
    resumed_at: Optional[str]
    terminated_at: Optional[str]


class Shipment(MutableRecord, total=False):
    contract_id: str
    origin_state: str
    destination_state: str
    tender_at: str
    expected_delivery_at: str
    declared_value_cents: int
    hazmat: bool
    status: str
    pre_embargo_status: str
    embargo_days_accrued: int
    embargoed_at: Optional[str]
    embargo_released_at: Optional[str]
    delivered_at: Optional[str]
    diverted_at: Optional[str]


class FeeLedgerEntry(ImmutableRecord, total=False):
    carrier_id: str
    entry_type: str
    amount_cents: int
    docket_ref: Optional[str]
    memo: Optional[str]


class SweepResult(TypedDict, total=False):
    swept_at: str
    audits_missed_count: int
    carriers_flagged_delinquent_count: int
    authorities_revoked_count: int
    contracts_terminated_count: int


JsonDict = Dict[str, Any]
