"""Domain types for the Landfill Gas & RNG Operations API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────

class UserRole(str, Enum):
    PROJECT_ADMIN = "ProjectAdmin"
    WELLFIELD_TECHNICIAN = "WellfieldTechnician"
    PLANT_OPERATOR = "PlantOperator"
    COMMERCIAL_SCHEDULER = "CommercialScheduler"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    HOST_REPRESENTATIVE = "HostRepresentative"
    OFFTAKER = "Offtaker"


# ─── Status / classification enums ────────────────────

class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    VIOLATION = "VIOLATION"


class RoyaltyVariant(str, Enum):
    GROSS_REVENUE_SHARE = "GROSS_REVENUE_SHARE"
    NETBACK_SHARE = "NETBACK_SHARE"


class WellOperatingState(str, Enum):
    ONLINE = "ONLINE"
    THROTTLED = "THROTTLED"
    ISOLATED = "ISOLATED"
    MAINTENANCE_LOCKOUT = "MAINTENANCE_LOCKOUT"
    DECOMMISSIONED = "DECOMMISSIONED"


class QualityClass(str, Enum):
    NONE = "NONE"
    GOOD = "GOOD"
    WATCH = "WATCH"
    ALARM = "ALARM"


class WorkOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkType(str, Enum):
    WELL_RETUNE = "WELL_RETUNE"
    LATERAL_REPAIR = "LATERAL_REPAIR"
    SUMP_PUMP_SERVICE = "SUMP_PUMP_SERVICE"
    HEADER_DEWATERING = "HEADER_DEWATERING"


class ProcessMode(str, Enum):
    STARTUP = "STARTUP"
    UPGRADING = "UPGRADING"
    FLARING = "FLARING"
    DOWN = "DOWN"
    DECOMMISSIONED = "DECOMMISSIONED"


class SpecStatus(str, Enum):
    ON_SPEC = "ON_SPEC"
    OFF_SPEC = "OFF_SPEC"
    QUARANTINE = "QUARANTINE"


class DowntimeCause(str, Enum):
    PLANNED_MAINTENANCE = "PLANNED_MAINTENANCE"
    COMPRESSOR_TRIP = "COMPRESSOR_TRIP"
    OFF_SPEC_TRIP = "OFF_SPEC_TRIP"
    WELLFIELD_SHORTFALL = "WELLFIELD_SHORTFALL"
    PIPELINE_CURTAILMENT = "PIPELINE_CURTAILMENT"


class DowntimeDisposition(str, Enum):
    FLARED = "FLARED"
    VENTED = "VENTED"
    BYPASS = "BYPASS"


class DowntimeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class NominationStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CURTAILED = "CURTAILED"
    CANCELLED = "CANCELLED"


class InjectionBatchStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ANALYSIS = "PENDING_ANALYSIS"
    ON_SPEC = "ON_SPEC"
    OFF_SPEC = "OFF_SPEC"
    NOMINATED = "NOMINATED"
    INJECTED = "INJECTED"
    DIVERTED_TO_FLARE = "DIVERTED_TO_FLARE"
    VOIDED = "VOIDED"


class SpecFailureReason(str, Enum):
    NONE = "NONE"
    LOW_METHANE = "LOW_METHANE"
    HIGH_OXYGEN = "HIGH_OXYGEN"
    HIGH_CO2 = "HIGH_CO2"


class AttributeProgram(str, Enum):
    RIN_D3 = "RIN_D3"
    LCFS = "LCFS"


class AttributeBasis(str, Enum):
    PROVISIONAL_NOMINATED = "PROVISIONAL_NOMINATED"
    SETTLED_METERED = "SETTLED_METERED"


class AttributeBatchStatus(str, Enum):
    PENDING = "PENDING"
    GENERATED = "GENERATED"
    QA_HOLD = "QA_HOLD"
    SEPARATED = "SEPARATED"
    RETIRED = "RETIRED"
    REVERSED = "REVERSED"


class ReversalReason(str, Enum):
    UPSTREAM_BATCH_DIVERTED = "UPSTREAM_BATCH_DIVERTED"
    BASIS_RESTATEMENT = "BASIS_RESTATEMENT"
    QA_FAILURE = "QA_FAILURE"
    REPORT_REJECTED = "REPORT_REJECTED"


class ReportType(str, Enum):
    NSPS_ANNUAL = "NSPS_ANNUAL"
    QUARTERLY_RIN_QAP = "QUARTERLY_RIN_QAP"
    LCFS_QUARTERLY = "LCFS_QUARTERLY"
    TITLE_V_SEMIANNUAL = "TITLE_V_SEMIANNUAL"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


class RoyaltyStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


# ─── Entity shapes ────────────────────────────────────
# Resources that carry id + created_at + updated_at + version.

class LandfillSite(TypedDict):
    id: str
    name: str
    state_code: str
    host_royalty_pct: float
    royalty_variant: str
    royalty_floor_usd_per_mmbtu: float
    permit_nmoc_limit_lb_per_hr: float
    design_collection_efficiency_pct: float
    collected_flow_scfm: float
    collection_efficiency_pct: float
    energy_produced_mmbtu: float
    energy_injected_mmbtu: float
    energy_flared_mmbtu: float
    energy_vented_mmbtu: float
    rin_generated_total: int
    rin_available_count: int
    rin_retired_count: int
    rin_reversed_count: int
    royalty_payable_usd: float
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class GasWell(TypedDict):
    id: str
    site_id: str
    well_code: str
    target_flow_scfm: float
    operating_state: str
    current_flow_scfm: float
    last_reading_flow_scfm: float
    wellhead_vacuum_inhg: float
    last_quality_class: str
    last_reading_at: Optional[str]
    consecutive_good_readings: int
    lockout_work_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    well_id: str
    work_type: str
    window_start: str
    window_end: str
    lockout_buffer_minutes: int
    status: str
    actual_start_at: Optional[str]
    actual_end_at: Optional[str]
    condensate_gallons_removed: float
    created_at: str
    updated_at: str
    version: int


class ProcessingPlant(TypedDict):
    id: str
    site_id: str
    plant_code: str
    receipt_point_code: str
    receipt_point_mdq_dth_per_day: float
    min_feed_scfm: float
    spec_min_methane_pct: float
    spec_max_oxygen_pct: float
    spec_max_co2_pct: float
    process_mode: str
    spec_status: str
    availability_factor_pct: float
    downtime_minutes_mtd: float
    flare_minutes_mtd: float
    created_at: str
    updated_at: str
    version: int


class DowntimeEvent(TypedDict):
    id: str
    plant_id: str
    start_at: str
    end_at: Optional[str]
    cause: str
    disposition: str
    status: str
    flared_mmbtu: float
    vented_mmbtu: float
    duration_minutes: float
    auto_generated: bool
    created_at: str
    updated_at: str
    version: int


class OfftakeContract(TypedDict):
    id: str
    site_id: str
    counterparty_name: str
    contract_mdq_dth_per_day: float
    price_usd_per_dth: float
    attribute_share_pct: float
    term_start: str
    term_end: str
    status: str
    delivered_dth_mtd: float
    created_at: str
    updated_at: str
    version: int


class PipelineNomination(TypedDict):
    id: str
    contract_id: str
    plant_id: str
    gas_day_start: str
    gas_day_end: str
    nominated_dth: float
    hourly_rate_dth: float
    status: str
    committed_dth: float
    delivered_dth: float
    curtail_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InjectionBatch(TypedDict):
    id: str
    plant_id: str
    nomination_id: Optional[str]
    interval_start: str
    interval_end: str
    hourly_volumes_mscf: List[float]
    methane_pct: float
    oxygen_pct: float
    co2_pct: float
    gross_mmbtu: float
    metered_mmbtu: Optional[float]
    status: str
    spec_failure_reason: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttributeBatch(TypedDict):
    id: str
    injection_batch_id: str
    program: str
    basis: str
    generation_period: str
    energy_basis_mmbtu: float
    eligibility_factor: float
    rin_count: int
    ci_project_gco2e_per_mj: Optional[float]
    lcfs_credits: float
    status: str
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict):
    id: str
    site_id: str
    report_type: str
    period: str
    nmoc_lb_per_hr_reported: float
    exceedance_flag: bool
    status: str
    prepared_by_user_id: str
    reviewed_by_user_id: Optional[str]
    revision_count: int
    return_reason: Optional[str]
    corrective_action_note: Optional[str]
    attached_attribute_batch_count: int
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    site_id: str
    period: str
    allowed_deductions_usd: float
    variant_override: Optional[str]
    variant_applied: str
    billable_mmbtu: float
    gas_revenue_usd: float
    attribute_revenue_usd: float
    gross_revenue_usd: float
    calculated_amount_usd: float
    floor_amount_usd: float
    royalty_amount_usd: float
    status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Append-only event records ────────────────────────
# These two expose only id and created_at: no updated_at, no version.

class WellTuningReading(TypedDict):
    id: str
    well_id: str
    taken_at: str
    methane_pct: float
    oxygen_pct: float
    nitrogen_pct: float
    temperature_f: float
    flow_scfm: float
    vacuum_inhg: float
    air_intrusion_index: float
    quality_class: str
    resulting_well_state: str
    recorded_by_user_id: str
    created_at: str


class CondensateHaul(TypedDict):
    id: str
    work_order_id: str
    gallons: float
    disposal_manifest_no: str
    hauled_at: str
    is_hazardous: bool
    created_at: str
