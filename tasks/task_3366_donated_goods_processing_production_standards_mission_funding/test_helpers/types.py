"""Domain types: entity shapes, status enums, and role enum for the Donated Goods API.

Entities fall into two weight classes per the PRD's common-resource rules:
most resources carry id + created_at + updated_at + version, while Territory,
DonationSite, and DisposalTicket are lightweight and carry only id + created_at.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BRAND_REGULATOR = "BrandRegulator"
    MEMBER_ADMIN = "MemberAdmin"
    DONATION_ATTENDANT = "DonationAttendant"
    STORE_ASSOCIATE = "StoreAssociate"
    PRODUCTION_LEAD = "ProductionLead"
    PROGRAM_DIRECTOR = "ProgramDirector"
    MEMBER_CFO = "MemberCFO"
    CONTRACT_MANAGER = "ContractManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class BrandLicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CostingMethod(str, Enum):
    STANDARD = "STANDARD"
    ACTUAL = "ACTUAL"


class MarginHealth(str, Enum):
    HEALTHY = "HEALTHY"
    LOW = "LOW"


class SiteType(str, Enum):
    ADC = "ADC"
    STORE_DROP = "STORE_DROP"


class DonationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SORTED = "SORTED"


class ItemCategory(str, Enum):
    TEXTILES = "TEXTILES"
    HOUSEWARES = "HOUSEWARES"
    MEDIA = "MEDIA"
    FURNITURE = "FURNITURE"
    EWASTE = "EWASTE"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    UNSALABLE = "UNSALABLE"


class DonatedItemStatus(str, Enum):
    SORTED = "SORTED"
    ON_FLOOR = "ON_FLOOR"
    SOLD = "SOLD"
    SALVAGED = "SALVAGED"


class ColorTag(str, Enum):
    BLUE = "BLUE"
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class StandardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RunStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PerformanceFlag(str, Enum):
    MET = "MET"
    MISSED = "MISSED"


class SalvageChannel(str, Enum):
    TEXTILE_BALE = "TEXTILE_BALE"
    EWASTE = "EWASTE"
    OUTLET_BIN = "OUTLET_BIN"


class SalvageLotStatus(str, Enum):
    OPEN = "OPEN"
    SOLD = "SOLD"


class ProgramType(str, Enum):
    JOB_TRAINING = "JOB_TRAINING"
    PLACEMENT = "PLACEMENT"
    SUPPORT = "SUPPORT"


class AllocationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    CANCELLED = "CANCELLED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    BREACH = "BREACH"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    ATTESTED = "ATTESTED"
    MISSED = "MISSED"


class DisposalMaterial(str, Enum):
    MIXED_UNSALABLE = "MIXED_UNSALABLE"
    HAZARD = "HAZARD"
    FURNITURE = "FURNITURE"


# ---------------------------------------------------------------------------
# Entity shapes (full-weight resources: id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class MemberOrg(TypedDict, total=False):
    id: str
    name: str
    brand_license_status: str
    costing_method: str
    reserve_floor_cents: int
    diversion_floor_bps: int
    retail_margin_pool_cents: int
    reserved_cents: int
    margin_health: str
    contract_revenue_cents: int
    total_diverted_lbs: float
    total_disposed_lbs: float
    diversion_rate_bps: int
    diversion_compliant: bool
    last_markdown_week: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict, total=False):
    id: str
    site_id: str
    donor_name: str
    donor_email: Optional[str]
    item_count_declared: int
    status: str
    receipt_issued: bool
    receipt_token: Optional[str]
    receipt_fmv_total_cents: Optional[int]
    sorted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonatedItem(TypedDict, total=False):
    id: str
    donation_id: str
    category: str
    condition_grade: str
    estimated_value_cents: int
    weight_lbs: float
    status: str
    price_cents: Optional[int]
    current_selling_price_cents: Optional[int]
    color_tag: Optional[str]
    floor_week: Optional[int]
    markdown_step: int
    priced_standard_id: Optional[str]
    unit_cost_cents: Optional[int]
    salvage_lot_id: Optional[str]
    sold_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionStandard(TypedDict, total=False):
    id: str
    member_org_id: str
    category: str
    target_items_per_hour: int
    hourly_cost_cents: int
    grade_price_map: dict
    price_floor_cents: int
    price_ceiling_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcessingRun(TypedDict, total=False):
    id: str
    site_id: str
    production_standard_id: str
    category: str
    status: str
    item_count_processed: Optional[int]
    unsalable_count: Optional[int]
    labor_minutes: Optional[int]
    labor_cost_cents: Optional[int]
    gross_rate_iph: Optional[float]
    net_rate_iph: Optional[float]
    variance_bps: Optional[int]
    performance_flag: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalvageLot(TypedDict, total=False):
    id: str
    member_org_id: str
    channel: str
    status: str
    total_weight_lbs: float
    item_count: int
    sale_revenue_cents: Optional[int]
    sold_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MissionProgram(TypedDict, total=False):
    id: str
    member_org_id: str
    name: str
    program_type: str
    start_date: str
    end_date: str
    funding_goal_cents: int
    funding_disbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class FundingAllocation(TypedDict, total=False):
    id: str
    mission_program_id: str
    amount_cents: int
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkforceContract(TypedDict, total=False):
    id: str
    member_org_id: str
    funding_agency: str
    start_date: str
    end_date: str
    contract_value_cents: int
    enrolled_headcount: int
    created_by_user_id: str
    status: str
    compliance_posture: str
    attested_payout_cents: int
    missed_count: int
    created_at: str
    updated_at: str
    version: int


class ContractMilestone(TypedDict, total=False):
    id: str
    contract_id: str
    description: str
    target_date: str
    min_headcount: int
    payout_cents: int
    status: str
    attested_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lightweight resources: id + created_at only (no updated_at, no version)
# ---------------------------------------------------------------------------

class Territory(TypedDict, total=False):
    id: str
    member_org_id: str
    region_code: str
    effective_from: str
    effective_to: Optional[str]
    created_at: str


class DonationSite(TypedDict, total=False):
    id: str
    member_org_id: str
    name: str
    site_type: str
    created_at: str


class DisposalTicket(TypedDict, total=False):
    id: str
    member_org_id: str
    material: str
    weight_lbs: float
    cost_cents: int
    created_at: str
