"""Domain types for the Med-Surg Supply Distribution API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them. Every resource in this API carries the four common properties
described in PRD section 2.4 (`id`, `created_at`, `updated_at`, `version`).
"""

from enum import Enum
from typing import Optional, TypedDict


# ─── Roles (PRD section 2.1) ──────────────────────────────────────────────

class UserRole(str, Enum):
    CONTRACT_ADMIN = "ContractAdmin"
    MATERIALS_MANAGER = "MaterialsManager"
    CLINICIAN = "Clinician"
    DISTRIBUTION_OPERATOR = "DistributionOperator"
    MANUFACTURER_REP = "ManufacturerRep"


# ─── Enumerations carried on entities ─────────────────────────────────────

class GpoMemberClass(str, Enum):
    ACUTE = "ACUTE"
    NON_ACUTE = "NON_ACUTE"
    SURGERY_CENTER = "SURGERY_CENTER"


class RoomType(str, Enum):
    OR_CORE = "OR_CORE"
    ICU = "ICU"
    GENERAL_STORE = "GENERAL_STORE"
    PHARMACY_VAULT = "PHARMACY_VAULT"


class ControlledLicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    NONE = "NONE"


class Uom(str, Enum):
    EA = "EA"
    BX = "BX"
    CS = "CS"


class HandlingClass(str, Enum):
    AMBIENT = "AMBIENT"
    COLD_CHAIN = "COLD_CHAIN"
    CONTROLLED = "CONTROLLED"
    CONTROLLED_COLD = "CONTROLLED_COLD"


class ItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ContractTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class GpoContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class ContractLineActivationState(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class FormularyStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RESTRICTED = "RESTRICTED"
    DELISTED = "DELISTED"


class FormularyDecision(str, Enum):
    APPROVED = "APPROVED"
    RESTRICTED = "RESTRICTED"
    DELISTED = "DELISTED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    EXCURSION_HOLD = "EXCURSION_HOLD"
    QUARANTINED = "QUARANTINED"
    DESTROYED = "DESTROYED"


class ExcursionAction(str, Enum):
    FLAG = "FLAG"
    RELEASE = "RELEASE"
    DESTROY = "DESTROY"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ALLOCATED = "ALLOCATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    CLAIMED = "CLAIMED"
    REBILL_REQUIRED = "REBILL_REQUIRED"
    RECONCILED = "RECONCILED"


class LineStatus(str, Enum):
    OPEN = "OPEN"
    ALLOCATED = "ALLOCATED"
    BACKORDERED = "BACKORDERED"
    SUBSTITUTED = "SUBSTITUTED"
    SHORTED = "SHORTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class SubstitutionStatus(str, Enum):
    PENDING = "PENDING"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ClinicianAction(str, Enum):
    REQUEST_INFO = "REQUEST_INFO"
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class RequesterAction(str, Enum):
    RESPOND = "RESPOND"
    WITHDRAW = "WITHDRAW"


class RecallClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class RecallStatus(str, Enum):
    ISSUED = "ISSUED"
    CASCADED = "CASCADED"
    CLOSED = "CLOSED"


class RecallAction(str, Enum):
    CASCADE = "CASCADE"
    CLOSE = "CLOSE"


class VehicleClass(str, Enum):
    AMBIENT_VAN = "AMBIENT_VAN"
    REEFER_VAN = "REEFER_VAN"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    REBILL_REQUIRED = "REBILL_REQUIRED"
    RECONCILED = "RECONCILED"


class ClaimResponseOutcome(str, Enum):
    ACCEPT = "ACCEPT"
    DISPUTE = "DISPUTE"


class ClaimSettleAction(str, Enum):
    RECONCILE = "RECONCILE"
    RESUBMIT = "RESUBMIT"


class ReplenishmentVariant(str, Enum):
    STANDARD_TOPOFF = "STANDARD_TOPOFF"
    LUM_SPLIT = "LUM_SPLIT"


# ─── Entities ─────────────────────────────────────────────────────────────

class SupplyRoom(TypedDict):
    id: str
    facility_code: str
    room_code: str
    gpo_member_class: str
    room_type: str
    refrigerated: bool
    controlled_secured: bool
    controlled_license_status: str
    window_open_min: int
    window_close_min: int
    credit_limit_cents: int
    open_commitment_cents: int
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict):
    id: str
    sku: str
    description: str
    manufacturer_code: str
    uom: str
    units_per_parent: int
    lum_parent_item_id: Optional[str]
    handling_class: str
    wac_cents: int
    is_lot_tracked: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class GpoContract(TypedDict):
    id: str
    manufacturer_code: str
    contract_code: str
    tier: str
    member_class_scope: str
    committed_volume_units: int
    effective_from: str
    effective_to: str
    supersedes_contract_id: Optional[str]
    status: str
    activated_at: Optional[str]
    chargeback_payable_cents: int
    created_at: str
    updated_at: str
    version: int


class ContractLine(TypedDict):
    id: str
    contract_id: str
    item_id: str
    tier_price_cents: int
    floor_price_cents: int
    chargeback_eligible: bool
    activation_state: str
    created_at: str
    updated_at: str
    version: int


class FormularyItem(TypedDict):
    id: str
    supply_room_id: str
    item_id: str
    facility_item_code: str
    formulary_status: str
    decided_by_user_id: Optional[str]
    par_qty: int
    reorder_point: int
    on_hand_qty: int
    lum_enabled: bool
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    item_id: str
    lot_code: str
    expiry_date: str
    received_quantity: int
    quantity_on_hand: int
    status: str
    excursion_flagged_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReplenishmentOrder(TypedDict):
    id: str
    supply_room_id: str
    route_id: Optional[str]
    stop_arrival_min: Optional[int]
    stop_service_minutes: Optional[int]
    service_date: Optional[str]
    fulfillment_status: str
    settlement_status: str
    order_total_cents: int
    submitted_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    item_id: str
    lot_id: Optional[str]
    pinned_contract_line_id: Optional[str]
    requested_qty: int
    allocated_qty: int
    pinned_unit_price_cents: int
    settled_unit_price_cents: Optional[int]
    extended_price_cents: int
    line_fee_cents: int
    chargeback_eligible: bool
    line_status: str
    created_at: str
    updated_at: str
    version: int


class SubstitutionRequest(TypedDict):
    id: str
    order_line_id: str
    proposed_item_id: str
    requested_by_user_id: str
    clinician_user_id: Optional[str]
    justification: str
    info_request_note: Optional[str]
    response_note: Optional[str]
    rounds_used: int
    status: str
    price_delta_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RecallNotice(TypedDict):
    id: str
    item_id: str
    lot_id: Optional[str]
    recall_class: str
    reason: str
    status: str
    quarantined_lot_count: int
    backordered_line_count: int
    cascaded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict):
    id: str
    route_code: str
    service_date: str
    vehicle_class: str
    planned_order_count: int
    cold_units_loaded: int
    status: str
    dispatched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChargebackClaim(TypedDict):
    id: str
    order_id: str
    contract_id: str
    submitted_by_user_id: str
    reconciled_by_user_id: Optional[str]
    gross_chargeback_cents: int
    admin_fee_pct: float
    admin_fee_cents: int
    net_chargeback_cents: int
    eligible_line_count: int
    status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
