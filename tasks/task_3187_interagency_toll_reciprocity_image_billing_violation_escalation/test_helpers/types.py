"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class VehicleClass(str, Enum):
    CLASS_2 = "CLASS_2"
    CLASS_5 = "CLASS_5"
    CLASS_7 = "CLASS_7"


class UserRole(str, Enum):
    SETTLEMENT_OFFICER = "SettlementOfficer"
    AGENCY_OPERATIONS = "AgencyOperations"
    ACCOUNT_HOLDER = "AccountHolder"
    VIOLATIONS_OFFICER = "ViolationsOfficer"
    PLATE_LOOKUP_AGENT = "PlateLookupAgent"


class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RateScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DiscountPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SuspendedReason(str, Enum):
    REPLENISHMENT_FAILED = "REPLENISHMENT_FAILED"
    VIOLATION_ESCALATION = "VIOLATION_ESCALATION"


class TransponderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REPORTED_LOST = "REPORTED_LOST"
    RETIRED = "RETIRED"


class TollTransactionStatus(str, Enum):
    POSTED = "POSTED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"
    DISPUTED = "DISPUTED"


class DetectionMethod(str, Enum):
    TRANSPONDER = "TRANSPONDER"
    IMAGE = "IMAGE"


class ImageBillStatus(str, Enum):
    PENDING_LOOKUP = "PENDING_LOOKUP"
    BILLED = "BILLED"
    REBILLED = "REBILLED"
    VOIDED = "VOIDED"
    ESCALATED = "ESCALATED"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    NOTICED = "NOTICED"
    ESCALATED = "ESCALATED"
    HOLD_REFERRED = "HOLD_REFERRED"
    PAID = "PAID"
    DISMISSED = "DISMISSED"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHOLD = "UPHOLD"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class DisputeType(str, Enum):
    VEHICLE_CLASSIFICATION = "VEHICLE_CLASSIFICATION"
    MISREAD_PLATE = "MISREAD_PLATE"
    RENTAL_VEHICLE = "RENTAL_VEHICLE"


class SettlementFileStatus(str, Enum):
    GENERATED = "GENERATED"
    TRANSMITTED = "TRANSMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RECONCILED = "RECONCILED"
    DISPUTED_SETTLEMENT = "DISPUTED_SETTLEMENT"


class PlateDataAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class Agency(TypedDict):
    id: str
    agency_code: str
    name: str
    home_state: str
    reciprocity_fee_bps: int
    settlement_currency: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict):
    id: str
    agency_id: str
    plaza_code: str
    vehicle_class: str
    base_rate_cents: int
    axle_multiplier: float
    peak_multiplier: float
    image_fee_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DiscountPlan(TypedDict):
    id: str
    agency_id: str
    plan_code: str
    discount_pct: float
    daily_discount_cap_cents: int
    applies_to_agency_codes: List[str]
    min_trips_per_month: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    home_agency_id: str
    holder_name: str
    holder_email: str
    discount_plan_id: str
    balance_cents: int
    low_balance_threshold_cents: int
    replenishment_amount_cents: int
    replenishment_fail_count: int
    discount_used_today_cents: int
    trips_this_month: int
    status: str
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Transponder(TypedDict):
    id: str
    account_id: str
    tag_number: str
    vehicle_class: str
    plate_number: str
    plate_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TollTransaction(TypedDict):
    # Append-only ledger row: id + created_at only (PRD §2.4); no updated_at/version.
    id: str
    created_at: str
    account_id: str
    transponder_id: Optional[str]
    away_agency_id: str
    rate_schedule_id: str
    plaza_code: str
    trip_timestamp: str
    is_peak: bool
    billed_vehicle_class: str
    detection_method: str
    gross_amount_cents: int
    discount_amount_cents: int
    charged_amount_cents: int
    status: str
    settlement_file_id: Optional[str]
    idempotency_key: str


class ImageBill(TypedDict):
    id: str
    account_id: Optional[str]
    plate_number: str
    plate_state: str
    toll_transaction_id: str
    lookup_agency_id: Optional[str]
    billed_amount_cents: int
    misread_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    account_id: Optional[str]
    plate_number: str
    plate_state: str
    toll_transaction_id: str
    image_bill_id: Optional[str]
    toll_amount_cents: int
    notice_count: int
    admin_fees_cents: int
    total_outstanding_cents: int
    first_notice_day: Optional[int]
    current_notice_day: Optional[int]
    registration_hold_referred: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    account_id: Optional[str]
    dispute_type: str
    toll_transaction_id: Optional[str]
    image_bill_id: Optional[str]
    violation_id: Optional[str]
    claimed_vehicle_class: Optional[str]
    claimed_plate_number: Optional[str]
    rental_agreement_ref: Optional[str]
    filed_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementFile(TypedDict):
    id: str
    from_agency_id: str
    to_agency_id: str
    settlement_day: int
    line_count: int
    gross_amount_cents: int
    fee_amount_cents: int
    net_amount_cents: int
    exception_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlateDataAgreement(TypedDict):
    id: str
    requesting_agency_id: str
    providing_agency_id: str
    effective_from: str
    effective_to: str
    covers_states: List[str]
    per_lookup_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
