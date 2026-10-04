"""Domain types: entity shapes, status enums, role enum.

PRD 2.6 states every entity in this system carries the full common field
set - ``id``, ``created_at``, ``updated_at`` and ``version`` - with no
exceptions, so every TypedDict here carries them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    AGENCY_CONTRACTING_OFFICER = "AgencyContractingOfficer"
    AGENCY_RATE_ANALYST = "AgencyRateAnalyst"
    CONCESSIONER_RATE_MANAGER = "ConcessionerRateManager"
    CONCESSIONER_OPS_MANAGER = "ConcessionerOpsManager"
    CONCESSIONER_FRONT_DESK = "ConcessionerFrontDesk"
    CONCESSIONER_ACCOUNTANT = "ConcessionerAccountant"
    AGENCY_FINANCIAL_AUDITOR = "AgencyFinancialAuditor"
    CONCESSIONER_MAINTENANCE_CHIEF = "ConcessionerMaintenanceChief"
    CONCESSIONER_HR_MANAGER = "ConcessionerHRManager"
    AGENCY_ENVIRONMENTAL_INSPECTOR = "AgencyEnvironmentalInspector"
    SYSTEM_TEST_HARNESS = "SystemTestHarness"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TRANSITION_PENDING = "TRANSITION_PENDING"
    CLOSED = "CLOSED"


class SeasonStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class ServiceLineStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RoomClassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class FilingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class StudyStatus(str, Enum):
    REGISTERED = "REGISTERED"
    STALE = "STALE"
    ARCHIVED = "ARCHIVED"


class ReservationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    FULFILLED = "FULFILLED"


class OccupancyBand(str, Enum):
    SOLO = "SOLO"
    DOUBLE = "DOUBLE"
    FAMILY = "FAMILY"


class OccupancyMode(str, Enum):
    BANDED = "BANDED"
    ACTUAL_HEADCOUNT = "ACTUAL_HEADCOUNT"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class StatementStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"


class ProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    COMPLETED = "COMPLETED"
    APPROVED = "APPROVED"
    EXPENDED = "EXPENDED"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFFLINE = "OFFLINE"


class HireStatus(str, Enum):
    HIRED = "HIRED"
    ARRIVED = "ARRIVED"
    DEPARTED = "DEPARTED"
    NO_SHOW = "NO_SHOW"
    TERMINATED = "TERMINATED"


class VoucherStatus(str, Enum):
    BOOKED = "BOOKED"
    USED = "USED"
    VOID = "VOID"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CORRECTIVE_PLAN_REQUIRED = "CORRECTIVE_PLAN_REQUIRED"
    CLOSED = "CLOSED"


class Contract(TypedDict, total=False):
    id: str
    park_code: str
    contract_number: str
    term_months: int
    start_date: str
    end_date: str
    franchise_fee_rate: float
    employee_housing_capacity: int
    lsi_annual_schedule_type: str
    environmental_plan_due_day_of_year: int
    status: str
    successor_contract_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OperatingSeason(TypedDict, total=False):
    id: str
    contract_id: str
    year: int
    open_date: str
    close_date: str
    lottery_open_date: str
    lottery_window_hours: int
    status: str
    month_offset: int
    created_at: str
    updated_at: str
    version: int


class ServiceLine(TypedDict, total=False):
    id: str
    contract_id: str
    line_type: str
    authorized: bool
    separate_reporting_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RoomClass(TypedDict, total=False):
    id: str
    contract_id: str
    code: str
    total_rooms: int
    peak_season_months: List[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SubmittedRate(TypedDict):
    occupancy_band: str
    nightly_rate_cents: int


class RateFiling(TypedDict, total=False):
    id: str
    contract_id: str
    season_id: str
    room_class_id: str
    submitted_rates: List[Dict[str, Any]]
    reference_study_id: str
    status: str
    effective_date: Optional[str]
    approved_weighted_mean_cents: Optional[int]
    revision_of_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComparabilityStudy(TypedDict, total=False):
    id: str
    contract_id: str
    title: str
    comparables: List[Dict[str, Any]]
    weighted_mean_cents: int
    prepared_at: str
    valid_through: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    contract_id: str
    season_id: str
    room_class_id: str
    guest_ref: str
    check_in_date: str
    check_out_date: str
    occupancy_band: str
    occupancy_mode: str
    beds_occupied: Optional[int]
    quoted_nightly_rate_cents: int
    total_charge_cents: int
    deposit_cents: int
    nights: int
    status: str
    cancellation_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class GrossReceiptsReport(TypedDict, total=False):
    id: str
    contract_id: str
    period_month: str
    service_line_id: str
    gross_receipts_cents: int
    submitted_by_role: Optional[str]
    submitted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FranchiseFeeStatement(TypedDict, total=False):
    id: str
    contract_id: str
    period_month: str
    lines: List[Dict[str, Any]]
    total_fee_cents: int
    reporting_method: str
    aggregate_diagnostic_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalProject(TypedDict, total=False):
    id: str
    contract_id: str
    title: str
    asset_ref: str
    authorized_cost_cents: int
    actual_cost_cents: int
    in_service_month_offset: int
    accrued_lsi_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EmployeeHousingUnit(TypedDict, total=False):
    id: str
    contract_id: str
    unit_code: str
    bed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonalHire(TypedDict, total=False):
    id: str
    contract_id: str
    season_id: str
    service_line_id: str
    employee_ref: str
    housing_unit_id: str
    arrival_date: str
    departure_date: str
    transport_origin: Optional[str]
    needs_transport: bool
    transport_voucher_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportVoucher(TypedDict, total=False):
    id: str
    contract_id: str
    hire_id: str
    origin: str
    booked_seats: int
    travel_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EnvironmentalIncident(TypedDict, total=False):
    id: str
    contract_id: str
    protocol: str
    severity: str
    occurred_at: str
    description: str
    corrective_plan_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int
