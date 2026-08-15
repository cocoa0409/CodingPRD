"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity narratives (sections 3.1-3.9) and the global
common-field rules (section 2.4). Immutable event records carry only
``id`` and ``created_at``; every other primary resource also carries
``updated_at`` and ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ASSEMBLY_LEAD = "AssemblyLead"
    QUALITY_ENGINEER = "QualityEngineer"
    SAFETY_OFFICER = "SafetyOfficer"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    CARRIER_AGENT = "CarrierAgent"
    CUSTOMER_SERVICE = "CustomerService"
    ANY = "Any"


class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CellLotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QUARANTINE = "QUARANTINE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class InspectionOutcome(str, Enum):
    PASS = "PASS"
    FAIL_SOFT = "FAIL_SOFT"
    FAIL_HARD = "FAIL_HARD"


class WeldingProfile(str, Enum):
    WELD_PROFILE_A = "WELD_PROFILE_A"
    WELD_PROFILE_B = "WELD_PROFILE_B"
    WELD_PROFILE_C = "WELD_PROFILE_C"


class AssemblyStatus(str, Enum):
    BUILT = "BUILT"
    WELD_RECORDED = "WELD_RECORDED"
    WELD_CERTIFIED = "WELD_CERTIFIED"
    BMS_FLASHED = "BMS_FLASHED"
    TEST_QUEUED = "TEST_QUEUED"
    CLASSIFIED = "CLASSIFIED"
    READY_TO_STORE = "READY_TO_STORE"
    RECALLED = "RECALLED"


class LogisticsStatus(str, Enum):
    NOT_STORED = "NOT_STORED"
    STAGED = "STAGED"
    STORED = "STORED"
    PICKED = "PICKED"
    PACKED_FOR_SHIP = "PACKED_FOR_SHIP"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


class SocBand(str, Enum):
    SOC_LOW = "SOC_LOW"
    SOC_MID = "SOC_MID"
    SOC_HIGH = "SOC_HIGH"


class ShippingClassification(str, Enum):
    NONE = "NONE"
    UN3480 = "UN3480"
    UN3481 = "UN3481"
    UN3090 = "UN3090"
    UN3091 = "UN3091"


