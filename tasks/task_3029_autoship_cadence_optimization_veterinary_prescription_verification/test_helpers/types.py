"""Domain types: entity TypedDicts, status enums and the role enum.

Field names mirror the PRD contract exactly.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    CLINIC_CONTACT = "ClinicContact"
    PHARMACY_TECHNICIAN = "PharmacyTechnician"
    PHARMACY_MANAGER = "PharmacyManager"
    CUSTOMER_SERVICE = "CustomerService"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class PetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PASSED = "PASSED"


class PetLifecycleState(str, Enum):
    ALIVE = "ALIVE"
    PASSED = "PASSED"
    ARCHIVED = "ARCHIVED"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"
    HORSE = "HORSE"
    BIRD = "BIRD"


class VetStatus(str, Enum):
    LISTED = "LISTED"
    VETERINARIAN_VERIFIED = "VETERINARIAN_VERIFIED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"
    BLOCKED = "BLOCKED"


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class MedicationScope(str, Enum):
    OTC = "OTC"
    PRESCRIPTION = "PRESCRIPTION"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    SUSPENDED = "SUSPENDED"
    CANCELED = "CANCELED"
    COMPASSIONATE_CANCELED = "COMPASSIONATE_CANCELED"


class DiscountEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class ItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class VerificationState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"
    EXPIRATION_MARKED = "EXPIRATION_MARKED"


class CadencePromptState(str, Enum):
    UNDER_CONSUMPTION = "UNDER_CONSUMPTION"
    ALIGNED = "ALIGNED"
    OVER_CONSUMPTION = "OVER_CONSUMPTION"


class ProtectionState(str, Enum):
    PROTECTED = "PROTECTED"
    REPRICED = "REPRICED"


class RxStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFICATION_IN_PROGRESS = "VERIFICATION_IN_PROGRESS"
    VERIFIED = "VERIFIED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    EXPIRED = "EXPIRED"


class ScriptSource(str, Enum):
    UPLOADED_SCRIPT = "UPLOADED_SCRIPT"
    WRITTEN_PRESCRIPTION = "WRITTEN_PRESCRIPTION"


class DrugSchedule(str, Enum):
    NONE = "NONE"
    CII = "CII"
    CIII = "CIII"
    CIV = "CIV"
    CV = "CV"


class OrderKind(str, Enum):
    FIRST = "FIRST"
    RECURRING = "RECURRING"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    AWAITING_PET_PASSING_DECISION = "AWAITING_PET_PASSING_DECISION"
    DELIVERED = "DELIVERED"
    CANCELED = "CANCELED"


class CancellationReason(str, Enum):
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    NON_DELIVERY = "NON_DELIVERY"
    PET_PASSED = "PET_PASSED"


class ShipmentStatus(str, Enum):
    PENDING = "PENDING"
    PACKED = "PACKED"
    DISPATCHED = "DISPATCHED"
    AWAITING_PET_PASSING_DECISION = "AWAITING_PET_PASSING_DECISION"
    DELIVERED = "DELIVERED"
    CANCELED = "CANCELED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RefundDestination(str, Enum):
    WALLET = "WALLET"
    ORIGINAL_PAYMENT = "ORIGINAL_PAYMENT"


# Pet is the exception: it carries only id and created_at (no updated_at, no version).
class Pet(TypedDict):
    id: str
    pet_name: str
    species: str
    breed: str
    weight_kg: float
    owner_state: str
    pet_status: str
    passed_at: Optional[str]
    pet_lifecycle_state: str
    compassionate_review_id: Optional[str]
    created_at: str


class Veterinarian(TypedDict):
    id: str
    full_name: str
    clinic_name: str
    clinic_phone: str
    vet_email: str
    license_number: str
    license_state: str
    vet_status: str
    created_at: str
    updated_at: str
    version: int


class PharmacySite(TypedDict):
    id: str
    site_code: str
    site_state: str
    licensed_states: List[str]
    cold_pack_capacity_units: int
    csr_registered: bool
    cold_pack_committed_units: int
    site_status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    product_name: str
    medication_scope: str
    cold_pack_required: bool
    unit_dose_mg_per_kg: float
    pack_size_units: int
    unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class AutoshipPlan(TypedDict):
    id: str
    pet_id: str
    plan_status: str
    autoship_discount_eligibility: str
    next_order_due_date: Optional[str]
    autoship_item_count: int
    cadence_prompt_due_date: Optional[str]
    cadence_prompt_due_days_delta: int
    blackout_start_date: Optional[str]
    blackout_end_date: Optional[str]
    released_refunds_cents: int
    transaction_adjustments_cents: int
    created_at: str
    updated_at: str
    version: int


class AutoshipItem(TypedDict):
    id: str
    autoship_plan_id: str
    product_id: str
    item_status: str
    verification_state: str
    cadence_days: int
    autoship_item_next_due_date: str
    unit_lifecycle_equivalent_days: int
    cadence_prompt_state: str
    default_quantity: int
    unit_price_cents: int
    price_protected_unit_price_cents: Optional[int]
    protection_state: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict):
    id: str
    autoship_item_id: str
    prescriber_id: str
    rx_status: str
    script_source: str
    script_document_id: Optional[str]
    written_prescriber_email_hash: Optional[str]
    drug_schedule: str
    temperature_sensitive: bool
    authorized_qty_total: int
    authorized_qty_remaining: int
    refills_authorized: int
    refills_used: int
    verification_expires_at: Optional[str]
    callback_attempt_count: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    autoship_plan_id: str
    order_kind: str
    order_status: str
    composed_at: str
    bundle_line_count: int
    merchandise_subtotal_cents: int
    autoship_discount_cents: int
    residual_promo_discount_cents: int
    order_total_cents: int
    order_total_components_sum: int
    cold_pack_fee_cents: int
    expedited_shipping_fee_cents: int
    promotion_code: Optional[str]
    cancellation_reason: Optional[str]
    refunded_amount_cents: int
    settlement_net_cents: int
    settlement_payment_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    autoship_item_id: str
    product_id: str
    quantity: int
    line_unit_price_cents: int
    line_autoship_discount_cents: int
    line_item_subtotal_cents: int
    line_requires_clinic_auth: bool
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    origin_site_id: str
    destination_state: str
    shipment_status: str
    cold_pack_required: bool
    cold_pack_units: int
    transit_window_start_date: Optional[str]
    transit_window_end_date: Optional[str]
    tracking_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ColdPackReservation(TypedDict):
    id: str
    shipment_id: str
    site_id: str
    units: int
    reservation_status: str
    created_at: str
    updated_at: str
    version: int


class CompassionateReview(TypedDict):
    id: str
    pet_id: str
    affected_shipment_id: Optional[str]
    review_status: str
    refund_destination: str
    refunded_amount_cents: int
    created_at: str
    updated_at: str
    version: int