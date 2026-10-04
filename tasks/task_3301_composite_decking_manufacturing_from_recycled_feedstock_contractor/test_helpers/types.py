"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, Optional, TypedDict


class UserRole(str, Enum):
    OPS_MANAGER = "OpsManager"
    QUALITY_ENGINEER = "QualityEngineer"
    PROCESS_ENGINEER = "ProcessEngineer"
    PRODUCT_MANAGER = "ProductManager"
    CHANNEL_MANAGER = "ChannelManager"
    DEALER_SALES_REP = "DealerSalesRep"
    DEALER = "Dealer"
    PROGRAM_ADMIN = "ProgramAdmin"
    CONTRACTOR = "Contractor"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


class SeasonPosture(str, Enum):
    PRE_SEASON = "PRE_SEASON"
    SELLING = "SELLING"


class SupplierKind(str, Enum):
    COLLECTION_PROGRAM = "COLLECTION_PROGRAM"
    BROKER = "BROKER"


class QualityTier(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class Material(str, Enum):
    PCR_FILM = "PCR_FILM"
    WOOD_FLOUR = "WOOD_FLOUR"
    REPRO_PE = "REPRO_PE"
    VIRGIN_PE = "VIRGIN_PE"


class LotStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class ReleaseDisposition(str, Enum):
    PRODUCTION = "PRODUCTION"
    SUPPORT_STOCK = "SUPPORT_STOCK"


class FormulationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ProductLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"
    REPAIRED_SUPPORTED = "REPAIRED_SUPPORTED"
    SUNSET = "SUNSET"


class Profile(str, Enum):
    GROOVED = "GROOVED"
    SQUARE = "SQUARE"
    FASCIA = "FASCIA"


class Emboss(str, Enum):
    WOODGRAIN = "WOODGRAIN"
    SMOOTH = "SMOOTH"


class DealerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class CommitmentStatus(str, Enum):
    OPEN = "OPEN"
    MET = "MET"
    SHORTFALL_PENALIZED = "SHORTFALL_PENALIZED"
    WAIVED = "WAIVED"


class AllocationStatus(str, Enum):
    OPEN = "OPEN"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RunKind(str, Enum):
    SELLABLE = "SELLABLE"
    SUPPORT_STOCK = "SUPPORT_STOCK"
    NULL_SLOT = "NULL_SLOT"


class LotDisposition(str, Enum):
    AVAILABLE = "AVAILABLE"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    CONSUMED_BY_CLAIM = "CONSUMED_BY_CLAIM"
    SCRAPPED = "SCRAPPED"


class ContractorStatus(str, Enum):
    APPLIED = "APPLIED"
    IN_TRAINING = "IN_TRAINING"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"


class Tier(str, Enum):
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ModuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TrainingRecordStatus(str, Enum):
    ENROLLED = "ENROLLED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class LeadStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    EXPIRED = "EXPIRED"
    DECLINED = "DECLINED"


class RegistrationStatus(str, Enum):
    PENDING = "PENDING"
    INSTALLED = "INSTALLED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    SAMPLE_REQUESTED = "SAMPLE_REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ClaimCategory(str, Enum):
    FADING = "FADING"
    STAINING = "STAINING"
    STRUCTURAL = "STRUCTURAL"


class LabVerdict(str, Enum):
    CONFIRMS_DEFECT = "CONFIRMS_DEFECT"
    CONTRADICTS_CLAIM = "CONTRADICTS_CLAIM"
    INCONCLUSIVE = "INCONCLUSIVE"


class SampleStatus(str, Enum):
    AWAITING = "AWAITING"
    RECEIVED = "RECEIVED"
    REVIEWED = "REVIEWED"


class KitType(str, Enum):
    DISPLAY_BOARD = "DISPLAY_BOARD"
    CHIP_SET = "CHIP_SET"


class KitStatus(str, Enum):
    ORDERED = "ORDERED"
    DELIVERED = "DELIVERED"
    RETIRED = "RETIRED"


class ChipRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class PriceBookStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class Plant(TypedDict):
    id: str
    name: str
    daily_capacity_lf: int
    lines: int
    resin_store: Dict[str, int]
    fg_store: Dict[str, int]
    reserved_fg_store: Dict[str, int]
    pre_season_window_start: str
    pre_season_window_end: str
    season_posture: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    name: str
    kind: str
    quality_tier: str
    reliability_score_bp: int
    created_at: str
    updated_at: str
    version: int


class CollectionProgram(TypedDict):
    id: str
    supplier_id: str
    region: str
    rebate_per_lb_cents: int
    accrued_rebate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeedstockLot(TypedDict):
    id: str
    supplier_id: str
    material: str
    weight_lbs: int
    received_date: str
    status: str
    moisture_pct: float
    contamination_ppm: int
    melt_flow_index: Optional[float]
    certificate_ref: str
    release_disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Formulation(TypedDict):
    id: str
    name: str
    lines: list
    status: str
    active_revision: int
    current_revision_hash: str
    created_at: str
    updated_at: str
    version: int


class ProductLine(TypedDict):
    id: str
    name: str
    color: str
    capped: bool
    profile: str
    emboss: str
    board_length_ft: int
    formulation_id: str
    repair_support_only: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict):
    id: str
    name: str
    territory_code: str
    credit_limit_cents: int
    outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShipmentOrder(TypedDict):
    id: str
    dealer_id: str
    product_line_id: str
    lf: int
    ship_week_start: str
    status: str
    invoiced_cents: Optional[int]
    actual_ship_date: Optional[str]
    price_book_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StockingCommitment(TypedDict):
    id: str
    dealer_id: str
    territory_code: str
    product_line_id: str
    committed_lf: int
    season_year: int
    fulfilled_lf: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationCommitment(TypedDict):
    id: str
    dealer_id: str
    product_line_id: str
    reserved_lf: int
    price_book_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    plant_id: str
    product_line_id: str
    formulation_revision: int
    planned_lf: int
    actual_lf: Optional[int]
    production_date: str
    line_slot: Optional[int]
    changeover_minutes: int
    total_minutes: int
    run_kind: str
    reservation_id: Optional[str]
    board_lot_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardLot(TypedDict):
    id: str
    plant_id: str
    production_run_id: str
    product_line_id: str
    formulation_revision: int
    lf: int
    produced_at: str
    support_tagged: bool
    disposition: str
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict):
    id: str
    name: str
    email: str
    status: str
    tier: str
    certified_at: Optional[str]
    completed_project_count: int
    enhanced_warranty_count: int
    created_at: str
    updated_at: str
    version: int


