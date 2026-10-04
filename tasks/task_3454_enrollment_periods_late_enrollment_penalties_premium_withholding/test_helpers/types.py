"""Structural descriptions of the resources the API returns.

The TypedDicts document the shapes the PRD promises so that assertions can
be written against a named contract instead of bare string keys.  They are
declared ``total=False`` because tests routinely inspect a subset of a
payload.

PRD section 2.5 gives every one of the fourteen resources the same four
system-managed fields - ``id``, ``created_at``, ``updated_at`` and
``version`` - so every TypedDict below builds on ``CommonProps``.  The enums
mirror the status machines and value vocabularies of PRD section 3.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --- Status enums -----------------------------------------------------------


class UserRole(str, Enum):
    BENEFICIARY = "Beneficiary"
    FIELD_OFFICER = "FieldOfficer"
    APPEALS_OFFICER = "AppealsOfficer"
    IRS_DATA_AGENT = "IrsDataAgent"
    BENEFIT_ADMINISTRATOR = "BenefitAdministrator"


class EnrollmentPeriodStatus(str, Enum):
    UPCOMING = "UPCOMING"
    OPEN = "OPEN"
    EXPIRED = "EXPIRED"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    CANCELLED = "CANCELLED"


class CollectionStatus(str, Enum):
    PENDING_SETUP = "PENDING_SETUP"
    WITHHOLDING = "WITHHOLDING"
    DIRECT_BILL = "DIRECT_BILL"
    DELINQUENT = "DELINQUENT"
    NOT_REQUIRED = "NOT_REQUIRED"
    CLOSED = "CLOSED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RecordStatus(str, Enum):
    ACTIVE_COVERAGE = "ACTIVE_COVERAGE"
    ENDED = "ENDED"


class PenaltyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WAIVED = "WAIVED"
    VOIDED = "VOIDED"


class DeterminationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class AppealStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ArrangementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    STOPPED = "STOPPED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ElectionStatus(str, Enum):
    GOVERNING = "GOVERNING"
    SUPERSEDED = "SUPERSEDED"
    EFFECTIVE = "EFFECTIVE"


class ReliefCaseStatus(str, Enum):
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


# --- Common property group (PRD section 2.5) --------------------------------


class CommonProps(TypedDict, total=False):
    """id, created_at, updated_at and version - carried by every resource."""

    id: str
    created_at: str
    updated_at: str
    version: int


# --- Entity shapes ------------------------------------------------------------


class Beneficiary(CommonProps, total=False):
    full_name: str
    date_of_birth: str
    attainment_month: str
    iep_start_month: str
    iep_end_month: str
    credit_cents: int


class IrmaaBracket(TypedDict):
    tier: int
    single_floor_cents: int
    joint_floor_cents: int
    part_b_surcharge_cents: int
    part_d_surcharge_cents: int


class RateSchedule(CommonProps, total=False):
    coverage_year: int
    part_b_standard_cents: int
    part_d_national_base_cents: int
    irmaa_brackets: List[IrmaaBracket]


class EnrollmentPeriod(CommonProps, total=False):
    beneficiary_id: str
    window_type: str  # IEP | SEP
    window_start_month: str
    window_end_month: str
    status: str  # UPCOMING | OPEN | EXPIRED
    source_coverage_ref: Optional[str]


class CoverageEnrollment(CommonProps, total=False):
    beneficiary_id: str
    part: str  # PART_A | PART_B | PART_D | PART_C
    enrollment_status: str
    collection_status: str
    effective_month: str
    end_month: Optional[str]
    enrolled_via_window: str  # IEP | SEP | GEP | AEP | OEP_MA | RELIEF


class EmployerCoverageRecord(CommonProps, total=False):
    beneficiary_id: str
    employer_name: str
    employer_size: int
    coverage_start_month: str
    coverage_end_month: Optional[str]
    employment_end_month: Optional[str]
    is_drug_coverage_creditable: bool
    verification_status: str
    record_status: str


class PenaltyAssessment(CommonProps, total=False):
    beneficiary_id: str
    part: str  # PART_B | PART_D
    gap_months: int
    full_12month_periods: Optional[int]  # populated for PART_B, null for PART_D
    penalty_pct: Optional[int]           # populated for PART_B, null for PART_D
    status: str  # ACTIVE | WAIVED | VOIDED


class TaxReturnRecord(CommonProps, total=False):
    beneficiary_id: str
    tax_year: int
    magi_cents: int
    filing_status: str  # SINGLE | MARRIED_JOINT


class PremiumDetermination(CommonProps, total=False):
    beneficiary_id: str
    coverage_year: int
    part: str  # PART_B | PART_D
    status: str  # PROVISIONAL | FINAL | SUPERSEDED
    tax_year_used: int
    irmaa_tier: int
    base_premium_cents: int
    irmaa_surcharge_cents: int
    lep_cents: int
    total_premium_cents: int
    created_by_user_id: str


class AppealCase(CommonProps, total=False):
    beneficiary_id: str
    premium_determination_id: str
    life_event_type: str
    event_date: str
    claimed_magi_cents: int
    status: str  # UNDER_REVIEW | MORE_INFO_REQUESTED | APPROVED | DENIED
    adjudicated_by_user_id: Optional[str]


class WithholdingArrangement(CommonProps, total=False):
    beneficiary_id: str
    monthly_benefit_cents: int
    status: str  # ACTIVE | SUSPENDED | STOPPED


class PremiumInvoice(CommonProps, total=False):
    beneficiary_id: str
    part: str  # PART_B | PART_D
    service_month: str
    amount_cents: int
    paid_cents: int
    applied_cents: int
    outstanding_cents: int
    due_date: str  # YYYY-MM-DD
    is_arrears: bool
    status: str


class PayerCoordinationRecord(CommonProps, total=False):
    beneficiary_id: str
    role: str   # MEDICARE_PRIMARY | MEDICARE_SECONDARY
    basis: str  # NO_EMPLOYER_COVERAGE | SMALL_EMPLOYER | LARGE_EMPLOYER
    effective_start_month: str
    effective_end_month: Optional[str]


class PlanElection(CommonProps, total=False):
    beneficiary_id: str
    election_window: str  # AEP | OEP_MA
    season_key: str       # AEP-<yyyy> | OEP-<yyyy>
    current_coverage: str  # ORIGINAL | MA
    target_coverage: str   # ORIGINAL | MA
    effective_month: str
    status: str  # GOVERNING | SUPERSEDED | EFFECTIVE


class EquitableReliefCase(CommonProps, total=False):
    beneficiary_id: str
    relief_type: str  # RETROACTIVE_ENROLLMENT | PENALTY_WAIVER | BOTH
    part: str         # PART_B | PART_D
    requested_effective_month: Optional[str]
    claimed_misinform_source: str  # FEDERAL_AGENCY | PLAN_REPRESENTATIVE | EMPLOYER
    description: str
    status: str  # UNDER_INVESTIGATION | GRANTED | DENIED


# --- Test-driving payloads (PRD section 4, the two unprefixed operations) ---


class ClockReading(TypedDict, total=False):
    """Body of the clock endpoint's data payload."""

    current_utc: str


class MonthlyCycleSummary(TypedDict, total=False):
    """Body of the monthly ops-run checkpoint's data payload."""

    cycle_month: str
    enrollments_activated: int
    invoices_issued: int
    enrollments_terminated: int
    elections_effectuated: int
