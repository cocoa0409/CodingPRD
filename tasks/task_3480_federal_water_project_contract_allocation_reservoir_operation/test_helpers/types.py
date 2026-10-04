"""Domain types: entity shapes, status enums, and the role enum.

Every primary resource carries the common quartet ``id`` / ``created_at`` /
``updated_at`` / ``version`` (PRD §2.5), with one exception: the immutable
HydrologyObservation record carries only ``id`` and ``created_at``, so its
shape below omits ``updated_at`` and ``version`` on purpose.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ── Roles (PRD §2.1) ───────────────────────────────────────────────────────

class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    RECLAMATION_OPERATOR = "ReclamationOperator"
    HYDROLOGY_OFFICER = "HydrologyOfficer"
    DISTRICT_MANAGER = "DistrictManager"
    ENVIRONMENTAL_OFFICER = "EnvironmentalOfficer"
    FINANCE_OFFICER = "FinanceOfficer"
    REGIONAL_DIRECTOR = "RegionalDirector"


# ── Enumerations ───────────────────────────────────────────────────────────

class PriorityClass(str, Enum):
    SENIOR = "SENIOR"
    JUNIOR = "JUNIOR"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class WaterYearStatus(str, Enum):
    OPEN = "OPEN"
    ANNOUNCED = "ANNOUNCED"
    CLOSED = "CLOSED"


class ObservationType(str, Enum):
    SNOWPACK_INDEX = "SNOWPACK_INDEX"
    RUNOFF_FORECAST_AF = "RUNOFF_FORECAST_AF"
    MEASURED_INFLOW_AF = "MEASURED_INFLOW_AF"


class AnnouncementStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ShortageTier(str, Enum):
    NONE = "NONE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class AllocationBasis(str, Enum):
    PRIORITY_WATERFALL = "PRIORITY_WATERFALL"
    SHORTAGE_SHARING = "SHORTAGE_SHARING"


class CompliancePosture(str, Enum):
    NORMAL = "NORMAL"
    COMPLIANCE_HOLD = "COMPLIANCE_HOLD"


class ReleasePurpose(str, Enum):
    DELIVERY = "DELIVERY"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    FLOOD_CONTROL = "FLOOD_CONTROL"
    POWER = "POWER"


class ReleaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"


class Species(str, Enum):
    SALMON = "SALMON"
    SMELT = "SMELT"
    STURGEON = "STURGEON"


class RequirementType(str, Enum):
    MIN_FLOW = "MIN_FLOW"
    PULSE_FLOW = "PULSE_FLOW"
    MAX_RELEASE = "MAX_RELEASE"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class IncidentResolution(str, Enum):
    FLOW_RESTORED = "FLOW_RESTORED"
    VARIANCE_GRANTED = "VARIANCE_GRANTED"


class FulfillmentStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    DELIVERED = "DELIVERED"
    SHORTED = "SHORTED"


class ComplianceStatus(str, Enum):
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class RevenuePeriodStatus(str, Enum):
    PROJECTED = "PROJECTED"
    SETTLED = "SETTLED"


class TransferStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class TransferDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"


class ReviewBasis(str, Enum):
    JUNIOR_IMPAIRMENT = "JUNIOR_IMPAIRMENT"
    RETURN_FLOW = "RETURN_FLOW"
    ENVIRONMENTAL = "ENVIRONMENTAL"


class ReviewOutcome(str, Enum):
    SUSTAINED = "SUSTAINED"
    DISMISSED = "DISMISSED"


class AgreementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RATIFIED = "RATIFIED"
    ACTIVATED = "ACTIVATED"


# ── Entity shapes ──────────────────────────────────────────────────────────
# Mutable resources carry id / created_at / updated_at / version (PRD §2.5).

class District(TypedDict):
    id: str
    name: str
    service_area_acres: int
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class WaterContract(TypedDict):
    id: str
    district_id: str
    contract_number: str
    priority_class: str
    max_annual_quantity_af: int
    repayment_obligation_cents: int
    repaid_credits_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WaterYear(TypedDict):
    id: str
    label: int
    season_start: str
    season_end: str
    status: str
    current_announcement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HydrologyObservation(TypedDict):
    # Append-only measurement record: id + created_at only, no updated_at,
    # no version (PRD §2.5).
    id: str
    water_year_id: str
    observation_type: str
    value: int
    observed_on: str
    created_at: str


class AllocationAnnouncement(TypedDict):
    id: str
    water_year_id: str
    sequence_number: int
    status: str
    declared_supply_af: Optional[int]
    shortage_tier: Optional[str]
    allocation_basis: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationLine(TypedDict):
    id: str
    announcement_id: str
    contract_id: str
    allocated_af: int
    delivered_af: int
    transfer_in_af: int
    transfer_out_af: int
    remaining_af: int
    created_at: str
    updated_at: str
    version: int


class Reservoir(TypedDict):
    id: str
    name: str
    capacity_af: int
    dead_pool_af: int
    flood_control_max_storage_af: int
    initial_storage_af: int
    current_storage_af: int
    outlet_capacity_cfs: int
    power_conversion_mwh_per_af: float
    compliance_posture: str
    open_incident_count: int
    total_repayment_obligation_cents: int
    unrecovered_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ReleaseOrder(TypedDict):
    id: str
    reservoir_id: str
    purpose: str
    release_cfs: int
    duration_days: int
    scheduled_start: str
    scheduled_end: str
    volume_af: int
    status: str
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnvironmentalConstraint(TypedDict):
    id: str
    reservoir_id: str
    species: str
    requirement_type: str
    required_min_cfs: Optional[int]
    max_release_cfs: Optional[int]
    enforce_start: str
    enforce_end: str
    created_at: str
    updated_at: str
    version: int


class ComplianceIncident(TypedDict):
    id: str
    reservoir_id: str
    constraint_id: str
    release_order_id: str
    deficit_cfs: int
    status: str
    resolution: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryOrder(TypedDict):
    id: str
    contract_id: str
    water_year_id: str
    allocation_line_id: str
    ordered_af: int
    delivered_af: int
    fulfillment_status: str
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class RevenuePeriod(TypedDict):
    id: str
    reservoir_id: str
    period_month: str
    rate_cents_per_mwh: int
    projected_mwh: float
    projected_revenue_cents: int
    settled_mwh: Optional[float]
    settled_revenue_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict):
    id: str
    from_contract_id: str
    to_contract_id: str
    water_year_id: str
    quantity_af: int
    price_cents: int
    status: str
    revision_count: int
    objection_window_end: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImpactReview(TypedDict):
    id: str
    transfer_request_id: str
    reviewer_district_id: str
    claimed_impact_af: int
    basis: str
    status: str
    resolution_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShortageAgreement(TypedDict):
    id: str
    name: str
    tier_1_senior_pct: int
    tier_1_junior_pct: int
    tier_2_senior_pct: int
    tier_2_junior_pct: int
    quorum_district_count: int
    signatory_district_ids: List[str]
    status: str
    activated_water_year_label: Optional[int]
    created_at: str
    updated_at: str
    version: int
