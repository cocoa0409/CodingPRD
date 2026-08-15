"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SHOP_ADMIN = "ShopAdmin"
    QC_MANAGER = "QCManager"
    WELD_LEAD = "WeldLead"
    WELDER = "Welder"
    CWI = "CWI"
    MATERIAL_CONTROLLER = "MaterialController"
    PRODUCTION_PLANNER = "ProductionPlanner"
    QUALITY_INSPECTOR = "QualityInspector"
    SHIPPING_CLERK = "ShippingClerk"


class ProcessType(str, Enum):
    SMAW = "SMAW"
    GMAW = "GMAW"
    FCAW = "FCAW"
    GTAW = "GTAW"
    SAW = "SAW"


class WelderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class NDTVendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OvenStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    QUARANTINED = "QUARANTINED"


class PQRStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class WPSStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class QualificationStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class LotStatus(str, Enum):
    IN_OVEN = "IN_OVEN"
    ISSUED = "ISSUED"
    EXPOSED = "EXPOSED"
    QUARANTINED = "QUARANTINED"
    EXHAUSTED = "EXHAUSTED"
    CONSUMED = "CONSUMED"


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    RETURNED = "RETURNED"
    VOID = "VOID"


class FixtureStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"
    UNDER_REPAIR = "UNDER_REPAIR"


class OwnerParty(str, Enum):
    SHOP = "SHOP"
    CUSTOMER = "CUSTOMER"


class ShopOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class WeldmentPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"
    REPAIR_REVIEW = "REPAIR_REVIEW"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class JointFabricationStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    WELDED_OUT = "WELDED_OUT"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"


class JointInspectionStatus(str, Enum):
    NOT_READY = "NOT_READY"
    READY_FOR_VT = "READY_FOR_VT"
    VT_PASSED = "VT_PASSED"
    NDT_IN_PROGRESS = "NDT_IN_PROGRESS"
    NDT_PASSED = "NDT_PASSED"
    NDT_FAILED = "NDT_FAILED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    REPAIR_WELDED_OUT = "REPAIR_WELDED_OUT"


class NDTMethod(str, Enum):
    VT = "VT"
    UT = "UT"
    RT = "RT"


class Disposition(str, Enum):
    PENDING = "PENDING"
    REWORK = "REWORK"
    USE_AS_IS = "USE_AS_IS"
    SCRAP = "SCRAP"


class StepCode(str, Enum):
    FIT_UP = "FIT_UP"
    WELD_OUT = "WELD_OUT"
    VT = "VT"
    NDT = "NDT"
    FINAL = "FINAL"


# --- Entity TypedDicts ---
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# The five ledger-style records (ConsumableIssue, WeldPass, DistortionReport,
# Inspection, TravelerSignOff) carry only id + created_at (PRD §2.4).


class Shop(TypedDict):
    id: str
    shop_name: str
    aws_d1_1_revision: str
    repair_rate_limit_pct: int
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class Welder(TypedDict):
    id: str
    shop_id: str
    stencil: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NDTVendor(TypedDict):
    id: str
    shop_id: str
    vendor_name: str
    supported_methods: List[str]
    hourly_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Oven(TypedDict):
    id: str
    shop_id: str
    oven_code: str
    holding_temp_c: int
    capacity_electrodes_kg: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PQR(TypedDict):
    id: str
    shop_id: str
    pqr_number: str
    process: str
    base_metal_spec: str
    thickness_range_min_mm: float
    thickness_range_max_mm: float
    test_report_id: str
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WPS(TypedDict):
    id: str
    shop_id: str
    wps_number: str
    revision: int
    pqr_id: str
    pinned_pqr_version: Optional[int]
    process: str
    base_metal_spec: str
    thickness_min_mm: float
    thickness_max_mm: float
    superseded_by_id: Optional[str]
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WelderQualification(TypedDict):
    id: str
    shop_id: str
    welder_id: str
    wps_id: str
    process: str
    qualified_at_utc: str
    last_weld_at_utc: str
    continuity_expires_at_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsumableLot(TypedDict):
    id: str
    shop_id: str
    lot_number: str
    filler_spec: str
    process: str
    received_kg: float
    remaining_kg: float
    exposed_minutes_total: int
    rebake_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsumableIssue(TypedDict):
    # Append-only ledger record: id + created_at only (no updated_at/version).
    id: str
    shop_id: str
    lot_id: str
    oven_id: str
    issued_to_welder_id: str
    issued_kg: float
    issued_at_utc: str
    returned_at_utc: Optional[str]
    exposure_minutes: int
    status: str
    created_at: str


class Fixture(TypedDict):
    id: str
    shop_id: str
    fixture_code: str
    capacity_weldments: int
    owner_party: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShopOrder(TypedDict):
    id: str
    shop_id: str
    po_number: str
    customer_name: str
    promised_ship_date_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Weldment(TypedDict):
    id: str
    shop_id: str
    shop_order_id: str
    weldment_serial: str
    fixture_id: str
    drawing_revision: str
    posture: str
    repair_pass_count: int
    total_pass_count: int
    repair_rate_pct: float
    distortion_count: int
    signed_off_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Joint(TypedDict):
    id: str
    shop_id: str
    weldment_id: str
    joint_number: str
    wps_id: str
    base_metal_thickness_mm: float
    required_ndt_methods: List[str]
    fabrication_status: str
    inspection_status: str
    repair_cycle_count: int
    created_at: str
    updated_at: str
    version: int


class WeldPass(TypedDict):
    # Append-only ledger record: id + created_at only (no updated_at/version).
    id: str
    shop_id: str
    joint_id: str
    welder_id: str
    qualification_id: str
    consumable_lot_id: str
    consumable_used_kg: float
    is_repair: bool
    welded_at_utc: str
    created_at: str


class DistortionReport(TypedDict):
    # Append-only ledger record: id + created_at only (no updated_at/version).
    id: str
    shop_id: str
    weldment_id: str
    joint_id: str
    measured_deviation_mm: float
    tolerance_mm: float
    reported_by_user_id: str
    reported_at_utc: str
    disposition: str
    created_at: str


class Inspection(TypedDict):
    # Append-only ledger record: id + created_at only (no updated_at/version).
    id: str
    shop_id: str
    joint_id: str
    method: str
    inspector_user_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    vendor_id: Optional[str]
    result: Optional[str]
    result_code: Optional[str]
    resulted_at_utc: Optional[str]
    hold_point_released: bool
    created_at: str


class TravelerSignOff(TypedDict):
    # Append-only ledger record: id + created_at only (no updated_at/version).
    id: str
    shop_id: str
    weldment_id: str
    step_code: str
    signed_by_user_id: str
    signed_at_utc: str
    notes: Optional[str]
    created_at: str
