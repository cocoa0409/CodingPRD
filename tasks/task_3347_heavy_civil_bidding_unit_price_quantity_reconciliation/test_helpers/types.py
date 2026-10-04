"""Domain types: entity TypedDicts, status enums and the role enum.

Every resource in this system is declared with common fields enabled, so each
entity carries ``id``, ``created_at``, ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import Optional, TypedDict


# --- Status enums ------------------------------------------------------------

class BidStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    OPEN = "OPEN"
    RECALLED = "RECALLED"


class ProjectStatus(str, Enum):
    PRE_BID = "PRE_BID"
    AWARDED = "AWARDED"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"


class ContractType(str, Enum):
    UNIT_PRICE = "UNIT_PRICE"
    LUMP_SUM = "LUMP_SUM"


class UnitOfMeasure(str, Enum):
    LF = "LF"
    CY = "CY"
    TON = "TON"
    EA = "EA"
    SY = "SY"


class BidItemStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class BondType(str, Enum):
    BID = "BID"
    PERFORMANCE = "PERFORMANCE"
    PAYMENT = "PAYMENT"
    MAINTENANCE = "MAINTENANCE"


class BondStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    EXECUTED = "EXECUTED"
    RELEASED = "RELEASED"


class SuretyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class QuoteStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CARRIED = "CARRIED"
    REJECTED = "REJECTED"
    SELECTED = "SELECTED"


class GoodFaithEffortBasis(str, Enum):
    NONE = "NONE"
    SOLICITED_DBE = "SOLICITED_DBE"
    DOCUMENTED_UNAVAILABLE = "DOCUMENTED_UNAVAILABLE"
    OUTREACH_EVENT = "OUTREACH_EVENT"


class MeasurementStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAYABLE = "PAYABLE"
    VOIDED = "VOIDED"


class ReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    CLOSED = "CLOSED"


class CloseoutStatus(str, Enum):
    NONE = "NONE"
    PENDING_RETENTION = "PENDING_RETENTION"
    CLOSED = "CLOSED"


class ConditionStatus(str, Enum):
    REPORTED = "REPORTED"
    DOCUMENTED = "DOCUMENTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DETERMINED = "DETERMINED"
    DENIED = "DENIED"


class DeterminationType(str, Enum):
    TIME_EXTENSION = "TIME_EXTENSION"
    COST_EQUITABLE_ADJUSTMENT = "COST_EQUITABLE_ADJUSTMENT"
    QUANTITY_ADJUSTMENT = "QUANTITY_ADJUSTMENT"
    REJECTED = "REJECTED"


class DeterminationStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    FINAL = "FINAL"


class CommitmentStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class RecallReasonCode(str, Enum):
    ERROR_IN_BID = "ERROR_IN_BID"
    OWNER_ADDENDUM = "OWNER_ADDENDUM"
    PROTESTS_RECEIVED = "PROTESTS_RECEIVED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ESTIMATOR = "Estimator"
    CONTRACTING_OFFICER = "ContractingOfficer"
    PROJECT_MANAGER = "ProjectManager"
    ENGINEER = "Engineer"
    SURETY = "Surety"
    ANONYMOUS = "Anonymous"


# --- Entity TypedDicts (all carry the common field set) ----------------------

class Project(TypedDict, total=False):
    id: str
    project_code: str
    owner_agency_name: str
    contract_type: str
    bid_deadline_at: str
    retention_rate_pct: float
    advertised_dbe_goal_pct: float
    bid_window_open_at: str
    bid_status: str
    project_status: str
    bid_open_at: Optional[str]
    total_bid_cents: int
    contract_value_cents: int
    unbalanced_bid_score: float
    dbe_participation_pct: float
    retention_balance_cents: int
    claim_window_open: bool
    created_at: str
    updated_at: str
    version: int


class BidItem(TypedDict, total=False):
    id: str
    project_id: str
    item_code: str
    item_description: str
    unit_of_measure: str
    estimated_quantity: float
    bid_unit_price_cents: int
    balanced_unit_price_cents: int
    crew_day_labor_cents: int
    crew_day_equipment_cents: int
    daily_productivity_units: float
    overrun_threshold_pct: float
    underrun_threshold_pct: float
    measured_quantity: float
    variance_pct: float
    item_status: str
    renegotiation_required: bool
    created_at: str
    updated_at: str
    version: int


class Surety(TypedDict, total=False):
    id: str
    surety_name: str
    aggregate_capacity_cents: int
    single_job_limit_cents: int
    capacity_consumed_cents: int
    available_capacity_cents: int
    unavailable_capacity_cents: int
    surety_status: str
    created_at: str
    updated_at: str
    version: int


class SuretyCommitment(TypedDict, total=False):
    id: str
    surety_id: str
    project_id: str
    committed_amount_cents: int
    commitment_status: str
    reserved_at: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bond(TypedDict, total=False):
    id: str
    project_id: str
    surety_id: str
    bond_type: str
    bond_amount_cents: int
    required_bond_cents: int
    bond_status: str
    effective_from: str
    effective_to: str
    maintain_bond_horizon_days: int
    issued_at: Optional[str]
    released_at: Optional[str]
    lien_claim_amount_cents: int
    capacity_consumed_cents: int
    created_at: str
    updated_at: str
    version: int


class SubcontractorQuote(TypedDict, total=False):
    id: str
    project_id: str
    trade_code: str
    contact_name: str
    quoted_amount_cents: int
    quote_window_start: str
    quote_window_end: str
    quote_received_at: str
    quote_status: str
    version_round: int
    unicap_registered: bool
    good_faith_effort_basis: str
    dbe_credit_cents: int
    carried_in_bid: bool
    shopping_flagged: bool
    created_at: str
    updated_at: str
    version: int


class ProgressMeasurement(TypedDict, total=False):
    id: str
    bid_item_id: str
    measured_quantity: float
    measured_at: str
    measurement_status: str
    applied_unit_price_cents: int
    payable_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class QuantityReconciliation(TypedDict, total=False):
    id: str
    project_id: str
    reconciliation_status: str
    overrun_item_count: int
    underrun_item_count: int
    net_adjustment_cents: int
    final_contract_value_cents: int
    retention_held_cents: int
    pace_basis_retention_cents: int
    retention_released_cents: int
    closeout_status: str
    created_at: str
    updated_at: str
    version: int


class DifferingSiteCondition(TypedDict, total=False):
    id: str
    project_id: str
    condition_status: str
    reported_at: str
    documentation_complete: bool
    notice_days_elapsed: int
    claimed_amount_cents: int
    claim_window_engaged: bool
    created_at: str
    updated_at: str
    version: int


class EngineerDetermination(TypedDict, total=False):
    id: str
    condition_id: str
    determination_type: str
    target_bid_item_id: Optional[str]
    determined_unit_rate_cents: int
    days_granted: int
    entitles_adjustment: bool
    determination_status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    session_token: str
    role: str
    user_id: str
