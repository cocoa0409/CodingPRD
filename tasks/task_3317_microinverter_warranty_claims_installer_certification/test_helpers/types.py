"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Enums ────────────────────────────────────────────

class CertificationLevel(str, Enum):
    CERTIFIED = "CERTIFIED"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class CertificationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class DesignProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMMISSIONED = "COMMISSIONED"


class ModelCode(str, Enum):
    IQ7 = "IQ7"
    IQ8 = "IQ8"
    IQ8HC = "IQ8HC"
    IQ7X_DISCONTINUED = "IQ7X_DISCONTINUED"


class LotStatus(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    RECALL = "RECALL"


class WarrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TRANSFERRED = "TRANSFERRED"


class CommissioningState(str, Enum):
    PENDING = "PENDING"
    COMMISSIONED = "COMMISSIONED"
    DECOMMISSIONED = "DECOMMISSIONED"


class MonitoredStatus(str, Enum):
    ONLINE = "ONLINE"
    UNDERPERFORMING = "UNDERPERFORMING"
    FAILED = "FAILED"
    OFFLINE = "OFFLINE"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DIAGNOSED = "DIAGNOSED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class ClaimKind(str, Enum):
    DEFECT = "DEFECT"
    UNDERPERFORMANCE = "UNDERPERFORMANCE"
    NO_POWER = "NO_POWER"
    COMMUNICATION = "COMMUNICATION"


class DiagnosticSource(str, Enum):
    REMOTE = "REMOTE"
    REMOTE_VERIFIED = "REMOTE_VERIFIED"


class LaborStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class TransferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TransferKind(str, Enum):
    SALE = "SALE"
    INHERITANCE = "INHERITANCE"
    FORECLOSURE = "FORECLOSURE"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    DISPATCHING = "DISPATCHING"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class CampaignOrigin(str, Enum):
    LOT_TREND = "LOT_TREND"
    MANUAL = "MANUAL"


class ReplacementOrderStatus(str, Enum):
    PENDING_DISPATCH = "PENDING_DISPATCH"
    DISPATCHED = "DISPATCHED"
    INSTALLED = "INSTALLED"
    CANCELED = "CANCELED"


class CompatibilityClass(str, Enum):
    IDENTICAL = "IDENTICAL"
    COMPATIBLE_UPGRADE = "COMPATIBLE_UPGRADE"
    INCOMPATIBLE = "INCOMPATIBLE"


class LotAction(str, Enum):
    CLEAR_RECALL = "CLEAR_RECALL"
    FORCE_WATCH = "FORCE_WATCH"
    OPEN_CAMPAIGN_BY_HAND = "OPEN_CAMPAIGN_BY_HAND"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INSTALLER = "Installer"
    MONITORING_SERVICE = "MonitoringService"
    HOMEOWNER = "Homeowner"


# ─── Entity payload shapes (PRD §2.4) ─────────────────

class CommissionedUnitEntry(TypedDict, total=False):
    serial_number: str
    model_code: str
    installed_at: str
    production_lot_code: str


# common_fields: true — carries id + created_at + updated_at + version
class Installer(TypedDict, total=False):
    id: str
    installer_code: str
    company_name: str
    certification_level: str
    certification_status: str
    certified_until: str
    design_tool_enabled: bool
    commissioning_enabled: bool
    active_system_count: int
    claim_approval_rate_pct: float
    labor_approved_cents_total: int
    labor_reversed_cents_total: int
    labor_paid_cents_total: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class DesignProject(TypedDict, total=False):
    id: str
    installer_id: str
    site_address: str
    site_postal_code: str
    module_count: int
    dc_capacity_watts: int
    dc_ac_ratio: float
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only/immutable: ONLY id + created_at
class ProductionLot(TypedDict, total=False):
    id: str
    created_at: str
    lot_code: str
    manufacture_month: str
    defect_threshold_pct: float
    embed_model_code: str
    units_registered_count: int
    failed_unit_count: int
    window_failed_unit_count: int
    defect_rate_cumulative_pct: float
    defect_rate_window_pct: float
    lot_status: str
    corrective_action_required: bool
    replacement_model_code: str
    watch_started_at: Optional[str]


# common_fields: true
class SystemRegistration(TypedDict, total=False):
    id: str
    installer_id: str
    design_project_id: str
    site_address: str
    site_postal_code: str
    homeowner_name: str
    homeowner_email: str
    units: List[CommissionedUnitEntry]
    commissioned_at: str
    warranty_start_at: str
    base_warranty_end_at: str
    extended_warranty_end_at: str
    warranty_status: str
    unit_count: int
    replacement_ratio: float
    coverage_window: dict
    owner_change_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Unit(TypedDict, total=False):
    id: str
    system_id: str
    serial_number: str
    model_code: str
    production_lot_id: str
    installed_at: str
    commissioning_state: str
    monitored_status: str
    last_performance_ratio: Optional[float]
    underperformance_streak_hours: int
    failed_at: Optional[str]
    replacement_count: int
    replacement_window_position: int
    rma_eligible: bool
    campaign_eligible: bool
    retired_generation: bool
    direct_replacement_unsupported: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class WarrantyClaim(TypedDict, total=False):
    id: str
    unit_id: str
    installer_id: str
    claim_kind: str
    remote_diagnostic_ref: str
    status: str
    installer_level_at_claim: str
    system_age_months_at_claim: int
    diagnostic_source: str
    labor_eligible: bool
    approved_labor_hours: float
    denial_reason: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class LaborReimbursement(TypedDict, total=False):
    id: str
    claim_id: str
    installer_id: str
    claimed_hours: float
    allowed_hours: float
    cap_applied: bool
    hourly_rate_cents: int
    age_factor: float
    level_factor: float
    labor_component_cents: int
    diagnostic_component_cents: int
    net_amount_cents: int
    status: str
    rejection_reason: Optional[str]
    paid_at: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only: ONLY id + created_at
class WarrantyTransfer(TypedDict, total=False):
    id: str
    created_at: str
    system_id: str
    transfer_kind: str
    new_owner_name: str
    new_owner_email: str
    effective_date: str
    preserved_months: int
    approval_source: str
    status: str
    rejection_reason: Optional[str]


# common_fields: true
class ProactiveCampaign(TypedDict, total=False):
    id: str
    lot_id: str
    origin: str
    replacement_model_code: str
    max_units: int
    guaranteed_units: int
    status: str
    target_unit_count: int
    dispatched_count: int
    canceled_count: int
    window_start_at: Optional[str]
    window_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only: ONLY id + created_at
class ReplacementOrder(TypedDict, total=False):
    id: str
    created_at: str
    claim_id: Optional[str]
    campaign_id: Optional[str]
    unit_id: str
    replacement_model_code: str
    compatibility_class: str
    status: str
    dispatched_at: Optional[str]
    installed_at: Optional[str]