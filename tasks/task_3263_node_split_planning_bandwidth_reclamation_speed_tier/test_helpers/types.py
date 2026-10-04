"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource model (§2.5 common fields, §3 entity narratives).
UtilizationSample is append-only: it carries only id + created_at, no
updated_at/version (PRD §2.5).
"""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UpstreamConfig(str, Enum):
    LEGACY = "LEGACY"
    MID_SPLIT = "MID_SPLIT"
    HIGH_SPLIT = "HIGH_SPLIT"


class NodeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SPLIT_RETIRED = "SPLIT_RETIRED"


class BlockType(str, Enum):
    LEGACY_VIDEO = "LEGACY_VIDEO"
    DATA = "DATA"


class SpectrumBlockStatus(str, Enum):
    VIDEO_ACTIVE = "VIDEO_ACTIVE"
    RECLAIM_PENDING = "RECLAIM_PENDING"
    DATA_ACTIVE = "DATA_ACTIVE"


class ServiceGroupPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"
    SPLIT_RETIRED = "SPLIT_RETIRED"


class UtilizationMethod(str, Enum):
    PEAK_PCT95 = "PEAK_PCT95"
    SUSTAINED_AVG = "SUSTAINED_AVG"


class CapacityActionType(str, Enum):
    NODE_SPLIT = "NODE_SPLIT"
    SPECTRUM_RECLAIM = "SPECTRUM_RECLAIM"
    MID_SPLIT_UPGRADE = "MID_SPLIT_UPGRADE"
    HIGH_SPLIT_UPGRADE = "HIGH_SPLIT_UPGRADE"


class CapacityActionOrigin(str, Enum):
    SYSTEM = "SYSTEM"
    MANUAL = "MANUAL"


class CapacityActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class NodeSplitProjectStatus(str, Enum):
    PERMIT_REVIEW = "PERMIT_REVIEW"
    PERMIT_GRANTED = "PERMIT_GRANTED"
    PERMIT_DENIED = "PERMIT_DENIED"
    SCHEDULED = "SCHEDULED"
    IN_CONSTRUCTION = "IN_CONSTRUCTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MigrationWaveStatus(str, Enum):
    PLANNED = "PLANNED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class CustomerEquipmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CapabilityClass(str, Enum):
    D30 = "D30"
    D31 = "D31"
    D40 = "D40"


class SpeedTierStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class ProvisioningRequestStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class RefreshCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    LAUNCHED = "LAUNCHED"
    CLOSED = "CLOSED"


class CongestionComplaintStatus(str, Enum):
    INVESTIGATING = "INVESTIGATING"
    CLASSIFIED = "CLASSIFIED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class CauseCategory(str, Enum):
    PLANT = "PLANT"
    IN_HOME = "IN_HOME"
    DESTINATION = "DESTINATION"


class ScoringVariant(str, Enum):
    EVIDENCE_WEIGHTED = "EVIDENCE_WEIGHTED"
    RECENCY_WEIGHTED = "RECENCY_WEIGHTED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    NETWORK_PLANNER = "NetworkPlanner"
    CAPACITY_ENGINEER = "CapacityEngineer"
    FIELD_OPS_COORDINATOR = "FieldOpsCoordinator"
    FRANCHISE_ADMIN = "FranchiseAdmin"
    PROVISIONING_AGENT = "ProvisioningAgent"
    CUSTOMER_CARE = "CustomerCare"


class FranchiseArea(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    obligation_homes_required: int
    obligation_deadline: str
    blackout_windows: List[dict]
    homes_built_progress: int
    created_at: str
    updated_at: str
    version: int


class OpticalNode(TypedDict, total=False):
    id: str
    franchise_area_id: str
    node_code: str
    homes_passed: int
    downstream_spectrum_mhz: int
    upstream_config: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SpectrumBlock(TypedDict, total=False):
    id: str
    optical_node_id: str
    block_type: str
    mhz: int
    status: str
    channels: int
    capacity_mbps: int
    created_at: str
    updated_at: str
    version: int


class ServiceGroup(TypedDict, total=False):
    id: str
    optical_node_id: str
    sg_code: str
    homes_passed: int
    warn_threshold_pct: int
    critical_threshold_pct: int
    utilization_method: str
    downstream_capacity_mbps: int
    upstream_capacity_mbps: int
    provisioned_downstream_mbps: int
    current_load_mbps: int
    current_utilization_pct: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class UtilizationSample(TypedDict, total=False):
    # Append-only: id + created_at only; NO updated_at, NO version (PRD §2.5).
    id: str
    service_group_id: str
    measured_at: str
    downstream_mbps: int
    upstream_mbps: int
    created_at: str


class CapacityAction(TypedDict, total=False):
    id: str
    service_group_id: str
    action_type: str
    origin: str
    status: str
    target_block_ids: Optional[List[str]]
    target_upstream_config: Optional[str]
    superseded_by_id: Optional[str]
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NodeSplitProject(TypedDict, total=False):
    id: str
    capacity_action_id: str
    child_count: int
    min_homes_per_child: int
    max_homes_per_child: int
    status: str
    window_start: Optional[str]
    window_end: Optional[str]
    child_allocations: Optional[List[int]]
    child_node_id: Optional[str]
    child_service_group_ids: Optional[List[str]]
    created_at: str
    updated_at: str
    version: int


class MigrationWave(TypedDict, total=False):
    id: str
    capacity_action_id: str
    wave_code: str
    window_start: str
    window_end: str
    target_cpe_ids: List[str]
    migrated_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerPremise(TypedDict, total=False):
    id: str
    service_group_id: str
    premise_ref: str
    address: str
    current_tier_id: Optional[str]
    provisioned_downstream_mbps: int
    created_at: str
    updated_at: str
    version: int


class CustomerEquipment(TypedDict, total=False):
    id: str
    customer_premise_id: str
    model: str
    docsis_version: str
    capability_class: str
    max_downstream_mbps: int
    video_legacy: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SpeedTier(TypedDict, total=False):
    id: str
    tier_code: str
    downstream_mbps: int
    upstream_mbps: int
    min_capability_class: str
    min_upstream_config: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProvisioningRequest(TypedDict, total=False):
    id: str
    customer_premise_id: str
    speed_tier_id: str
    status: str
    config_file_content: Optional[str]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefreshCampaign(TypedDict, total=False):
    id: str
    franchise_area_id: str
    campaign_code: str
    target_capability_class: str
    status: str
    targeted_count: int
    swapped_count: int
    created_at: str
    updated_at: str
    version: int


class CongestionComplaint(TypedDict, total=False):
    id: str
    customer_premise_id: str
    description: str
    plant_signal: int
    home_signal: int
    destination_signal: int
    scoring_variant_used: Optional[str]
    score_plant: Optional[float]
    score_in_home: Optional[float]
    score_destination: Optional[float]
    cause_category: Optional[str]
    status: str
    resolution_note: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int