class TrainingModule(TypedDict):
    id: str
    title: str
    version_no: int
    duration_hours: float
    required_for_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict):
    id: str
    contractor_id: str
    module_id: str
    status: str
    passed_module_version: Optional[int]
    passed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeadReferral(TypedDict):
    id: str
    homeowner_name: str
    zip_code: str
    submitted_by_dealer_id: str
    assigned_contractor_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallRegistration(TypedDict):
    id: str
    contractor_id: str
    dealer_id: str
    product_line_id: str
    install_date: str
    registered_at: str
    completion_date: Optional[str]
    enhanced_warranty: bool
    warranty_years: int
    board_lot_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    install_registration_id: str
    category: str
    filed_at: str
    status: str
    adjudication: Optional[str]
    credit_amount_cents: Optional[int]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimSample(TypedDict):
    id: str
    warranty_claim_id: str
    received_at: Optional[str]
    lab_verdict: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SampleKit(TypedDict):
    id: str
    dealer_id: str
    product_line_id: str
    kit_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ColorChipRequest(TypedDict):
    id: str
    dealer_id: str
    product_line_id: str
    quantity: int
    status: str
    chip_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceBook(TypedDict):
    id: str
    name: str
    effective_from: str
    base_prices: Dict[str, int]
    tier_discounts_bp: Dict[str, int]
    status: str
    created_at: str
    updated_at: str
    version: int
