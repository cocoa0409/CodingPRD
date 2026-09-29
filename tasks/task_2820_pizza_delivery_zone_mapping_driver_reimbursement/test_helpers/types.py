"""Domain types for the Store Operations API: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    STORE_MANAGER = "StoreManager"
    DISPATCHER = "Dispatcher"
    DRIVER = "Driver"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CUSTOMER_CARE_AGENT = "CustomerCareAgent"


class ServicePosture(str, Enum):
    OPEN = "OPEN"
    CARRYOUT_ONLY = "CARRYOUT_ONLY"
    CLOSED = "CLOSED"


class ZoneVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ZoneState(str, Enum):
    IN_ZONE = "IN_ZONE"
    EDGE = "EDGE"
    OUT_OF_ZONE = "OUT_OF_ZONE"


class DisputeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class DisputeAction(str, Enum):
    START_REVIEW = "START_REVIEW"
    REQUEST_INFO = "REQUEST_INFO"
    GRANT = "GRANT"
    DENY = "DENY"
    WITHDRAW = "WITHDRAW"


class QualificationStatus(str, Enum):
    APPLICANT = "APPLICANT"
    PENDING_CHECKS = "PENDING_CHECKS"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    DISQUALIFIED = "DISQUALIFIED"


class QualificationDecision(str, Enum):
    QUALIFY = "QUALIFY"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    DISQUALIFY = "DISQUALIFY"


class VehicleClass(str, Enum):
    CAR = "CAR"
    SUV = "SUV"
    SCOOTER = "SCOOTER"


class InsuranceStatus(str, Enum):
    NONE = "NONE"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class InsuranceVerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class MvrResult(str, Enum):
    CLEAR = "CLEAR"
    MINOR_VIOLATIONS = "MINOR_VIOLATIONS"
    FAILED = "FAILED"


class CashPosture(str, Enum):
    CLEAR = "CLEAR"
    DROP_REQUIRED = "DROP_REQUIRED"


class CostModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SafeDropStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class FulfillmentStatus(str, Enum):
    PLACED = "PLACED"
    ZONE_HELD = "ZONE_HELD"
    ZONE_CLEARED = "ZONE_CLEARED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    ASSIGNED = "ASSIGNED"
    EN_ROUTE = "EN_ROUTE"
    DELIVERED = "DELIVERED"
    REMAKE_QUEUED = "REMAKE_QUEUED"
    CLOSED = "CLOSED"
    DECLINED_OUT_OF_AREA = "DECLINED_OUT_OF_AREA"
    CARRYOUT_REDIRECTED = "CARRYOUT_REDIRECTED"


class SettlementStatus(str, Enum):
    UNDISCLOSED = "UNDISCLOSED"
    DISCLOSED = "DISCLOSED"
    CHARGED = "CHARGED"
    ADJUSTED = "ADJUSTED"
    CLOSED_SETTLED = "CLOSED_SETTLED"
    VOIDED = "VOIDED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"


class FeeTier(str, Enum):
    BASE = "BASE"
    MID = "MID"
    FAR = "FAR"


class DeclinedReason(str, Enum):
    OUT_OF_AREA = "OUT_OF_AREA"
    DRIVE_TIME_EXCEEDED = "DRIVE_TIME_EXCEEDED"
    STORE_CARRYOUT_ONLY = "STORE_CARRYOUT_ONLY"


class ZoneDecisionAction(str, Enum):
    CLEAR = "CLEAR"
    HOLD = "HOLD"
    DECLINE = "DECLINE"
    REDIRECT_CARRYOUT = "REDIRECT_CARRYOUT"


class ProductionAction(str, Enum):
    START = "START"
    READY = "READY"


class DispatchStatus(str, Enum):
    DRAFT = "DRAFT"
    STACKED = "STACKED"
    LOCKED = "LOCKED"
    EN_ROUTE = "EN_ROUTE"
    RETURNED = "RETURNED"
    SETTLED = "SETTLED"
    RECALLED = "RECALLED"
    CANCELLED = "CANCELLED"


class DispatchStopStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    RELEASED = "RELEASED"
    REMADE = "REMADE"


class ReimbursementLineType(str, Enum):
    PROVISIONAL_STOP = "PROVISIONAL_STOP"
    ACTUAL_STOP = "ACTUAL_STOP"
    CLAWBACK = "CLAWBACK"


class ReimbursementBasis(str, Enum):
    ESTIMATED = "ESTIMATED"
    ACTUAL = "ACTUAL"
    NONE = "NONE"


class ReimbursementLineStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACCRUED = "ACCRUED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    REMEDY_PROPOSED = "REMEDY_PROPOSED"
    REMEDY_ISSUED = "REMEDY_ISSUED"
    DISMISSED = "DISMISSED"


class ComplaintCategory(str, Enum):
    LATE = "LATE"
    FEE_DISCLOSURE = "FEE_DISCLOSURE"
    QUALITY = "QUALITY"
    DRIVER_CONDUCT = "DRIVER_CONDUCT"


class RemedyBasis(str, Enum):
    LATE_TIER = "LATE_TIER"
    FEE_REFUND = "FEE_REFUND"
    QUALITY_HALF = "QUALITY_HALF"
    CONDUCT_ZERO = "CONDUCT_ZERO"


class ComplaintResolveAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    DISMISS = "DISMISS"


# --- Entity shapes ------------------------------------------------------------
# Every resource carries id + created_at. All resources except the motor-vehicle
# record pull additionally carry updated_at and version; the pull is append-only
# and carries id and created_at only.


class Store(TypedDict):
    id: str
    store_number: str
    name: str
    latitude_micro: int
    longitude_micro: int
    promise_minutes: int
    delivery_fee_cents: int
    cash_limit_cents: int
    hot_bag_count: int
    max_stacked_stops: int
    handoff_minutes_per_stop: int
    dispatch_reset_buffer_minutes: int
    service_posture: str
    cash_collected_total_cents: int
    safe_deposit_total_cents: int
    unassigned_order_count: int
    active_zone_version_number: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ZoneVersion(TypedDict):
    id: str
    store_id: str
    version_number: int
    status: str
    polygon: List[Dict[str, int]]
    effective_from: str
    effective_to: str
    max_drive_time_minutes: int
    base_drive_minutes: int
    minutes_per_mile: int
    peak_surcharge_minutes: int
    barrier_surcharge_minutes: int
    supersedes_zone_version_id: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceAddress(TypedDict):
    id: str
    store_id: str
    line1: str
    latitude_micro: int
    longitude_micro: int
    crosses_barrier: bool
    grid_miles: float
    drive_time_estimate_minutes: int
    zone_state: str
    effective_zone_state: str
    override_state: Optional[str]
    override_until: Optional[str]
    evaluated_zone_version_number: int
    evaluated_at: str
    created_at: str
    updated_at: str
    version: int


class AddressDispute(TypedDict):
    id: str
    service_address_id: str
    claimed_state: str
    evidence_note: str
    status: str
    review_round_count: int
    resolution: Optional[str]
    decided_at: Optional[str]
    reviewer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    store_id: str
    full_name: str
    license_number: str
    vehicle_class: str
    qualification_status: str
    insurance_status: str
    mvr_points_latest: int
    cash_on_hand_cents: int
    cash_posture: str
    reimbursement_accrued_cents: int
    qualified_by_user_id: Optional[str]
    disqualified_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MvrCheck(TypedDict):
    """Append-only immutable audit record: id and created_at only, no version."""

    id: str
    driver_id: str
    result: str
    violation_points: int
    checked_on: str
    recorded_by_user_id: str
    created_at: str


class InsuranceVerification(TypedDict):
    id: str
    driver_id: str
    policy_number: str
    coverage_from: str
    coverage_to: str
    liability_limit_cents: int
    status: str
    rejected_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VehicleCostModel(TypedDict):
    id: str
    store_id: str
    vehicle_class: str
    per_delivery_cents: int
    tier1_cap_miles: float
    tier1_per_mile_cents: int
    tier2_per_mile_cents: int
    min_reimbursement_per_stop_cents: int
    effective_from: str
    status: str
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafeDrop(TypedDict):
    id: str
    driver_id: str
    amount_cents: int
    envelope_number: str
    status: str
    voided_reason: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    store_id: str
    service_address_id: str
    customer_name: str
    customer_phone: str
    food_subtotal_cents: int
    tip_cents: int
    payment_method: str
    fulfillment_status: str
    settlement_status: str
    fee_tier: str
    base_delivery_fee_cents: int
    fee_waiver_pct: int
    delivery_fee_cents: int
    total_charge_cents: int
    promise_minutes_snapshot: int
    placed_at: str
    ready_at: Optional[str]
    door_arrival_at: Optional[str]
    zone_held_at: Optional[str]
    zone_hold_minutes: int
    remake_hold_minutes: int
    order_to_door_gross_minutes: Optional[int]
    order_to_door_net_minutes: Optional[int]
    declined_reason: Optional[str]
    disclosed_fee_cents: Optional[int]
    disclosed_tip_cents: Optional[int]
    driver_tip_notice_given: Optional[bool]
    fee_disclosure_accurate: Optional[bool]
    fee_disclosed_at: Optional[str]
    cash_collected_cents: int
    remake_count: int
    remake_credit_cents: int
    remedy_issued_cents: int
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict):
    id: str
    driver_id: str
    planned_depart_at: str
    status: str
    stop_count: int
    committed_hot_bag_slots: int
    route_minutes: Optional[int]
    expected_return_at: Optional[str]
    resolved_cost_model_id: Optional[str]
    estimated_reimbursement_cents: Optional[int]
    actual_reimbursement_cents: Optional[int]
    reimbursement_variance_cents: Optional[int]
    departed_at: Optional[str]
    returned_at: Optional[str]
    recalled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispatchStop(TypedDict):
    id: str
    dispatch_id: str
    order_id: str
    sequence: int
    status: str
    hot_bag_slots: int
    planned_miles: float
    planned_drive_minutes: int
    actual_miles: Optional[float]
    cash_collected_cents: int
    arrived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReimbursementLine(TypedDict):
    id: str
    dispatch_id: str
    driver_id: str
    order_id: Optional[str]
    line_type: str
    basis: str
    amount_cents: int
    sequence_snapshot: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    order_id: str
    category: str
    description: str
    status: str
    proposed_remedy_cents: Optional[int]
    remedy_basis: Optional[str]
    driver_chargeable: bool
    clawback_cents: int
    logged_by_user_id: str
    resolved_by_user_id: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CashReconciliation(TypedDict):
    store_id: str
    cash_collected_total_cents: int
    safe_deposit_total_cents: int
    driver_cash_on_hand_total_cents: int
    reconciled: bool
