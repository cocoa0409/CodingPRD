"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource carries the standard
four system-managed fields (id, created_at, updated_at, version) per the PRD
common-resource-properties section, except WastageRecord, which is an
append-only event log entry carrying only id and created_at.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD user/role section)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ORDERING_PHYSICIAN = "OrderingPhysician"
    BLOOD_BANK_TECHNOLOGIST = "BloodBankTechnologist"
    BLOOD_BANK_SUPERVISOR = "BloodBankSupervisor"
    SUPPLIER_COORDINATOR = "SupplierCoordinator"
    QUALITY_OFFICER = "QualityOfficer"


# ---------------------------------------------------------------------------
# Vocabulary enums (PRD blood-components/typing vocabulary section)
# ---------------------------------------------------------------------------

class ProductType(str, Enum):
    RBC = "RBC"
    WHOLE_BLOOD = "WHOLE_BLOOD"
    PLT_APHERESIS = "PLT_APHERESIS"
    PLT_POOL = "PLT_POOL"
    FFP = "FFP"
    CRYO = "CRYO"


class AboType(str, Enum):
    O = "O"
    A = "A"
    B = "B"
    AB = "AB"
    UNKNOWN = "UNKNOWN"


class RhType(str, Enum):
    POS = "POS"
    NEG = "NEG"
    UNKNOWN = "UNKNOWN"


