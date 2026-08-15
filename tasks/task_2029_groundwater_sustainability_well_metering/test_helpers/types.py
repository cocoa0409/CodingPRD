"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    WELL_OWNER = "WellOwner"
    WATER_MASTER = "WaterMaster"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    APPEALS_OFFICER = "AppealsOfficer"
    STATE_REGULATOR = "StateRegulator"


class AccountType(str, Enum):
    AGRICULTURAL = "AGRICULTURAL"
    MUNICIPAL = "MUNICIPAL"
    INDUSTRIAL = "INDUSTRIAL"
    DOMESTIC = "DOMESTIC"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class WellType(str, Enum):
    PRODUCTION = "PRODUCTION"
    MONITORING = "MONITORING"
    DOMESTIC = "DOMESTIC"


class WellStatus(str, Enum):
    REGISTERED = "REGISTERED"
    METER_INSTALLED = "METER_INSTALLED"
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"


class TransferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class SnapshotStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DISCARDED = "DISCARDED"


class BasinCondition(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    CRITICAL = "CRITICAL"


class PenaltyReason(str, Enum):
    OVERDRAFT = "OVERDRAFT"
    LATE_REPORT = "LATE_REPORT"
    UNMETERED_PUMPING = "UNMETERED_PUMPING"


class AssessmentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    APPEALED = "APPEALED"
    UPHELD = "UPHELD"
    REDUCED = "REDUCED"
    OVERTURNED = "OVERTURNED"
    PAID = "PAID"


class AppealOutcome(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    REDUCED = "REDUCED"


class AnnualReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# --- Entity shapes (PRD §2.4: seven resources carry id/created_at/updated_at/version;
# MonitoringReading is the append-only exception with only id + created_at) ---


class WaterUserAccount(TypedDict, total=False):
    id: str
    holder_name: str
    account_type: str
    base_allocation_af: float
    status: str
    current_water_year: int
    extracted_af_ytd: float
    pending_extraction_af: float
    credit_balance_af: float
    transfer_out_af_ytd: float
    transfer_reserved_af: float
    penalty_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Well(TypedDict, total=False):
    id: str
    account_id: str
    well_type: str
    location_description: str
    minimum_threshold_ft: Optional[float]
    meter_serial: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExtractionReport(TypedDict, total=False):
    id: str
    well_id: str
    water_year: int
    month: int
    reported_af: float
    late_flag: bool
    fee_cents: Optional[int]
    amendment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferOrder(TypedDict, total=False):
    id: str
    seller_account_id: str
    buyer_account_id: str
    quantity_af: float
    unit_price_cents: int
    effective_start_date: str
    effective_end_date: str
    expires_at: str
    settled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MonitoringReading(TypedDict, total=False):
    # Append-only event log: carries ONLY id + created_at (no updated_at, no version).
    id: str
    created_at: str
    well_id: str
    measured_at: str
    depth_to_water_ft: float
    collector_name: str


class BasinConditionSnapshot(TypedDict, total=False):
    id: str
    computed_at: str
    eligible_well_count: int
    breached_well_count: int
    breach_pct: Optional[float]
    rolling_mean_depth_ft: Optional[float]
    condition: str
    mean_condition: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PenaltyAssessment(TypedDict, total=False):
    id: str
    account_id: str
    reason: str
    water_year: int
    overdraft_af: Optional[float]
    amount_cents: int
    reduced_amount_cents: Optional[int]
    paid_amount_cents: Optional[int]
    assessed_by: str
    decided_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualStateReport(TypedDict, total=False):
    id: str
    water_year: int
    total_extracted_af: float
    verified_report_count: int
    overdraft_assessment_count: int
    penalties_assessed_cents: int
    penalties_collected_cents: int
    total_pumping_fees_cents: int
    final_basin_condition: Optional[str]
    avg_depth_ft: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int
