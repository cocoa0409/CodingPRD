"""TypedDict shapes for every resource the PRD declares.

Thirteen of the fourteen resources carry ``id``, ``created_at``, ``updated_at``
and ``version``. ``LiningInspection`` is the declared exception: it carries only
``id`` and ``created_at``, so its shape deliberately omits the mutation-tracking
pair rather than marking them optional.
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict

Role = Literal[
    "PlantAdmin",
    "PlantOperator",
    "QualityInspector",
    "ComplianceEngineer",
    "CertificationApprover",
    "SupplierQualityManager",
    "WarrantyAnalyst",
    "SupplierRep",
]

ComponentCategory = Literal[
    "GAS_VALVE", "THERMOSTAT", "TP_RELIEF_VALVE", "ANODE", "COMPRESSOR", "ECO_SWITCH"
]
FuelType = Literal["GAS", "ELECTRIC", "HEAT_PUMP"]
Channel = Literal["TRADE", "RETAIL", "BUILDER"]
TestType = Literal["UEF", "FIRST_HOUR_RATING", "RECOVERY"]
InspectionType = Literal["ADHESION", "HOLIDAY"]
InspectionResult = Literal["PASS", "FAIL"]
RecordStatus = Literal["CURRENT", "SUPERSEDED"]
FailureMode = Literal[
    "TANK_LEAK", "ANODE_DEPLETION", "THERMOSTAT", "GAS_VALVE", "COMPRESSOR", "OTHER"
]
RemedyType = Literal[
    "TANK_REPLACEMENT", "GAS_VALVE_KIT", "TP_VALVE_KIT", "FULL_UNIT_REPLACEMENT"
]
HardnessBand = Literal["SOFT", "MODERATE", "HARD", "VERY_HARD"]

SupplierStatus = Literal["PENDING", "QUALIFIED", "CONDITIONAL", "DISQUALIFIED"]
ComponentLotStatus = Literal["QUARANTINED", "RELEASED", "REJECTED", "BLOCKED", "CONSUMED"]
BatchStatus = Literal["MIXED", "FIRED", "QUARANTINED"]
CertificationDimension = Literal[
    "UNCERTIFIED", "TEST_PENDING", "CERTIFIED", "SUSPENDED", "DECERTIFIED"
]
ReleaseDimension = Literal["DRAFT", "RELEASED", "RESTRICTED", "WITHDRAWN"]
TankLotStatus = Literal[
    "FAB_QUEUED",
    "WELDED",
    "LINED",
    "LINING_VERIFIED",
    "LINING_REJECTED",
    "RELINE_QUEUED",
    "FOAMED",
    "JACKETED",
    "RELEASED",
    "SCRAPPED",
]
TestStatus = Literal["SCHEDULED", "PASSED", "FAILED", "VOIDED"]
CertificationStatus = Literal[
    "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "REVOKED", "SUPERSEDED"
]
BuildStatus = Literal[
    "COMPONENTS_STAGED", "ASSEMBLED", "LABELED", "SHIPPED", "HELD", "SCRAPPED"
]
LabelStatus = Literal["NONE", "APPLIED", "INVALID"]
ClaimStatus = Literal["OPEN", "VALIDATED", "DENIED", "PAID"]
CampaignStatus = Literal[
    "DRAFT", "SCOPED", "ANNOUNCED", "IN_REMEDY", "CLOSED", "CANCELLED"
]
NoticeStatus = Literal["PENDING", "NOTIFIED", "REMEDIED", "UNREACHABLE"]


class SystemFields(TypedDict):
    """The four system fields carried by every resource except LiningInspection."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Supplier(SystemFields, total=False):
    name: str
    component_category: ComponentCategory
    audit_score: int
    defect_ppm: int
    open_capa_count: int
    qualification_status: SupplierStatus
    qualification_score: Optional[float]
    qualified_until: Optional[str]
    disqualification_reason_code: Optional[str]
    blocked_lot_count: int


class ComponentLot(SystemFields, total=False):
    supplier_id: str
    part_number: str
    category: ComponentCategory
    quantity: int
    certificate_of_conformance: bool
    status: ComponentLotStatus
    reject_reason_code: Optional[str]
    consumed_quantity: int
    remaining_quantity: int


class Furnace(SystemFields, total=False):
    furnace_code: str
    max_firing_temp_c: int
    occupied_window_count: int


class GlassLiningBatch(SystemFields, total=False):
    furnace_id: str
    batch_code: str
    slurry_mix_code: str
    firing_temp_c: int
    firing_start: str
    firing_end: str
    status: BatchStatus
    quarantine_reason_code: Optional[str]
    assigned_lot_count: int
    rejected_lot_count: int


