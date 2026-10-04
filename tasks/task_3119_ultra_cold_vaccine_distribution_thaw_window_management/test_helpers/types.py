"""Domain types: entity structures, status enumerations and the role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MANUFACTURING_QA = "ManufacturingQA"
    REGULATORY_AFFAIRS_OFFICER = "RegulatoryAffairsOfficer"
    DISTRIBUTION_PLANNER = "DistributionPlanner"
    SITE_COORDINATOR = "SiteCoordinator"
    LOGISTICS_OPERATOR = "LogisticsOperator"
    COLD_CHAIN_REVIEWER = "ColdChainReviewer"
    MEDICAL_SCIENCE_LIAISON = "MedicalScienceLiaison"


class Presentation(str, Enum):
    SINGLE_DOSE_VIAL = "SINGLE_DOSE_VIAL"
    MULTI_DOSE_VIAL = "MULTI_DOSE_VIAL"


class AllocationBasis(str, Enum):
    POPULATION_SHARE = "POPULATION_SHARE"
    FIXED_QUANTITY = "FIXED_QUANTITY"


class SegmentRule(str, Enum):
    TIE_CONTINUE = "TIE_CONTINUE"
    STOP = "STOP"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    ALLOCATED = "ALLOCATED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    RECALLED = "RECALLED"


class WindowStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EntitlementAcceptanceStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    FULFILLED = "FULFILLED"
    LAPSED = "LAPSED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"


class PaymentStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    DISPUTED = "DISPUTED"


class StorageCapability(str, Enum):
    ULTRA_COLD = "ULTRA_COLD"
    REFRIGERATED = "REFRIGERATED"
    AMBIENT_ONLY = "AMBIENT_ONLY"


class ColdChainEquipmentType(str, Enum):
    ULTRA_COLD_FREEZER = "ULTRA_COLD_FREEZER"
    THERMAL_SHIPPER = "THERMAL_SHIPPER"


class EquipmentType(str, Enum):
    ULTRA_COLD_FREEZER = "ULTRA_COLD_FREEZER"
    THERMAL_SHIPPER = "THERMAL_SHIPPER"
    DATA_LOGGER = "DATA_LOGGER"


class EquipmentVerificationStatus(str, Enum):
    RECORDED = "RECORDED"
    INVALIDATED = "INVALIDATED"


class EquipmentOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class EntryRoute(str, Enum):
    DIRECT_ULTRA_COLD = "DIRECT_ULTRA_COLD"
    THAW_AT_HUB = "THAW_AT_HUB"


class DispatchStatus(str, Enum):
    DRAFT = "DRAFT"
    PACKED = "PACKED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    REJECTED_AT_DOCK = "REJECTED_AT_DOCK"


class PackingStatus(str, Enum):
    PREPARING = "PREPARING"
    SEALED = "SEALED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    RELEASED = "RELEASED"
    HELD = "HELD"


class ShipperHoldReason(str, Enum):
    MISSING_LOGGER = "MISSING_LOGGER"
    INSUFFICIENT_DRY_ICE = "INSUFFICIENT_DRY_ICE"
    LATE_PACKING = "LATE_PACKING"
    LATE_READING = "LATE_READING"


class TemperatureState(str, Enum):
    ULTRA_COLD = "ULTRA_COLD"
    THAWED = "THAWED"
    REFRIGERATED = "REFRIGERATED"
    PUNCTURED = "PUNCTURED"
    EXPIRED = "EXPIRED"
    IN_TRANSIT = "IN_TRANSIT"
    PALLET_STAGED = "PALLET_STAGED"
    DESTROYED = "DESTROYED"


class LedgerEntryType(str, Enum):
    RELEASE = "RELEASE"
    THAW = "THAW"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    ADMINISTER = "ADMINISTER"
    PUNCTURE = "PUNCTURE"
    EXPIRE = "EXPIRE"
    WASTE = "WASTE"
    DESTROY = "DESTROY"
    REVERSE = "REVERSE"


class LedgerEntryStatus(str, Enum):
    RECORDED = "RECORDED"
    RECONCILED = "RECONCILED"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DISPATCHED = "DISPATCHED"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class TransferLapseReason(str, Enum):
    WINDOW_EXPIRED = "WINDOW_EXPIRED"
    DEST_ADMISSIBILITY_FAILED = "DEST_ADMISSIBILITY_FAILED"
    DEST_STANDING_FROZEN = "DEST_STANDING_FROZEN"
    REFREEZE_FORBIDDEN = "REFREEZE_FORBIDDEN"


class ExcursionReviewStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADJUDICATED = "ADJUDICATED"


class AdjudicationStatus(str, Enum):
    PENDING = "PENDING"
    USABLE = "USABLE"
    NOT_USABLE = "NOT_USABLE"


class QuarantineStatus(str, Enum):
    OPEN = "OPEN"
    LIFTED = "LIFTED"
    RETAINED = "RETAINED"
    DESTROYED = "DESTROYED"


class SliceClosureState(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    CLOSED = "CLOSED"


class SliceStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"


class ProgramStandingStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PropagationMode(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    AFTER_CYCLE = "AFTER_CYCLE"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    LAPSED = "LAPSED"


class ReservationResolveMethod(str, Enum):
    RESERVATION_BOUNDARY = "RESERVATION_BOUNDARY"
    CAPACITY_POOLED = "CAPACITY_POOLED"


class ReservationTempState(str, Enum):
    FROZEN = "FROZEN"
    THAWED = "THAWED"


class OrderRejectionReason(str, Enum):
    BELOW_MIN_ORDER = "BELOW_MIN_ORDER"
    NO_ENTITLEMENT = "NO_ENTITLEMENT"
    CAPACITY_UNAVAILABLE = "CAPACITY_UNAVAILABLE"
    SITE_NOT_READY = "SITE_NOT_READY"
    WINDOW_CLOSED = "WINDOW_CLOSED"


class WastageCause(str, Enum):
    TEMPERATURE_EXCURSION = "TEMPERATURE_EXCURSION"
    PUNCTURE_EXPIRY = "PUNCTURE_EXPIRY"
    THAW_WINDOW_BREACH = "THAW_WINDOW_BREACH"
    REFRIGERATED_EXPIRY = "REFRIGERATED_EXPIRY"
    TRANSFER_REJECTION = "TRANSFER_REJECTION"
    SITE_RETURN = "SITE_RETURN"


class AuditOrdering(str, Enum):
    WALLCLOCK = "WALLCLOCK"
    CONSISTENT = "CONSISTENT"


class AccountabilityVariant(str, Enum):
    INTERIM = "INTERIM"
    CERTIFIED = "CERTIFIED"


# ── Entity shapes ─────────────────────────────────────────────────────────
# Every addressable resource carries id + created_at + updated_at + version,
# except the two append-only records noted in the PRD.

class ProductConfiguration(TypedDict, total=False):
    id: str
    product_code: str
    presentation: str
    doses_per_vial: int
    vials_per_carton: int
    cartons_per_pallet: int
    ship_box_cartons: int
    min_order_cartons: int
    ultra_cold_min_c: float
    ultra_cold_max_c: float
    refrigerated_min_c: float
    refrigerated_max_c: float
    thaw_stability_hours: int
    refrigerated_shelf_life_hours: int
    excursion_tolerance_min_c: float
    excursion_max_single_breach_minutes: int
    excursion_max_cumulative_minutes: int
    refreeze_prohibited: bool
    punctured_bud_hours: int
    wastage_threshold_pct: float
    doses_per_carton: int
    created_at: str
    updated_at: str
    version: int


class JurisdictionProgram(TypedDict, total=False):
    id: str
    jurisdiction_code: str
    regulatory_body: str
    allocation_basis: str
    population_weight: float
    fixed_weekly_cartons: int
    weekly_allocation_cap_cartons: int
    min_order_cartons: int
    reservable_carton_pct: float
    acceptance_window_hours: int
    shipping_days: List[str]
    shipping_cutoff_utc: str
    quarantine_on_review: bool
    adjudication_sla_hours: int
    segment_rule: str
    reporting_period_days: int
    released_cartons_to_date: int
    credit_balance_cartons: int
    lapsed_carton_count: int
    standing_status: str
    created_at: str
    updated_at: str
    version: int


class AllocationBatch(TypedDict, total=False):
    id: str
    batch_code: str
    product_configuration_id: str
    jurisdiction_program_id: str
    released_cartons: int
    release_date: str
    expiry_date: str
    status: str
    allocated_cartons: int
    unallocated_cartons: int
    doses_released_total: int
    created_at: str
    updated_at: str
    version: int


class AllocationWindow(TypedDict, total=False):
    id: str
    allocation_batch_id: str
    jurisdiction_program_id: str
    opens_at: str
    closes_at: str
    status: str
    requested_cartons: int
    accepted_cartons: int
    created_at: str
    updated_at: str
    version: int


class AllocationEntitlement(TypedDict, total=False):
    id: str
    allocation_window_id: str
    jurisdiction_program_id: str
    computed_cartons: int
    held_cartons: int
    accepted_cartons: int
    available_cartons: int
    acceptance_status: str
    lapsed_at: Optional[str]
    release_rate: float
    created_at: str
    updated_at: str
    version: int


class SiteOrder(TypedDict, total=False):
    id: str
    allocation_entitlement_id: str
    storage_site_id: str
    requested_cartons: int
    requested_doses: int
    accepted_cartons: int
    accepted_doses: int
    rejected_cartons: int
    rounded_from_doses: int
    min_order_shortfall_cartons: int
    requested_cartons_snapshot: int
    order_status: str
    payment_status: str
    submitted_at: Optional[str]
    materialization_variance_doses: int
    created_at: str
    updated_at: str
    version: int


class StorageSite(TypedDict, total=False):
    id: str
    site_code: str
    site_name: str
    jurisdiction_program_id: str
    storage_capability: str
    ultra_cold_capacity_cartons: int
    refrigerated_capacity_cartons: int
    cold_chain_equipment_type: str
    equipment_certificate_expires_at: str
    expected_weekly_doses: int
    equipment_certified: bool
    equipment_verification_id: Optional[str]
    reported_entry_type: str
    usable_doses: int
    administrative_remaining_doses: int
    open_excursion_count: int
    inventory_status: str
    created_at: str
    updated_at: str
    version: int


class SiteEquipmentVerification(TypedDict, total=False):
    id: str
    storage_site_id: str
    equipment_type: str
    certificate_number: str
    certificate_expires_at: str
    verified_at: str
    outcome: str
    status: str
    invalidated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispatchOrder(TypedDict, total=False):
    id: str
    site_order_id: str
    storage_site_id: str
    entry_route: str
    staging_site_id: Optional[str]
    freeze_required: bool
    dispatched_at: Optional[str]
    eta_at: Optional[str]
    status: str
    carton_count: int
    route_cartons: int
    min_order_shortfall_cartons: int
    created_at: str
    updated_at: str
    version: int


class ColdChainShipper(TypedDict, total=False):
    id: str
    dispatch_order_id: str
    shipper_serial: str
    dry_ice_kg: float
    packing_started_at: str
    packing_completed_at: Optional[str]
    logger_serial: str
    packing_status: str
    hold_reason: Optional[str]
    payload_locked_at: Optional[str]
    required_dry_ice_kg: int
    dry_ice_deficit_kg: float
    punctured_ice_slots: float
    created_at: str
    updated_at: str
    version: int


class TemperatureLoggerReading(TypedDict, total=False):
    """Append-only and immutable once created: id + created_at only."""
    id: str
    cold_chain_shipper_id: str
    recorded_at: str
    temperature_c: float
    source: str
    breach_minutes: int
    created_at: str


class Carton(TypedDict, total=False):
    id: str
    allocation_batch_id: str
    cold_chain_shipper_id: Optional[str]
    carton_serial: str
    vials_per_carton: int
    doses_per_carton: int
    temperature_state: str
    thawed_at: Optional[str]
    thaw_window_expires_at: Optional[str]
    current_expires_at: Optional[str]
    expired_at: Optional[str]
    remaining_doses: int
    administrative_remaining_doses: int
    cumulative_released_doses: int
    administrative_expired: bool
    dose_shortfall_doses: int
    created_at: str
    updated_at: str
    version: int


class DoseLedgerEntry(TypedDict, total=False):
    """Append-only: id + created_at only; no updated_at, no version."""
    id: str
    carton_id: str
    entry_type: str
    quantity_doses: int
    occurred_at: str
    site_id: Optional[str]
    reverses_entry_id: Optional[str]
    status: str
    created_at: str


class SiteTransfer(TypedDict, total=False):
    id: str
    from_site_id: str
    to_site_id: str
    carton_id: str
    requested_at: str
    status: str
    hours_remaining_at_request: float
    dest_required_entry_type: str
    admissibility: str
    reservation_expires_at: Optional[str]
    cumulative_conflict_minutes: int
    freeze_required: bool
    lapse_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TemperatureExcursion(TypedDict, total=False):
    id: str
    carton_id: str
    storage_site_id: str
    first_breach_at: str
    last_breach_at: str
    min_temperature_c: float
    reported_at: str
    review_status: str
    adjudication_status: str
    adjudicated_at: Optional[str]
    min_duration_minutes: int
    dosing_hours_remaining_at_breach: float
    exceeds_cumulative_cap: bool
    dose_impact_category: str
    dose_impact_factor: float
    quarantine_status: str
    current_resolution_trace_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExcursionAdjudication(TypedDict, total=False):
    id: str
    temperature_excursion_id: str
    adjudicator_user_id: str
    outcome: str
    rationale: str
    effective_from: str
    prior_outcome: Optional[str]
    certified_lost_doses: int
    interim_lost_doses: int
    freeze_transitive_doses: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DosesAffectedSlice(TypedDict, total=False):
    id: str
    temperature_excursion_id: str
    closure_state: str
    time_slice_c: float
    doses_upper_bound: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WastageReport(TypedDict, total=False):
    id: str
    excursion_adjudication_id: str
    accounting_period_start: str
    accounting_period_end: str
    reported_at: str
    attributed_cause: str
    doses_reported: int
    dose_accountability_status: str
    diluent_doses: int
    certified_doses: int
    reconciliation_variance_doses: int
    site_wastage_rate_ppm: int
    created_at: str
    updated_at: str
    version: int


class OrderRejection(TypedDict, total=False):
    id: str
    site_order_id: str
    rejected_cartons: int
    reason_code: str
    rejected_at: str
    doses_not_booked: int
    entitlement_release_cartons: int
    created_at: str
    updated_at: str
    version: int


class EntitlementRelease(TypedDict, total=False):
    id: str
    allocation_entitlement_id: str
    reallocated_to_entitlement_id: Optional[str]
    released_cartons: int
    reason_code: str
    released_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReportingPeriod(TypedDict, total=False):
    id: str
    jurisdiction_program_id: str
    period_start: str
    period_end: str
    report_version: int
    status: str
    released_doses: int
    administered_doses: int
    accounted_doses: int
    forecast_remaining_doses: Optional[int]
    unaccounted_doses: int
    wastage_rate_basis_points: int
    created_at: str
    updated_at: str
    version: int


class ProgramStanding(TypedDict, total=False):
    id: str
    jurisdiction_program_id: str
    as_of: str
    propagation_mode: str
    lapsed_period_count: int
    lapsed_window_count: int
    lapsed_carton_rate: float
    lapsed_carton_count: int
    lapsed_entitlement_count: int
    risk_tier: int
    created_at: str
    updated_at: str
    version: int


class ShippingWindowLapse(TypedDict, total=False):
    id: str
    allocation_entitlement_id: str
    lapsed_at: str
    lapsed_cartons: int
    reason: str
    dose_reconciliation_status: str
    doses_undelivered: int
    created_at: str
    updated_at: str
    version: int


class AdjudicationAppeal(TypedDict, total=False):
    id: str
    temperature_excursion_id: str
    filed_by_user_id: str
    filed_at: str
    status: str
    prior_trace_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CartonStorageReservation(TypedDict, total=False):
    id: str
    storage_site_id: str
    carton_id: str
    entry_type: str
    temp_state: str
    reserved_capacity_cartons: int
    start_at: str
    end_at: str
    status: str
    resolved_conflict_minutes: int
    created_at: str
    updated_at: str
    version: int


class CartonFamily(TypedDict, total=False):
    id: str
    site_id: str
    member_site_id: str
    linked_at: str
    shared_dose_count: int
    created_at: str
    updated_at: str
    version: int