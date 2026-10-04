"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    CONTRACTS_OFFICER = "ContractsOfficer"
    CUSTOMER_ADMIN = "CustomerAdmin"
    SUPPLY_CHAIN_AUDITOR = "SupplyChainAuditor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    WARRANTY_ADMINISTRATOR = "WarrantyAdministrator"
    RECYCLING_COORDINATOR = "RecyclingCoordinator"


class CreditTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class Technology(str, Enum):
    CDTE_THIN_FILM = "CDTE_THIN_FILM"
    CDTE_THIN_FILM_CUTE = "CDTE_THIN_FILM_CUTE"


class ModuleSeriesStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ProductionLineStatus(str, Enum):
    COMMISSIONING = "COMMISSIONING"
    RAMPING = "RAMPING"
    AT_CAPACITY = "AT_CAPACITY"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class QualificationTier(str, Enum):
    QUALIFIED = "QUALIFIED"
    PROVISIONAL = "PROVISIONAL"
    UNQUALIFIED = "UNQUALIFIED"


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    ACTIVE = "ACTIVE"
    CONSTRAINED = "CONSTRAINED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULED = "RESCHEDULED"
    DELIVERED = "DELIVERED"
    RECALLED = "RECALLED"
    CANCELLED = "CANCELLED"


class DeliveryContentStatus(str, Enum):
    UNEVALUATED = "UNEVALUATED"
    QUALIFIED_DOMESTIC = "QUALIFIED_DOMESTIC"
    NON_QUALIFYING = "NON_QUALIFYING"


class ComponentType(str, Enum):
    SEMICONDUCTOR_FEEDSTOCK = "SEMICONDUCTOR_FEEDSTOCK"
    GLASS = "GLASS"
    BACKSHEET = "BACKSHEET"
    FRAME = "FRAME"
    JUNCTION_BOX = "JUNCTION_BOX"


class ComponentLotStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    VERIFIED = "VERIFIED"
    QUARANTINED = "QUARANTINED"


class AttestationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"


class RecyclingObligationStatus(str, Enum):
    OPEN = "OPEN"
    COLLECTING = "COLLECTING"
    RECOVERED = "RECOVERED"
    SETTLED = "SETTLED"


class ClaimType(str, Enum):
    PRODUCT_DEFECT = "PRODUCT_DEFECT"
    PERFORMANCE_SHORTFALL = "PERFORMANCE_SHORTFALL"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry the full common-field set:
# id, created_at, updated_at, version — PRD §2.4)
# ---------------------------------------------------------------------------

class Customer(TypedDict, total=False):
    id: str
    legal_name: str
    credit_tier: str
    tax_credit_flag: bool
    created_at: str
    updated_at: str
    version: int


class BinProfileEntry(TypedDict):
    bin_code: str
    wattage: float
    fraction: float


class ModuleSeries(TypedDict, total=False):
    id: str
    series_code: str
    technology: str
    nominal_wattage: float
    bin_profile: List[BinProfileEntry]
    temp_coefficient: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict, total=False):
    id: str
    line_code: str
    site_country: str
    annual_capacity_mw: float
    committed_capacity_mw: float
    reserved_capacity_mw: float
    available_capacity_mw: float
    warranty_reserved_mw: float
    ramp_quarter_index: int
    actual_yield_rate: Optional[float]
    qualification_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityReservation(TypedDict, total=False):
    id: str
    customer_id: str
    line_id: str
    series_id: str
    delivery_year: int
    contracted_mw: float
    price_usd_per_w: float
    deposit_usd: float
    term_years: int
    delivered_mw: float
    deposit_forfeited_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BinCount(TypedDict):
    bin_code: str
    count: int


class ProductionRun(TypedDict, total=False):
    id: str
    line_id: str
    series_id: str
    quarter: int
    input_modules: int
    good_modules: int
    bin_counts: List[BinCount]
    run_yield_rate: float
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict, total=False):
    id: str
    reservation_id: str
    scheduled_window_start: str
    scheduled_window_end: str
    volume_mw: float
    lot_ids: List[str]
    schedule_status: str
    content_status: str
    created_at: str
    updated_at: str
    version: int


class ComponentLot(TypedDict, total=False):
    id: str
    supplier_name: str
    lot_code: str
    component_type: str
    country_of_origin: str
    lot_cost_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceAttestation(TypedDict, total=False):
    id: str
    line_id: str
    period_year: int
    labor_cost_usd: float
    feedstock_cost_usd: float
    glass_cost_usd: float
    balance_of_system_cost_usd: float
    overhead_cost_usd: float
    total_manufactured_cost_usd: float
    printed_content_pct: float
    adjusted_content_pct: float
    manufactured_products_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RecyclingObligation(TypedDict, total=False):
    id: str
    customer_id: str
    period_year: int
    shipped_volume_mw: float
    required_collected_mw: float
    collected_volume_mw: float
    fulfillment_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    reservation_id: str
    claim_type: str
    claimed_mw: float
    measured_energy_kwh: Optional[float]
    claim_amount_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int
