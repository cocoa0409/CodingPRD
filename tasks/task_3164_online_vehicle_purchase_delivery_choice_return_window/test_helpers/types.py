"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class VehicleStatus(str, Enum):
    INTAKE = "INTAKE"
    IN_RECON = "IN_RECON"
    LISTED = "LISTED"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    RETURN_INBOUND = "RETURN_INBOUND"
    REMOVED = "REMOVED"


class AnnotationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETRACTED = "RETRACTED"


class PrequalStatus(str, Enum):
    PREQUALIFIED = "PREQUALIFIED"
    LOCKED = "LOCKED"
    EXPIRED = "EXPIRED"


class PricingMode(str, Enum):
    STANDARD = "STANDARD"
    CONSERVATIVE = "CONSERVATIVE"


class TradeInStatus(str, Enum):
    OFFERED = "OFFERED"
    INSPECTED = "INSPECTED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    STRUCTURED = "STRUCTURED"
    APPOINTMENT_SET = "APPOINTMENT_SET"
    COMPLETED = "COMPLETED"
    RETURN_INITIATED = "RETURN_INITIATED"
    RETURN_COMPLETED = "RETURN_COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    FINANCED = "FINANCED"
    PAID = "PAID"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"


class DeliveryStatus(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"


class TitleRegStatus(str, Enum):
    PENDING = "PENDING"
    TEMP_TAG_ISSUED = "TEMP_TAG_ISSUED"
    FILED = "FILED"
    REGISTERED = "REGISTERED"
    BLOCKED = "BLOCKED"


class ProcessingMode(str, Enum):
    IN_STATE = "IN_STATE"
    OUT_OF_STATE = "OUT_OF_STATE"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ReturnTransitStatus(str, Enum):
    PICKUP_SCHEDULED = "PICKUP_SCHEDULED"
    PICKED_UP = "PICKED_UP"
    ARRIVED_AT_CENTER = "ARRIVED_AT_CENTER"
    INTAKE_DONE = "INTAKE_DONE"


class DefectClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"
    REPAIR_COMPLETE = "REPAIR_COMPLETE"


class DisclosureFlag(str, Enum):
    DISCLOSED = "DISCLOSED"
    UNDISCLOSED = "UNDISCLOSED"


class RepairAuthStatus(str, Enum):
    ISSUED = "ISSUED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class ReconIntakeStatus(str, Enum):
    PENDING_ARRIVAL = "PENDING_ARRIVAL"
    RECEIVED = "RECEIVED"
    IN_WORK = "IN_WORK"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class FulfillmentChoice(str, Enum):
    HOME_DELIVERY = "HOME_DELIVERY"
    VENDING_MACHINE = "VENDING_MACHINE"


class CreditBand(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    PLATFORM_ADMIN = "PlatformAdmin"
    CUSTOMER_ADVOCATE = "CustomerAdvocate"
    RECON_OPERATOR = "ReconOperator"
    REGISTRATION_CLERK = "RegistrationClerk"
    WARRANTY_ADMIN = "WarrantyAdmin"


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    state_code: str
    default_fulfillment_choice: str
    created_at: str
    updated_at: str
    version: int


class ReconditioningCenter(TypedDict, total=False):
    id: str
    name: str
    market_code: str
    daily_capacity: int
    slot_count: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    vin: str
    make: str
    model: str
    year: int
    mileage: int
    base_price_cents: int
    market_code: str
    center_id: Optional[str]
    status: str
    listed_price_cents: int
    annotation_count: int
    created_at: str
    updated_at: str
    version: int


class ImperfectionAnnotation(TypedDict, total=False):
    id: str
    vehicle_id: str
    area: str
    severity: str
    deduction_cents: int
    image_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingPrequalification(TypedDict, total=False):
    id: str
    customer_id: str
    annual_income_cents: int
    credit_band: str
    max_amount_cents: int
    apr_bps: int
    monthly_payment_cents: int
    pricing_mode: str
    status: str
    expires_at: str
    locked_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradeInOffer(TypedDict, total=False):
    id: str
    customer_id: str
    vin: str
    questionnaire: dict
    initial_offer_cents: int
    adjusted_offer_cents: Optional[int]
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    customer_id: str
    vehicle_id: str
    fulfillment_choice: str
    state_code: str
    trade_in_offer_id: Optional[str]
    financing_id: Optional[str]
    status: str
    payment_status: str
    delivery_status: str
    down_payment_cents: int
    amount_financed_cents: int
    total_due_cents: int
    odometer_at_delivery: Optional[int]
    delivered_at: Optional[str]
    return_deadline: Optional[str]
    return_requested_mileage: Optional[int]
    return_reason_code: Optional[str]
    return_inspection_result: Optional[str]
    refund_amount_cents: Optional[int]
    refund_processed_at: Optional[str]
    deposit_cents: int
    created_at: str
    updated_at: str
    version: int


class TitleRegistration(TypedDict, total=False):
    id: str
    order_id: str
    vehicle_id: str
    state_code: str
    status: str
    temp_tag_number: Optional[str]
    temp_tag_expires_at: Optional[str]
    filed_at: Optional[str]
    registration_due_at: Optional[str]
    missed_commitment: bool
    processing_mode: str
    created_at: str
    updated_at: str
    version: int


class DeliveryAppointment(TypedDict, total=False):
    id: str
    order_id: str
    kind: str
    market_code: str
    address_region: Optional[str]
    vending_site_code: Optional[str]
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnTransit(TypedDict, total=False):
    id: str
    order_id: str
    vehicle_id: str
    market_code: str
    start_at: str
    end_at: str
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DefectClaim(TypedDict, total=False):
    id: str
    order_id: str
    vehicle_id: str
    defect_description: str
    defect_area: str
    status: str
    disclosure_flag: str
    review_note: Optional[str]
    authorized_estimate_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RepairAuthorization(TypedDict, total=False):
    id: str
    claim_id: str
    estimate_cents: int
    covered_amount_cents: int
    deductible_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReconIntake(TypedDict, total=False):
    id: str
    vehicle_id: str
    center_id: str
    arrived_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
