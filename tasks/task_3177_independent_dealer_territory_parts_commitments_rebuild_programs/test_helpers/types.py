"""Domain types: entity TypedDicts, status enums and the role enum.

Derived from the PRD's resource declarations (§2.5, §3) and its role statement
(§2.1). Entities declared with the common field set carry ``id``, ``created_at``,
``updated_at`` and ``version``; ``PerformanceReview`` is the one resource
declared without the common field set and therefore carries only ``id`` and
``created_at``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Enumerations ─────────────────────────────────────

class DealerStatus(str, Enum):
    PENDING_AGREEMENT = "PENDING_AGREEMENT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ProductFamily(str, Enum):
    EXCAVATION = "EXCAVATION"
    EARTHMOVING = "EARTHMOVING"
    COMPACTION = "COMPACTION"
    POWER_SYSTEMS = "POWER_SYSTEMS"
    LIFT_TRUCK = "LIFT_TRUCK"


class ExclusivityLevel(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    SHARED = "SHARED"


class DealerAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    PERFORMANCE_DEFICIENT = "PERFORMANCE_DEFICIENT"
    TERMINATED = "TERMINATED"


class ToolingComplianceStatus(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    PARTIAL = "PARTIAL"
    COMPLIANT = "COMPLIANT"


class PerformanceReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    RESULTS_RECORDED = "RESULTS_RECORDED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    CIRCUMSTANCE_PENDING = "CIRCUMSTANCE_PENDING"
    EVALUATED = "EVALUATED"


class PartsCommitmentStatus(str, Enum):
    PLANNED = "PLANNED"
    SUBMITTED = "SUBMITTED"
    ORDER_READY = "ORDER_READY"
    CORE_PENDING = "CORE_PENDING"
    PERFORMANCE_DEFICIENT = "PERFORMANCE_DEFICIENT"
    SUSPENDED = "SUSPENDED"
    COMPLETE = "COMPLETE"


class MachinePopulationTier(str, Enum):
    MICRO = "MICRO"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class EmergencyTier(str, Enum):
    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"
    BASIC = "BASIC"


class PartsOrderBatchStatus(str, Enum):
    OPEN = "OPEN"
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CredentialCode(str, Enum):
    DEALER_MASTER = "DEALER_MASTER"
    DEALER_CERTIFIED = "DEALER_CERTIFIED"


class RebuildClaimStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    CORE_PENDING = "CORE_PENDING"
    CORE_RETURNED = "CORE_RETURNED"
    DELIVERED = "DELIVERED"
    CERTIFIED = "CERTIFIED"
    COMPLETE = "COMPLETE"
    DENIED = "DENIED"
    DECLINED = "DECLINED"


class RebuildSpecCode(str, Enum):
    CAT_CERTIFIED_1 = "CAT_CERTIFIED_1"
    CAT_CERTIFIED_2 = "CAT_CERTIFIED_2"
    CAT_CERTIFIED_3 = "CAT_CERTIFIED_3"


class EquipmentOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FINANCE_APPROVED = "FINANCE_APPROVED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TradeInStatus(str, Enum):
    APPRAISED = "APPRAISED"
    ACCEPTED = "ACCEPTED"
    REMARKETED = "REMARKETED"
    SCRAPPED = "SCRAPPED"


class SupportPlanTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class SupportAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ObservationKind(str, Enum):
    MACHINE = "MACHINE"
    LIGHT = "LIGHT"


class PartyRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SUPERSEDED = "SUPERSEDED"


class PopulationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class WeightClassTier(str, Enum):
    LIGHT = "LIGHT"
    MIDDLE = "MIDDLE"
    HEAVY = "HEAVY"


class ServiceOrderKind(str, Enum):
    EMERGENCY_FILL = "EMERGENCY_FILL"
    RESTRICTION = "RESTRICTION"
    SLA_AUDIT = "SLA_AUDIT"


class RestrictionScope(str, Enum):
    HOURS_SPENT = "HOURS_SPENT"
    METER_RUNNING = "METER_RUNNING"
    FULL_STOP = "FULL_STOP"


class ServiceOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    FILLED = "FILLED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class UserRole(str, Enum):
    DEALER_NETWORK_MANAGER = "DealerNetworkManager"
    DEALER_PERFORMANCE_REVIEWER = "DealerPerformanceReviewer"
    PARTS_MANAGER = "PartsManager"
    REBUILD_PROGRAM_SPECIALIST = "RebuildProgramSpecialist"
    SERVICE_TECHNICIAN_SUPERVISOR = "ServiceTechnicianSupervisor"
    DEALER_SALES_MANAGER = "DealerSalesManager"
    FINANCE_PARTNER = "FinancePartner"
    INPUT_DEALER = "InputDealer"


# ─── Entities (common field set) ──────────────────────

class Dealer(TypedDict):
    id: str
    legal_name: str
    home_state_code: str
    territory_code: str
    status: str
    certified_family_count: int
    trusted_commitment_count: int
    open_backorder_units: int
    market_share_pct: float
    created_at: str
    updated_at: str
    version: int


class DealerAgreement(TypedDict):
    id: str
    dealer_id: str
    product_family: str
    territory_code: str
    exclusivity_level: str
    start_at: str
    end_at: str
    status: str
    performance_plan_share_pct: float
    performance_actual_share_pct: float
    certified_technician_count: int
    tooling_compliance_status: str
    trusted_commitment: bool
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartsCommitment(TypedDict):
    id: str
    agreement_id: str
    dealer_id: str
    product_family: str
    machine_population_units: int
    machine_population_slope: float
    machine_population_tier: Optional[str]
    planned_annual_units: int
    emergency_stocking_target_pct: float
    emergency_fill_window_hours: float
    required_stocking_units: Optional[int]
    required_stocking_units_final: Optional[int]
    available_commitment_units: Optional[int]
    availability_target_pct: Optional[float]
    emergency_tier: Optional[str]
    committed_units: int
    fulfilled_units: int
    fill_rate_pct: float
    credit_balance_cents: int
    status: str
    backorder_opened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartsOrderBatch(TypedDict):
    id: str
    commitment_id: str
    product_family: str
    requested_units: int
    reserved_units: int
    unfilled_units: int
    status: str
    requested_at: str
    received_at: Optional[str]
    emergency: bool
    core_return_required: bool
    core_units: int
    created_at: str
    updated_at: str
    version: int


class CertificationRecord(TypedDict):
    id: str
    dealer_id: str
    technician_name: str
    product_family: str
    credential_code: str
    certified_at: str
    recurrence_within_period: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RebuildClaim(TypedDict):
    id: str
    dealer_id: str
    product_family: str
    machine_serial: str
    machine_operating_weight_lb: int
    client_meter_hours: float
    requested_at: str
    core_purchase_value_cents: Optional[int]
    core_return_credit_cents: Optional[int]
    core_returned_at: Optional[str]
    rebuild_labor_hours: float
    rebuild_labor_rate_cents: int
    rebuild_fee_cents: Optional[int]
    certified_rebuild_spec_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentOrder(TypedDict):
    id: str
    dealer_id: str
    product_family: str
    machine_serial: str
    list_price_cents: int
    trade_in_serial: Optional[str]
    status: str
    financing_approval_reference: Optional[str]
    supportable_machine_registered: bool
    requested_at: str
    created_at: str
    updated_at: str
    version: int


class TradeInUnit(TypedDict):
    id: str
    order_id: str
    machine_serial: str
    machine_operating_weight_lb: int
    appraised_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SupportAgreement(TypedDict):
    id: str
    dealer_id: str
    machine_serial: str
    plan_tier: str
    enrolled_at: str
    coverage_multiplier: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketShareObservation(TypedDict):
    id: str
    dealer_id: str
    product_family: str
    observed_machine_units: int
    territory_machine_units: int
    observed_share_pct: float
    recorded_at: str
    kind: str
    created_at: str
    updated_at: str
    version: int


class PartyRegistration(TypedDict):
    id: str
    dealer_id: str
    territory_code: str
    registered_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MachinePopulationRecord(TypedDict):
    id: str
    dealer_id: str
    product_family: str
    machine_serial: str
    machine_operating_weight_lb: int
    meter_hours: float
    weight_class_tier: Optional[str]
    coverage_multiplier: Optional[float]
    projected_annual_parts_units: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict):
    id: str
    dealer_id: str
    commitment_id: str
    kind: str
    product_family: str
    machine_serial: Optional[str]
    orderable_ref_enabled: bool
    response_window_hours: Optional[float]
    restriction_scope: str
    priority_rank: Optional[int]
    risk_score: Optional[int]
    sla_hours: float
    emergency_filled_units: Optional[int]
    deferral_tier: Optional[int]
    opened_at: str
    resolved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Entity declared without the common field set ─────

class PerformanceReview(TypedDict):
    """Declared without the common field set: id + created_at only.

    No ``updated_at`` and no ``version`` field at all.
    """
    id: str
    dealer_id: str
    agreement_id: str
    period_start: str
    period_end: str
    status: str
    actual_territory_machine_units: int
    territory_market_machine_units: int
    actual_market_share_pct: Optional[float]
    performance_ratio_pct: Optional[float]
    quality_deficiency_pp: Optional[float]
    quality_deficient: bool
    sampled_service_orders: int
    met_sla_service_orders: int
    discrepancy_pp: Optional[float]
    circumstance_note: Optional[str]
    loyalty_score: Optional[float]
    created_at: str


__all__ = [
    "DealerStatus", "ProductFamily", "ExclusivityLevel", "DealerAgreementStatus",
    "ToolingComplianceStatus", "PerformanceReviewStatus", "PartsCommitmentStatus",
    "MachinePopulationTier", "EmergencyTier", "PartsOrderBatchStatus",
    "CertificationStatus", "CredentialCode", "RebuildClaimStatus", "RebuildSpecCode",
    "EquipmentOrderStatus", "TradeInStatus", "SupportPlanTier",
    "SupportAgreementStatus", "ObservationKind", "PartyRegistrationStatus",
    "PopulationStatus", "WeightClassTier", "ServiceOrderKind", "RestrictionScope",
    "ServiceOrderStatus", "UserRole",
    "Dealer", "DealerAgreement", "PerformanceReview", "PartsCommitment",
    "PartsOrderBatch", "CertificationRecord", "RebuildClaim", "EquipmentOrder",
    "TradeInUnit", "SupportAgreement", "MarketShareObservation",
    "PartyRegistration", "MachinePopulationRecord", "ServiceOrder",
]