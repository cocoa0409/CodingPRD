"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRODUCT_ENGINEER = "ProductEngineer"
    COMPLIANCE_ENGINEER = "ComplianceEngineer"
    FIELD_RESEARCHER = "FieldResearcher"
    SERVICE_AGENT = "ServiceAgent"
    ACCOUNT_MANAGER = "AccountManager"
    CHANNEL_MANAGER = "ChannelManager"


class PlatformStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUNSETTING = "SUNSETTING"
    RETIRED = "RETIRED"


class CertificationStatus(str, Enum):
    DESIGN = "DESIGN"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    RECALLED = "RECALLED"


class ToolStage(str, Enum):
    CONCEPT = "CONCEPT"
    FIELD_RESEARCH = "FIELD_RESEARCH"
    PROTOTYPE = "PROTOTYPE"
    ENGINEERING_VALIDATION = "ENGINEERING_VALIDATION"
    LAUNCHED = "LAUNCHED"
    DISCONTINUED = "DISCONTINUED"


class InsightStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"


class AssetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REPORTED_LOST = "REPORTED_LOST"
    DECOMMISSIONED = "DECOMMISSIONED"


class AdjudicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FulfillmentStatus(str, Enum):
    NONE = "NONE"
    AWAITING_UNIT = "AWAITING_UNIT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ListingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"


class CaseStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    CLEARED = "CLEARED"


class BulletinStatus(str, Enum):
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


class Coverage(str, Enum):
    FREE = "FREE"
    PRORATED = "PRORATED"
    OUT_OF_WARRANTY = "OUT_OF_WARRANTY"


class AgeBasis(str, Enum):
    ACTIVATION = "ACTIVATION"
    MANUFACTURE = "MANUFACTURE"


# All entities carry the four common properties of PRD §2.4
# (id, created_at, updated_at, version).

class BatteryPlatform(TypedDict, total=False):
    id: str
    code: str
    interface_key: str
    chemistry_family: str
    backward_commitment_years: int
    forward_commitment_generations: int
    sunset_announce_date: Optional[str]
    sunset_date: Optional[str]
    status: str
    current_generation: int
    created_at: str
    updated_at: str
    version: int


class BatteryPack(TypedDict, total=False):
    id: str
    platform_id: str
    sku: str
    pack_generation: int
    cell_supplier_code: str
    cell_format: str
    rated_capacity_wh: float
    max_charge_rate_w: float
    replacement_price_cents: int
    warranty_days: int
    free_replacement_days: int
    certification_status: str
    submitted_by_user_id: Optional[str]
    safety_hold: bool
    charge_estimate_minutes: int
    charger_compatible: bool
    created_at: str
    updated_at: str
    version: int


class Charger(TypedDict, total=False):
    id: str
    platform_id: str
    model_code: str
    charger_generation: int
    max_charge_rate_w: float
    created_at: str
    updated_at: str
    version: int


class ToolModel(TypedDict, total=False):
    id: str
    platform_id: str
    model_code: str
    trade: str
    category: str
    tier: str
    corded_conversion: bool
    avg_power_draw_w: float
    runtime_target_min: Optional[float]
    min_pack_generation: int
    max_pack_generation: int
    replacement_price_cents: int
    warranty_days: int
    free_replacement_days: int
    torque_min_nm: float
    torque_max_nm: float
    stage: str
    adopted_field_research_count: int
    adopted_jobsite_observation_count: int
    regulatory_compatible_pack_count: int
    best_runtime_min: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ResearchInsight(TypedDict, total=False):
    id: str
    tool_model_id: str
    kind: str
    summary: str
    severity: str
    status: str
    submitted_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ServiceCenter(TypedDict, total=False):
    id: str
    code: str
    region: str
    capabilities: List[str]
    daily_capacity: int
    created_at: str
    updated_at: str
    version: int


class AssetAccount(TypedDict, total=False):
    id: str
    org_name: str
    tier: str
    asset_limit: int
    active_asset_count: int
    created_at: str
    updated_at: str
    version: int


class TrackedAsset(TypedDict, total=False):
    id: str
    account_id: str
    subject_type: str
    tool_model_id: Optional[str]
    battery_pack_id: Optional[str]
    serial_number: str
    manufactured_at: str
    first_paired_at: str
    status: str
    custom_torque_limit_nm: Optional[float]
    anti_theft_lock_enabled: bool
    is_replacement_unit: bool
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    tracked_asset_id: str
    claim_type: str
    fault_code: str
    service_date: str
    service_center_id: str
    adjudication_status: str
    fulfillment_status: str
    age_basis: str
    age_days: int
    coverage: str
    credit_cents: int
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChannelPartner(TypedDict, total=False):
    id: str
    name: str
    channel_type: str
    region: str
    has_suspended_listings: bool
    active_allocation_total: int
    created_at: str
    updated_at: str
    version: int


class DistributionListing(TypedDict, total=False):
    id: str
    channel_partner_id: str
    tool_model_id: Optional[str]
    battery_pack_id: Optional[str]
    charger_id: Optional[str]
    wholesale_price_cents: int
    allocation_qty: int
    status: str
    requires_relist_ack: bool
    superseded_by_listing_id: Optional[str]
    channel_partner_version: int
    created_at: str
    updated_at: str
    version: int


class CounterfeitCase(TypedDict, total=False):
    id: str
    battery_pack_id: str
    reported_serial: str
    detection_method: str
    status: str
    evidence_score: int
    created_by_user_id: str
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyBulletin(TypedDict, total=False):
    id: str
    platform_id: str
    battery_pack_ids: List[str]
    severity: str
    title: str
    effective_from: str
    effective_to: Optional[str]
    supersedes_bulletin_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
