"""Domain types: entity TypedDicts, status enums and the role enum.

TypedDicts follow the PRD's common-field split: resources that declare common
fields carry ``id``, ``created_at``, ``updated_at`` and ``version``; the three
resources the PRD exempts (``BreedHandlingRule``, ``RabiesCertificate`` and
``GroomingRiskScreening``) carry only ``id`` and ``created_at``, and their
TypedDicts deliberately omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Optional, TypedDict


# ── Enumerations ─────────────────────────────────────────────────────────────

class StoreStateCode(str, Enum):
    CA = "CA"
    TX = "TX"
    NY = "NY"
    FL = "FL"


class HospitalPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    SUSPENDED = "SUSPENDED"


class PetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class Species(str, Enum):
    CANINE = "CANINE"
    FELINE = "FELINE"


class HandlingTier(str, Enum):
    STANDARD = "STANDARD"
    SENSITIVE = "SENSITIVE"
    HIGH_RISK = "HIGH_RISK"


class BayCode(str, Enum):
    GROOMING = "GROOMING"
    VETERINARY = "VETERINARY"
    TRAINING = "TRAINING"
    VACCINATION = "VACCINATION"


class BayStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    DISABLED = "DISABLED"


class ServiceType(str, Enum):
    GROOMING = "GROOMING"
    TRAINING = "TRAINING"
    VETERINARY = "VETERINARY"
    VACCINATION = "VACCINATION"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCREENED = "SCREENED"
    BAY_CONFIRMED = "BAY_CONFIRMED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class EncounterStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    IN_EXAM = "IN_EXAM"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClinicStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class VaccineType(str, Enum):
    RABIES = "RABIES"
    BORDETELLA = "BORDETELLA"
    DHPP = "DHPP"
    FVRCP = "FVRCP"


class VisitStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CERTIFICATE_ISSUED = "CERTIFICATE_ISSUED"
    REPORT_REQUIRED = "REPORT_REQUIRED"
    REPORTED = "REPORTED"
    BLOCKED = "BLOCKED"


class StateReportStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    NOT_REQUIRED = "NOT_REQUIRED"
    OVERDUE = "OVERDUE"


class ItemType(str, Enum):
    MEDICATION = "MEDICATION"
    DIET = "DIET"
    TREATMENT = "TREATMENT"


class AuthorizationStatus(str, Enum):
    PENDING_EXAM = "PENDING_EXAM"
    AUTHORIZED = "AUTHORIZED"
    PARTIALLY_DISPENSED = "PARTIALLY_DISPENSED"
    DISPENSED = "DISPENSED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PharmacyOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    DISPENSED = "DISPENSED"
    REJECTED = "REJECTED"


class OnHold(str, Enum):
    NONE = "NONE"
    HOLDING = "HOLDING"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class IncidentType(str, Enum):
    PET_INJURY = "PET_INJURY"
    HANDLER_INJURY = "HANDLER_INJURY"
    BITE = "BITE"


class ClaimStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PackageTier(str, Enum):
    ESSENTIAL = "ESSENTIAL"
    PLUS = "PLUS"
    UNLIMITED = "UNLIMITED"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class CycleStatus(str, Enum):
    PENDING = "PENDING"
    BILLED = "BILLED"
    FAILED = "FAILED"
    VOID = "VOID"


class CrossSellStatus(str, Enum):
    PENDING = "PENDING"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class EnrollmentStatus(str, Enum):
    PENDING_ACK = "PENDING_ACK"
    RESTRICTED = "RESTRICTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STORE_MANAGER = "StoreManager"
    VETERINARY_STAFF = "VeterinaryStaff"
    GROOMING_STAFF = "GroomingStaff"
    VACCINATION_STAFF = "VaccinationStaff"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PHARMACY_STAFF = "PharmacyStaff"
    TRAINING_STAFF = "TrainingStaff"
    ANY = "Any"


# ── TypedDicts: common_fields = true ─────────────────────────────────────────

class Store(TypedDict):
    id: str
    store_code: str
    city: str
    state_code: str
    service_bay_count: int
    hospital_capacity: int
    hospital_occupancy: int
    hospital_posture: str
    pharmacy_hold_until: Optional[str]
    cross_sell_credit_balance_cents: int
    incident_risk_index: int
    restricted_training_slots_pending: int
    frozen_vaccination_clinics: int
    stores_held_total: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    email: str
    state_code: str
    home_store_id: str
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Pet(TypedDict):
    id: str
    member_id: str
    name: str
    species: str
    breed: str
    weight_kg: float
    rabies_vaccination_expires_at: Optional[str]
    risk_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceBay(TypedDict):
    id: str
    store_id: str
    bay_code: str
    is_frozen: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceBooking(TypedDict):
    id: str
    store_id: str
    bay_id: str
    pet_id: str
    service_type: str
    starts_at: str
    ends_at: str
    screening_score: int
    pet_version: int
    handling_level: Optional[str]
    screening_valid_until: Optional[str]
    re_screen_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class VeterinaryEncounter(TypedDict):
    id: str
    pet_id: str
    store_id: str
    booking_id: Optional[str]
    clinician_name: str
    scheduled_at: str
    chief_complaint: Optional[str]
    exam_date: Optional[str]
    medical_notes: Optional[str]
    charge_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VaccinationClinic(TypedDict):
    id: str
    store_id: str
    clinic_date: str
    open_time: str
    close_time: str
    coverage_required: bool
    coverage_provider: Optional[str]
    clinic_status: str
    created_at: str
    updated_at: str
    version: int


class VaccinationVisit(TypedDict):
    id: str
    clinic_id: str
    pet_id: str
    store_id: str
    walk_in_at: str
    vaccine_type: str
    prior_rabies_vaccination_date: Optional[str]
    prior_effective_days: Optional[int]
    prior_is_booster: bool
    new_effective_days: Optional[int]
    certificate_serial: Optional[str]
    certificate_issued_at: Optional[str]
    certificate_expires_at: Optional[str]
    state_report_status: str
    state_report_due_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PrescriptionAuthorization(TypedDict):
    id: str
    pet_id: str
    encounter_id: str
    store_id: str
    item_type: str
    item_name: str
    sku: str
    unit_price_cents: int
    quantity: int
    authorized_at: Optional[str]
    expires_at: Optional[str]
    price_at_authorization_cents: int
    retail_facing: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PharmacyOrder(TypedDict):
    id: str
    authorization_id: str
    store_id: str
    requested_quantity: int
    on_hold: str
    status: str
    current_retail_price_cents: int
    created_at: str
    updated_at: str
    version: int


class IncidentRecord(TypedDict):
    id: str
    store_id: str
    booking_id: str
    pet_id: str
    severity: str
    incident_type: str
    risk_points: int
    claim_amount_cents: int
    payout_amount_cents: int
    risk_points_lost: int
    available_claimable_cents: int
    override_reason: Optional[str]
    claim_status: str
    created_at: str
    updated_at: str
    version: int


class ServicePackage(TypedDict):
    id: str
    member_id: str
    member_state_code: str
    tier: str
    state_sales_tax_rate: float
    monthly_fee_cents: int
    monthly_total_cents: float
    total_price_cents: float
    billing_cycle_count: int
    grooming_visits_included: int
    vet_visits_included: int
    vaccine_visits_included: int
    included_visits_total: int
    consumed_visits: int
    cycles_consumed: int
    overage_visits: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PackageBillingCycle(TypedDict):
    id: str
    package_id: str
    cycle_index: int
    cycle_total_cents: float
    overage_credit_cents: int
    tax_cents: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RetailCrossSell(TypedDict):
    id: str
    store_id: str
    authorization_id: str
    pet_id: str
    sku: str
    gross_cents: int
    credit_granted_cents: int
    credit_redeemed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingEnrollment(TypedDict):
    id: str
    package_id: str
    store_id: str
    pet_id: str
    class_code: str
    courses_required: int
    courses_completed: int
    courses_needed: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ── TypedDicts: common_fields = false (append-only, id + created_at only) ────

class BreedHandlingRule(TypedDict):
    id: str
    breed: str
    species: str
    risk_points: int
    handling_tier: str
    allowed_for_grooming: bool
    created_at: str
    # no updated_at, no version


class RabiesCertificate(TypedDict):
    id: str
    visit_id: str
    pet_id: str
    store_id: str
    serial: str
    issued_at: str
    expires_at: str
    effective_days: int
    is_booster: bool
    is_effective: bool
    created_at: str
    # no updated_at, no version


class GroomingRiskScreening(TypedDict):
    id: str
    booking_id: str
    risk_total: int
    health_condition_points: int
    handling_level: str
    aggression_acknowledged: bool
    recorded_at: str
    valid_until: str
    created_at: str
    # no updated_at, no version