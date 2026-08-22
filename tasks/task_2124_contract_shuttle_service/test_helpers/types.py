"""Domain types for the Contract Shuttle Service API.

Entity payload shapes, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    CONTRACT_ADMIN = "ContractAdmin"
    CLIENT_LIAISON = "ClientLiaison"
    OPS_PLANNER = "OpsPlanner"
    FLEET_MANAGER = "FleetManager"
    DRIVER_USER = "DriverUser"


# ─── Status enums ─────────────────────────────────────────────────────────────

class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    RENEWED = "RENEWED"
    TERMINATED = "TERMINATED"


class SiteType(str, Enum):
    HOTEL = "HOTEL"
    CAMPUS = "CAMPUS"
    CORPORATE = "CORPORATE"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEGRADED = "DEGRADED"
    RETIRED = "RETIRED"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    RETIRED = "RETIRED"


class LicenseClass(str, Enum):
    CDL_B = "CDL_B"
    CDL_C = "CDL_C"


class TripDispatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ASSIGNED = "ASSIGNED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class TripSettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"
    CREDITED = "CREDITED"
    WAIVED = "WAIVED"


class MissedReason(str, Enum):
    OPERATOR_FAULT = "OPERATOR_FAULT"
    CLIENT_REQUEST = "CLIENT_REQUEST"
    WEATHER = "WEATHER"


class RidershipSource(str, Enum):
    DRIVER_TALLY = "DRIVER_TALLY"
    APC_SENSOR = "APC_SENSOR"


class OnDemandRequestStatus(str, Enum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    SERVED = "SERVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class MaintenanceKind(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    CORRECTIVE = "CORRECTIVE"
    BRANDING_WRAP = "BRANDING_WRAP"


class MaintenanceStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MaintenanceOutcome(str, Enum):
    RETURN_TO_SERVICE = "RETURN_TO_SERVICE"
    RETIRE = "RETIRE"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"


class SettlementVariant(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class MemoStatus(str, Enum):
    ISSUED = "ISSUED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class MemoReason(str, Enum):
    MISSED_TRIP = "MISSED_TRIP"
    WAIT_SLA_BREACH = "WAIT_SLA_BREACH"
    GOODWILL = "GOODWILL"


class OfferStatus(str, Enum):
    OPEN = "OPEN"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class OfferDecision(str, Enum):
    REOPEN = "REOPEN"
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


# ─── Entity shapes ────────────────────────────────────────────────────────────
# Every resource except a ridership count row carries id, created_at, updated_at
# and version. A ridership count row is an append-only observation and carries
# only id and created_at.


class ServiceContract(TypedDict):
    id: str
    client_name: str
    site_type: str
    base_rate_cents_per_service_hour: int
    term_start_date: str
    term_end_date: str
    escalation_index_pct: float
    sla_on_time_threshold_pct: float
    penalty_rate_cents_per_missed_trip: int
    ada_min_accessible_pct: float
    predecessor_contract_id: Optional[str]
    status: str
    credit_balance_cents: int
    branded_vehicle_count: int
    branded_ada_vehicle_count: int
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    contract_id: str
    name: str
    loop_minutes: int
    headway_minutes: int
    service_window_start_min: int
    service_window_end_min: int
    demand_forecast_pax_per_hour: int
    reference_seat_capacity: int
    required_vehicle_count: int
    ada_required_count: int
    status: str
    published_service_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    fleet_code: str
    seat_capacity: int
    is_ada_accessible: bool
    odometer_km: int
    service_interval_km: int
    branding_contract_id: Optional[str]
    status: str
    committed_block_minutes: int
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    full_name: str
    license_class: str
    ada_certified: bool
    max_duty_minutes_per_day: int
    assigned_duty_minutes_current_date: int
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict):
    id: str
    route_id: str
    contract_id: str
    vehicle_id: Optional[str]
    driver_id: Optional[str]
    service_date: str
    scheduled_departure_min: int
    scheduled_arrival_min: int
    actual_departure_min: Optional[int]
    actual_completion_min: Optional[int]
    dispatch_status: str
    settlement_status: str
    missed_reason: Optional[str]
    counted_boardings: int
    counted_ada_boardings: int
    matched_party_seats: int
    created_at: str
    updated_at: str
    version: int


class RidershipCount(TypedDict):
    """Append-only observation: id and created_at only, no updated_at, no version."""

    id: str
    trip_id: str
    boarded: int
    alighted: int
    ada_boardings: int
    source: str
    sequence_no: int
    recorded_by_user_id: str
    created_at: str


class OnDemandRequest(TypedDict):
    id: str
    contract_id: str
    matched_trip_id: Optional[str]
    service_date: str
    requested_pickup_min: int
    party_size: int
    requires_ada: bool
    promised_headway_minutes: int
    promised_wait_minutes: int
    actual_wait_minutes: Optional[int]
    wait_overage_minutes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceOrder(TypedDict):
    id: str
    vehicle_id: str
    kind: str
    service_date: str
    window_start_min: int
    window_end_min: int
    odometer_at_open: int
    status: str
    outcome: Optional[str]
    displaced_trip_count: int
    created_at: str
    updated_at: str
    version: int


class ServicePeriodReport(TypedDict):
    id: str
    contract_id: str
    period_start_date: str
    period_end_date: str
    status: str
    settlement_variant: str
    revision_round: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    effective_rate_cents_per_service_hour: int
    scheduled_trip_count: int
    completed_trip_count: int
    missed_trip_count: int
    waived_trip_count: int
    countable_trip_count: int
    on_time_trip_count: int
    on_time_pct: float
    total_boardings: int
    total_ada_boardings: int
    total_billable_minutes: int
    billable_service_hours: float
    gross_amount_cents: int
    penalty_tier_pct: float
    sla_penalty_cents: int
    missed_trip_penalty_cents: int
    penalty_amount_cents: int
    credit_amount_cents: int
    net_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class CreditMemo(TypedDict):
    id: str
    contract_id: str
    trip_id: Optional[str]
    applied_report_id: Optional[str]
    amount_cents: int
    reason: str
    status: str
    voided_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalOffer(TypedDict):
    id: str
    contract_id: str
    basis_report_id: Optional[str]
    successor_contract_id: Optional[str]
    proposed_term_months: int
    proposed_rate_cents_per_service_hour: int
    counter_rate_cents_per_service_hour: Optional[int]
    agreed_rate_cents_per_service_hour: Optional[int]
    volume_pct: float
    clawback_pct: float
    applied_escalation_pct: float
    round_index: int
    status: str
    created_at: str
    updated_at: str
    version: int
