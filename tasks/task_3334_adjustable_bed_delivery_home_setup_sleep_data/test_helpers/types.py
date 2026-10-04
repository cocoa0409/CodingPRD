"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class StoreStatus(str, Enum):
    pass  # Store has no status machine


class FitAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    FULFILLING = "FULFILLING"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    FINANCED = "FINANCED"
    REFUNDED = "REFUNDED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    WAITLISTED = "WAITLISTED"
    VERIFIED = "VERIFIED"
    FAILED_SETUP = "FAILED_SETUP"
    CANCELLED = "CANCELLED"


class PairingStatus(str, Enum):
    UNPAIRED = "UNPAIRED"
    PAIRED = "PAIRED"


class Connectivity(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class SleepNightStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class TrialReturnStatus(str, Enum):
    INITIATED = "INITIATED"
    REFUNDED = "REFUNDED"
    REJECTED = "REJECTED"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"


class FinancingPlanStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    PAID_OFF = "PAID_OFF"
    SETTLED_EARLY = "SETTLED_EARLY"
    DEFAULTED = "DEFAULTED"
    VOIDED = "VOIDED"


class SubscriptionTier(str, Enum):
    FREE = "FREE"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PLATFORM_ADMIN = "PlatformAdmin"
    SALES_ASSOCIATE = "SalesAssociate"
    CUSTOMER = "Customer"
    DELIVERY_TECHNICIAN = "DeliveryTechnician"
    SERVICE_AGENT = "ServiceAgent"
    FINANCE_AGENT = "FinanceAgent"
    DEVICE_GATEWAY = "DeviceGateway"


class Store(TypedDict, total=False):
    id: str
    name: str
    zone_codes: List[str]
    default_window_capacity_slots: int
    created_at: str
    updated_at: str
    version: int


class ProductModel(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    price_cents: int
    replacement_part_price_cents: int
    warranty_months: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    home_store_id: str
    email: str
    full_name: str
    subscription_tier: str
    subscription_status: str
    store_credit_cents: int
    entitlements: List[str]
    created_at: str
    updated_at: str
    version: int


class FitAssessment(TypedDict, total=False):
    id: str
    customer_id: str
    store_id: str
    sleep_position: str
    weight_band: str
    partner_sleeper: bool
    preferred_feel: str
    recommended_firmness: Optional[int]
    recommended_skus: List[str]
    supersedes_assessment_id: Optional[str]
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    fit_assessment_id: str
    line_items: List[Dict[str, Any]]
    subtotal_cents: int
    discount_cents: int
    delivery_fee_cents: int
    total_due_cents: int
    total_paid_cents: int
    order_status: str
    payment_status: str
    trial_verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryWindow(TypedDict, total=False):
    id: str
    store_id: str
    team_id: str
    window_start: str
    window_end: str
    capacity_slots: int
    reserved_slots: int
    created_at: str
    updated_at: str
    version: int


class DeliveryVisit(TypedDict, total=False):
    id: str
    order_id: str
    delivery_window_id: str
    remove_old_mattress: bool
    slot_need: int
    room_prep_notes: Optional[str]
    setup_checklist: Optional[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    order_id: str
    customer_id: str
    kind: str
    serial_number: str
    firmware_version: str
    pairing_status: str
    connectivity: str
    final_nights_count: int
    created_at: str
    updated_at: str
    version: int


class SleepNight(TypedDict, total=False):
    id: str
    device_id: str
    customer_id: str
    night_date: str
    minutes_asleep: int
    restlessness_events: int
    avg_heart_rate: int
    provisional_score: int
    final_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrialReturn(TypedDict, total=False):
    id: str
    order_id: str
    reason: str
    refund_destination: str
    initiated_night_index: int
    condition: Optional[str]
    depreciation_cents: Optional[int]
    restocking_fee_cents: Optional[int]
    refund_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    order_id: str
    device_id: str
    component_category: str
    proration_variant: str
    description: str
    months_in_service: int
    final_nights_used: int
    credit_cents: Optional[int]
    applied_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingPlan(TypedDict, total=False):
    id: str
    order_id: str
    offer_type: str
    down_payment_cents: int
    term_months: int
    apr_bps: int
    principal_cents: int
    monthly_payment_cents: int
    promo_months: int
    paid_cents: int
    balance_cents: int
    retro_interest_posted: bool
    settled_credit_cents: int
    activated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