class PackDisposition(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    RETURN_PENDING = "RETURN_PENDING"
    DISCHARGED = "DISCHARGED"
    SCRAPPED = "SCRAPPED"
    RECALLED_HOLD = "RECALLED_HOLD"


class FirmwareStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    DEPRECATED = "DEPRECATED"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REVOKE = "REVOKE"


class DossierStatus(str, Enum):
    OPEN = "OPEN"
    TESTS_RECORDED = "TESTS_RECORDED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    FAILED = "FAILED"


class DossierOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class FireZone(str, Enum):
    ZONE_A = "ZONE_A"
    ZONE_B = "ZONE_B"
    ZONE_C = "ZONE_C"
    ZONE_ISOLATION = "ZONE_ISOLATION"


class PlacementStatus(str, Enum):
    STAGED = "STAGED"
    STORED = "STORED"
    RELEASED = "RELEASED"


class ShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    TENDERED = "TENDERED"
    CARRIER_ACCEPTED = "CARRIER_ACCEPTED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CARRIER_REJECTED = "CARRIER_REJECTED"


class UnClassCode(str, Enum):
    UN3480 = "UN3480"
    UN3481 = "UN3481"
    UN3090 = "UN3090"
    UN3091 = "UN3091"


class RmaReasonCode(str, Enum):
    DEFECT = "DEFECT"
    WARRANTY = "WARRANTY"
    OVERSTOCK = "OVERSTOCK"
    RECALL_RETURN = "RECALL_RETURN"


class RmaStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DISCHARGE_PENDING = "DISCHARGE_PENDING"
    DISCHARGED = "DISCHARGED"
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"
    DENIED = "DENIED"


class RecallSeverity(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CONTAINED = "CONTAINED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class IntegrationProgram(TypedDict):
    id: str
    program_code: str
    compliance_risk_index: float
    storage_capacity_wh: int
    wh_committed: float
    wh_available: float
    recall_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CellLot(TypedDict):
    id: str
    program_id: str
    lot_code: str
    cell_count: int
    rated_capacity_mah: int
    receiving_soc_percent: float
    measured_soc_percent: Optional[float]
    quarantine_cycle_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CellInspectionRecord(TypedDict):
    # Immutable event record: only id + created_at, no updated_at / version.
    id: str
    created_at: str
    cell_lot_id: str
    program_id: str
    inspector_id: str
    measured_soc_percent: float
    measured_voltage_v: float
    visual_defect_count: int
    outcome: str


class PackBOM(TypedDict):
    id: str
    program_id: str
    bom_code: str
    cell_lot_id: str
    cells_required: int
    series_count: int
    parallel_count: int
    nominal_energy_wh: float
    welding_profile: str
    is_locked: bool
    version_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BatteryPack(TypedDict):
    id: str
    program_id: str
    serial_number: str
    bom_id: str
    cell_lot_id: str
    pack_energy_wh: float
    assembly_status: str
    logistics_status: str
    soc_percent: float
    soc_band: str
    shipping_classification: str
    welding_heat_dose_j: Optional[float]
    bms_firmware_id: Optional[str]
    dossier_id: Optional[str]
    storage_location_id: Optional[str]
    active_recall_id: Optional[str]
    is_safe_discharged: bool
    disposition: str
    created_at: str
    updated_at: str
    version: int


class WeldingParameterRecord(TypedDict):
    # Immutable event record: only id + created_at, no updated_at / version.
    id: str
    created_at: str
    battery_pack_id: str
    program_id: str
    operator_id: str
    certified_by_id: Optional[str]
    weld_count: int
    current_amps: float
    pulse_ms: int
    electrode_force_n: float
    weld_profile_used: str
    heat_dose_j: float
    is_certified: bool


class BMSFirmware(TypedDict):
    id: str
    program_id: str
    firmware_version: str
    binary_sha256: str
    supports_soc_hysteresis: bool
    approval_record_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FirmwareApproval(TypedDict):
    # Immutable event record: only id + created_at, no updated_at / version.
    id: str
    created_at: str
    bms_firmware_id: str
    program_id: str
    approver_id: str
    decision: str
    rationale: str


class BMSFlashRecord(TypedDict):
    # Immutable event record: only id + created_at, no updated_at / version.
    id: str
    created_at: str
    battery_pack_id: str
    program_id: str
    bms_firmware_id: str
    flashed_by_id: str
    flash_cycle_index: int


class SafetyTestDossier(TypedDict):
    id: str
    battery_pack_id: str
    program_id: str
    dossier_cycle_index: int
    altitude_sim_kpa: Optional[float]
    thermal_cycles: Optional[int]
    vibration_minutes: Optional[int]
    shock_g_peak: Optional[float]
    external_short_circuit_ok: Optional[bool]
    impact_crush_ok: Optional[bool]
    overcharge_ok: Optional[bool]
    forced_discharge_ok: Optional[bool]
    provisional_un_score: Optional[float]
    final_un_score: Optional[float]
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageLocation(TypedDict):
    id: str
    program_id: str
    location_code: str
    fire_zone: str
    capacity_wh: int
    wh_occupied: float
    wh_headroom: float
    accepts_soc_band: List[str]
    created_at: str
    updated_at: str
    version: int


class StoragePlacement(TypedDict):
    id: str
    storage_location_id: str
    battery_pack_id: str
    program_id: str
    staged_at_utc: str
    stored_at_utc: Optional[str]
    released_at_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportShipment(TypedDict):
    id: str
    program_id: str
    carrier_code: str
    un_class_code: str
    declared_weight_kg: float
    total_pack_count: int
    total_wh: float
    carrier_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShipmentPackLink(TypedDict):
    # Immutable event record: only id + created_at, no updated_at / version.
    id: str
    created_at: str
    transport_shipment_id: str
    battery_pack_id: str
    program_id: str
    attached_at_utc: str


class ReturnAuthorization(TypedDict):
    id: str
    program_id: str
    battery_pack_id: str
    reason_code: str
    requested_by_id: str
    approved_by_id: Optional[str]
    target_soc_percent: float
    actual_soc_after_discharge: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallCampaign(TypedDict):
    id: str
    program_id: str
    recall_code: str
    scope_lot_id: Optional[str]
    scope_bom_id: Optional[str]
    scope_serial_prefix: Optional[str]
    packs_in_scope: int
    packs_contained: int
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int