class ProductModel(SystemFields, total=False):
    model_code: str
    fuel_type: FuelType
    nominal_capacity_gallons: int
    channel: Channel
    insulation_r_value: float
    is_private_label: bool
    base_model_id: Optional[str]
    brand_label: Optional[str]
    certification_status: CertificationDimension
    release_status: ReleaseDimension
    uef_rated: Optional[float]
    fhr_rated: Optional[float]
    recovery_rate_rated: Optional[float]
    label_serial_prefix: Optional[str]
    held_unit_count: int
    warranty_reserve_accrued_cents: int
    warranty_paid_cents: int
    warranty_reserve_balance_cents: int


class TestCell(SystemFields, total=False):
    cell_code: str
    parallel_slots: int
    cooldown_hours: int


class EfficiencyTest(SystemFields, total=False):
    product_model_id: str
    test_cell_id: str
    test_type: TestType
    sample_size: int
    window_start: str
    window_end: str
    status: TestStatus
    measured_value: Optional[float]
    effective_minimum: Optional[float]
    margin: Optional[float]
    recorded_at: Optional[str]


class RatingCertification(SystemFields, total=False):
    product_model_id: str
    status: CertificationStatus
    certified_uef: Optional[float]
    certified_fhr: Optional[float]
    certified_recovery: Optional[float]
    uef_test_count: Optional[int]
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    effective_date: Optional[str]
    label_serial_prefix: Optional[str]
    reason_code: Optional[str]


class TankLot(SystemFields, total=False):
    product_model_id: str
    lot_code: str
    planned_quantity: int
    production_period: str
    status: TankLotStatus
    wip_quantity: int
    good_quantity: int
    scrapped_quantity: int
    rework_count: int
    last_scrap_quantity: Optional[int]
    cascade_rejected: bool
    glass_lining_batch_id: Optional[str]
    weld_operator_user_id: Optional[str]
    foam_density_kg_m3: Optional[float]
    foam_thickness_mm: Optional[int]
    achieved_r_value: Optional[float]
    unit_count: int


class LiningInspection(TypedDict, total=False):
    """Immutable record: the PRD grants it ``id`` and ``created_at`` only."""

    id: str
    created_at: str
    tank_lot_id: str
    inspection_type: InspectionType
    sample_size: int
    holiday_count: Optional[int]
    adhesion_class: Optional[int]
    holidays_per_tank: Optional[float]
    result: InspectionResult
    record_status: RecordStatus
    scrap_quantity: Optional[int]
    inspector_user_id: str


class HeaterUnit(SystemFields, total=False):
    tank_lot_id: str
    product_model_id: str
    gas_control_lot_id: Optional[str]
    safety_valve_lot_id: str
    production_period: str
    build_status: BuildStatus
    held_from_status: Optional[BuildStatus]
    hold_reason_code: Optional[str]
    label_status: LabelStatus
    serial_number: Optional[str]
    shipped_at: Optional[str]
    distribution_channel: Optional[Channel]
    install_water_hardness_gpg: Optional[float]
    water_hardness_band: Optional[HardnessBand]
    hardness_factor: Optional[float]
    months_in_service: Optional[int]


class WarrantyClaim(SystemFields, total=False):
    heater_unit_id: str
    failure_mode: FailureMode
    reported_water_hardness_gpg: float
    months_in_service_at_report: int
    status: ClaimStatus
    coverage_pct: Optional[float]
    approved_payout_cents: Optional[int]
    paid_at: Optional[str]
    reason_code: Optional[str]


class RecallCampaign(SystemFields, total=False):
    campaign_code: str
    scope_product_model_id: str
    remedy_type: RemedyType
    budget_cents: int
    status: CampaignStatus
    serial_range_start: Optional[str]
    serial_range_end: Optional[str]
    affected_unit_count: int
    per_unit_remedy_cost_cents: Optional[int]
    estimated_remedy_cost_cents: Optional[int]
    notice_count: int
    remedied_count: int
    unreachable_count: int
    completion_pct_notice_based: float
    completion_pct_population_based: float


class RecallNotice(SystemFields, total=False):
    recall_campaign_id: str
    heater_unit_id: str
    status: NoticeStatus
    remedy_cost_cents: int
    notified_at: Optional[str]
    remedied_at: Optional[str]


class WarrantyAnalysis(TypedDict, total=False):
    """Computed report returned by the warranty-analysis read."""

    product_model_id: str
    production_period: str
    variant: str
    shipped_unit_count: int
    tank_leak_claim_count: int
    weighted_exposure_unit_months: float
    failure_rate_ppm: float
    soft_unit_count: int
    moderate_unit_count: int
    hard_unit_count: int
    very_hard_unit_count: int


class CompletionReport(TypedDict, total=False):
    """Computed report returned by the recall completion read."""

    recall_campaign_id: str
    affected_unit_count: int
    notice_count: int
    remedied_count: int
    unreachable_count: int
    completion_pct_notice_based: float
    completion_pct_population_based: float


JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