class AntibodyStatus(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    UNKNOWN = "UNKNOWN"


class AntibodyScreen(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class SpecialRequirement(str, Enum):
    IRRADIATED = "IRRADIATED"
    CMV_NEGATIVE = "CMV_NEGATIVE"
    WASHED = "WASHED"


# ---------------------------------------------------------------------------
# Status enums (one per state machine in the PRD narratives)
# ---------------------------------------------------------------------------

class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SupplierOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RECEIVING = "RECEIVING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BloodUnitStatus(str, Enum):
    QUARANTINED = "QUARANTINED"
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ISSUED = "ISSUED"
    TRANSFUSED = "TRANSFUSED"
    EXPIRED = "EXPIRED"
    DISCARDED = "DISCARDED"
    REJECTED = "REJECTED"
    RETURNED_TO_SUPPLIER = "RETURNED_TO_SUPPLIER"
    QUARANTINED_HOLD = "QUARANTINED_HOLD"


class HoldReason(str, Enum):
    REACTION_PRECAUTION = "REACTION_PRECAUTION"
    RECALL = "RECALL"
    SUPPLIER_SUSPENSION = "SUPPLIER_SUSPENSION"


class TypeAndScreenStatus(str, Enum):
    COLLECTED = "COLLECTED"
    RESULTED = "RESULTED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class TransfusionOrderStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    AWAITING_CROSSMATCH = "AWAITING_CROSSMATCH"
    READY = "READY"
    PARTIALLY_ISSUED = "PARTIALLY_ISSUED"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class Urgency(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    EMERGENCY = "EMERGENCY"


class TypeRestriction(str, Enum):
    NONE = "NONE"
    O_ONLY = "O_ONLY"
    AB_ONLY = "AB_ONLY"


class CrossmatchStatus(str, Enum):
    PENDING = "PENDING"
    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    CONSUMED = "CONSUMED"


class CrossmatchMethod(str, Enum):
    ELECTRONIC = "ELECTRONIC"
    SEROLOGIC_AHG = "SEROLOGIC_AHG"


class CrossmatchResult(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"


class IssueRecordStatus(str, Enum):
    ISSUED = "ISSUED"
    TRANSFUSION_STARTED = "TRANSFUSION_STARTED"
    TRANSFUSED = "TRANSFUSED"
    RETURNED = "RETURNED"
    TRANSFUSION_STOPPED = "TRANSFUSION_STOPPED"


class ReturnDisposition(str, Enum):
    RESTOCKED = "RESTOCKED"
    DISCARDED_OVER_30MIN = "DISCARDED_OVER_30MIN"
    DISCARDED_COMPROMISED = "DISCARDED_COMPROMISED"


class MtpStatus(str, Enum):
    ACTIVATED = "ACTIVATED"
    STANDING_DOWN = "STANDING_DOWN"
    DEACTIVATED = "DEACTIVATED"


class ReactionType(str, Enum):
    FEBRILE_NON_HEMOLYTIC = "FEBRILE_NON_HEMOLYTIC"
    ALLERGIC_MILD = "ALLERGIC_MILD"
    ALLERGIC_ANAPHYLAXIS = "ALLERGIC_ANAPHYLAXIS"
    HEMOLYTIC_ACUTE = "HEMOLYTIC_ACUTE"
    HEMOLYTIC_DELAYED = "HEMOLYTIC_DELAYED"
    TRALI = "TRALI"
    TACO = "TACO"
    SEPTIC = "SEPTIC"
    OTHER = "OTHER"


class Severity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    LIFE_THREATENING = "LIFE_THREATENING"


class ReactionStatus(str, Enum):
    REPORTED = "REPORTED"
    INVESTIGATING = "INVESTIGATING"
    CONFIRMED = "CONFIRMED"
    RULED_OUT = "RULED_OUT"
    CLOSED = "CLOSED"


class ReactionConclusion(str, Enum):
    CONFIRMED = "CONFIRMED"
    RULED_OUT = "RULED_OUT"


class RecallScopeType(str, Enum):
    DONOR = "DONOR"
    LOT = "LOT"
    UNIT = "UNIT"


class RecallDisposition(str, Enum):
    DESTRUCTION = "DESTRUCTION"
    MARKET_WITHDRAWAL = "MARKET_WITHDRAWAL"


class RecallStatus(str, Enum):
    OPEN = "OPEN"
    UNITS_IDENTIFIED = "UNITS_IDENTIFIED"
    QUARANTINE_COMPLETE = "QUARANTINE_COMPLETE"
    NOTIFICATION_COMPLETE = "NOTIFICATION_COMPLETE"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class WastageReason(str, Enum):
    EXPIRED = "EXPIRED"
    RETURNED_OVER_30MIN = "RETURNED_OVER_30MIN"
    RETURNED_COMPROMISED = "RETURNED_COMPROMISED"
    PARTIAL_TRANSFUSION = "PARTIAL_TRANSFUSION"
    REACTION_INVESTIGATION = "REACTION_INVESTIGATION"
    RECALL_DESTRUCTION = "RECALL_DESTRUCTION"
    MANUAL = "MANUAL"


class Posture(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    SHORTAGE = "SHORTAGE"
    CRITICAL = "CRITICAL"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CoolerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHECKED_OUT = "CHECKED_OUT"
    RESTOCKING = "RESTOCKING"


class CheckoutStatus(str, Enum):
    OPEN = "OPEN"
    RETURNED = "RETURNED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Patient(TypedDict, total=False):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    special_requirements: List[str]
    current_abo_type: str
    current_rh_type: str
    antibody_status: str
    identified_antibodies: List[str]
    abo_confirmed: bool
    has_active_type_and_screen: bool
    active_mtp: bool
    total_units_transfused: int
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    name: str
    license_number: str
    default_lead_time_hours: int
    status: str
    suspended_at: Optional[str]
    suspend_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplierOrderLine(TypedDict):
    product_type: str
    abo_type: str
    rh_type: str
    quantity: int


class ReceivedSummaryLine(TypedDict, total=False):
    product_type: str
    abo_type: str
    rh_type: str
    received_qty: int


class SupplierOrder(TypedDict, total=False):
    id: str
    supplier_id: str
    is_emergency: bool
    lines: List[SupplierOrderLine]
    expected_delivery_at: Optional[str]
    status: str
    estimated_cost_cents: int
    received_summary: List[ReceivedSummaryLine]
    total_units_received: int
    backordered: bool
    created_at: str
    updated_at: str
    version: int


class BloodUnit(TypedDict, total=False):
    id: str
    unit_number: str
    supplier_order_id: str
    supplier_id: str
    donor_id: str
    lot_number: str
    product_type: str
    abo_type: str
    rh_type: str
    volume_ml: int
    collected_at: str
    thawed_at: Optional[str]
    pooled_at: Optional[str]
    expires_at: str
    antigen_negative: List[str]
    irradiated: bool
    cmv_negative: bool
    washed: bool
    derived_from_unit_id: Optional[str]
    status: str
    hold_origin_state: Optional[str]
    hold_reason: Optional[str]
    intake_reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TypeAndScreen(TypedDict, total=False):
    id: str
    patient_id: str
    specimen_collected_at: str
    expires_at: str
    abo_result: str
    rh_result: str
    antibody_screen: str
    antibody_identifications: List[str]
    resulted_at: Optional[str]
    resulted_by_user_id: Optional[str]
    validated_at: Optional[str]
    validated_by_user_id: Optional[str]
    status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransfusionOrder(TypedDict, total=False):
    id: str
    patient_id: str
    ordering_physician_id: str
    product_type: str
    units_requested: int
    urgency: str
    indication_code: str
    requires_crossmatch: bool
    type_restriction: str
    demand_bucket: str
    special_requirements_snapshot: List[str]
    units_crossmatched: int
    units_issued_net: int
    units_transfused: int
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    status: str
    rejection_reason: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Crossmatch(TypedDict, total=False):
    id: str
    order_id: str
    unit_id: Optional[str]
    patient_id: str
    method: str
    status: str
    auto_selected: bool
    resulted_at: Optional[str]
    resulted_by_user_id: Optional[str]
    reserved_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MtpActivation(TypedDict, total=False):
    id: str
    patient_id: str
    activated_by_physician_id: str
    activation_reason: str
    status: str
    packs_dispatched: int
    units_issued_total: int
    units_wasted_total: int
    activated_at: str
    stood_down_at: Optional[str]
    deactivated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IssueRecord(TypedDict, total=False):
    id: str
    order_id: str
    unit_id: Optional[str]
    patient_id: str
    mtp_activation_id: Optional[str]
    is_emergency_release: bool
    emergency_justification: Optional[str]
    verified_by_user_id: str
    issued_by_user_id: str
    issued_at: str
    transfusion_started_at: Optional[str]
    completed_at: Optional[str]
    returned_at: Optional[str]
    return_seal_intact: Optional[bool]
    return_temperature_excursion: Optional[bool]
    return_disposition: Optional[str]
    physician_acknowledged_at: Optional[str]
    ack_overdue: bool
    lookback_notified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TransfusionReaction(TypedDict, total=False):
    id: str
    issue_record_id: str
    patient_id: str
    unit_id: str
    reaction_type: str
    severity: str
    symptoms: Optional[str]
    reported_by_user_id: str
    investigator_user_id: Optional[str]
    clerical_check_passed: Optional[bool]
    dat_result: Optional[str]
    hemolysis_present: Optional[bool]
    workup_recorded_at: Optional[str]
    conclusion: Optional[str]
    final_classification: Optional[str]
    linked_recall_case_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallCase(TypedDict, total=False):
    id: str
    scope_type: str
    donor_id: Optional[str]
    lot_number: Optional[str]
    unit_id: Optional[str]
    implicated_since: Optional[str]
    reason: str
    disposition: str
    auto_created: bool
    implicated_unit_ids: List[str]
    implicated_unit_count: int
    quarantined_count: int
    transfused_issue_count: int
    notifications_sent_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WastageRecord(TypedDict, total=False):
    # Append-only event log entry: carries ONLY id + created_at among the
    # system-managed fields — no updated_at, no version (PRD common-resource
    # properties section).
    id: str
    created_at: str
    unit_id: str
    product_type: str
    abo_type: str
    rh_type: str
    reason: str
    quantity_units: int
    recorded_by_user_id: str
    note: Optional[str]


class ParLevelPolicy(TypedDict, total=False):
    id: str
    product_type: str
    abo_type: str
    rh_type: str
    watch_threshold: int
    shortage_threshold: int
    critical_threshold: int
    min_shelf_life_hours: int
    status: str
    current_posture: str
    usable_units: int
    inbound_units_24h: int
    excessive_wastage: bool
    created_at: str
    updated_at: str
    version: int


class TransportCooler(TypedDict, total=False):
    id: str
    cooler_tag: str
    status: str
    restock_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoolerCheckout(TypedDict, total=False):
    id: str
    cooler_id: str
    planned_start: str
    planned_end: str
    checked_out_by_user_id: str
    actual_returned_at: Optional[str]
    status: str
    overdue: bool
    created_at: str
    updated_at: str
    version: int
