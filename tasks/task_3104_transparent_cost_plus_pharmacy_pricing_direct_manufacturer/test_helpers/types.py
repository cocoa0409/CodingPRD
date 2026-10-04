"""Domain types for the transparent cost-plus pharmacy API.

Every resource in this system carries the same four system-managed fields
(id, created_at, updated_at, version) — there are no partial-carriage
resources — so every entity TypedDict below includes all four.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────

class ManufacturerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PharmacyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PrescriberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DrugState(str, Enum):
    FORMULARY = "FORMULARY"
    NON_FORMULARY = "NON_FORMULARY"
    DELISTED = "DELISTED"


class DrugSourcingStatus(str, Enum):
    SOURCED = "SOURCED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UNSOURCED = "UNSOURCED"
    SUSPENDED = "SUSPENDED"


class PriceStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class PriceSourcingStatus(str, Enum):
    SOURCED = "SOURCED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUPPRESSED = "SUPPRESSED"


class ReliabilityTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class LicenseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    INTAKE_REVIEW = "INTAKE_REVIEW"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"
    TERMINATED = "TERMINATED"


class PrescriptionRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    PAID = "PAID"
    FULFILLING = "FULFILLING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELED = "CANCELED"


class ShipmentStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


class ClaimStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    SHIPPED = "SHIPPED"
    DENIED = "DENIED"
    CANCELED = "CANCELED"


class ComparisonStatus(str, Enum):
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    SUBSTANTIATED = "SUBSTANTIATED"
    BLOCKED = "BLOCKED"


class ComparisonState(str, Enum):
    FRESH = "FRESH"
    REFRESH_REQUIRED = "REFRESH_REQUIRED"
    STALE = "STALE"


class SubstantiationStatus(str, Enum):
    PENDING = "PENDING"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class SubstantiationSourceKind(str, Enum):
    RETAIL_SURVEY = "RETAIL_SURVEY"
    BENEFIT_INDEX = "BENEFIT_INDEX"
    MANUFACTURER_NOTICE = "MANUFACTURER_NOTICE"


class UserRole(str, Enum):
    PATIENT = "Patient"
    PHARMACIST = "Pharmacist"
    PHARMACY_OPS = "PharmacyOps"
    ANONYMOUS = "Anonymous"


# Claim denial reason codes (denial_reason_code values, not error_ids)
DENIAL_REASONS = (
    "REFILLS_EXHAUSTED",
    "SOURCING_UNAVAILABLE",
    "DRUG_DELISTED",
    "SUPPLY_SHORTFALL",
    "ORDER_CANCELED",
    "SOURCING_LOST",
)


# ─── Entity TypedDicts ────────────────────────────────

class Manufacturer(TypedDict):
    id: str
    manufacturer_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Drug(TypedDict):
    id: str
    drug_name: str
    strength: str
    dosage_form: str
    is_controlled: bool
    state: str
    packaging: Optional[str]
    retail_reference_price_cents: int
    insured_reference_price_cents: int
    demand_units_30d: int
    supply_units: int
    sourcing_status: str
    effective_unit_cost_cents: Optional[int]
    ship_interval_days: Optional[int]
    expansion_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ManufacturerDrugPrice(TypedDict):
    id: str
    drug_id: str
    manufacturer_id: str
    unit_cost_cents: int
    available_units: int
    reliability_tier: str
    packaging: str
    price_status: str
    sourcing_status: str
    interval_days: int
    effective_per_unit_cents: int
    created_at: str
    updated_at: str
    version: int


class Pharmacy(TypedDict):
    id: str
    pharmacy_name: str
    domicile_state_code: str
    shipping_enabled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PharmacyLicense(TypedDict):
    id: str
    pharmacy_id: str
    state_code: str
    license_number: str
    status: str
    verified_at: Optional[str]
    expiry_at: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    email: str
    home_state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescriber(TypedDict):
    id: str
    prescriber_name: str
    npi: str
    license_state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict):
    id: str
    patient_id: str
    prescriber_id: str
    drug_id: str
    ship_state_code: str
    total_refills_authorized: int
    refills_consumed: int
    status: str
    rejection_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrescriptionRequest(TypedDict):
    id: str
    prescription_id: str
    packaged_quantity: int
    consumed_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    prescription_id: str
    request_id: str
    pharmacy_id: str
    quantity: int
    ship_state_code: str
    paid_at: Optional[str]
    status: str
    source_price_id: str
    sub_source_price_id: Optional[str]
    acquisition_cost_cents: int
    is_blended_cost: bool
    primary_units: int
    fallback_units: int
    markup_cents: int
    pharmacy_fee_cents: int
    shipping_fee_cents: int
    patient_price_cents: int
    retail_reference_price_cents: int
    insured_reference_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    request_id: str
    shipment_seq: int
    status: str
    dispatch_at: Optional[str]
    delivery_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    prescription_id: str
    claim_seq: int
    status: str
    reserved_quantity: int
    denied_at: Optional[str]
    denial_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceComparison(TypedDict):
    id: str
    order_id: str
    typical_retail_price_cents: int
    benefit_covered_price_cents: int
    substantiated: bool
    substantiation_digest: Optional[str]
    status: str
    state: str
    stale_deadline_at: str
    created_at: str
    updated_at: str
    version: int


class PriceSubstantiation(TypedDict):
    id: str
    order_id: str
    source_kind: str
    source_reference: str
    observed_at: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int