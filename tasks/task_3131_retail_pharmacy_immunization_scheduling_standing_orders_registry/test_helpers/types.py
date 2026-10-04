"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProtocolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AuthorityType(str, Enum):
    STANDING_ORDER = "STANDING_ORDER"
    PROTOCOL = "PROTOCOL"
    PRESCRIPTION_REQUIRED = "PRESCRIPTION_REQUIRED"


class RegistryFormat(str, Enum):
    HL7_VXU = "HL7_VXU"
    FLAT_FILE_CSV = "FLAT_FILE_CSV"
    STATE_API_JSON = "STATE_API_JSON"


class BenefitType(str, Enum):
    PHARMACY = "PHARMACY"
    MEDICAL = "MEDICAL"
    BOTH = "BOTH"


class LotStatus(str, Enum):
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


class ExcursionSeverityTier(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class ExcursionDisposition(str, Enum):
    RELEASE_OK = "RELEASE_OK"
    RELEASE_OK_CUMULATIVE = "RELEASE_OK_CUMULATIVE"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    SCREENED = "SCREENED"
    CONSENTED = "CONSENTED"
    VACCINATED = "VACCINATED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    EXPIRED = "EXPIRED"


class ReviewOutcome(str, Enum):
    CLEARED = "CLEARED"
    REFERRED_OUT = "REFERRED_OUT"


class RecordStatus(str, Enum):
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class BillingChannel(str, Enum):
    PHARMACY_BENEFIT = "PHARMACY_BENEFIT"
    MEDICAL_BENEFIT = "MEDICAL_BENEFIT"
    CASH = "CASH"


class SubmissionStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    LATE_UNRESOLVED = "LATE_UNRESOLVED"


class ObservationStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"


class EventStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    STORE_MANAGER = "StoreManager"
    PHARMACIST = "Pharmacist"
    PHARMACY_TECHNICIAN = "PharmacyTechnician"
    IMMUNIZER = "Immunizer"
    OBSERVATION_MONITOR = "ObservationMonitor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PATIENT = "Patient"


# ---- Entity TypedDicts (common_fields: true unless noted) ----


class PharmacyStore(TypedDict, total=False):
    id: str
    store_number: str
    state_code: str
    address_line: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StateProtocol(TypedDict, total=False):
    id: str
    state_code: str
    vaccine_product_id: str
    authority_type: str
    min_patient_age_years: int
    max_doses_per_patient_per_day: int
    registry_format: str
    registry_deadline_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VaccineProduct(TypedDict, total=False):
    id: str
    cvx_code: str
    name: str
    min_patient_age_years: int
    doses_per_series: int
    min_interval_days: int
    cash_price_cents: int
    fridge_temp_min_c: float
    fridge_temp_max_c: float
    observation_minutes: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    state_code: str
    allergy_flags: List[str]
    high_risk_flag: bool
    insurance_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsurancePlan(TypedDict, total=False):
    id: str
    plan_name: str
    benefit_type: str
    copay_cents: int
    coinsurance_pct: float
    deductible_remaining_cents: int
    covered_cvx_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class VaccineLot(TypedDict, total=False):
    id: str
    store_id: str
    vaccine_product_id: str
    lot_number: str
    expiration_date: str
    doses_received: int
    doses_available: int
    status: str
    quarantine_reason: Optional[str]
    last_excursion_severity_tier: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TemperatureReading(TypedDict, total=False):
    # common_fields: false — carries ONLY id and created_at (no updated_at, no version)
    id: str
    lot_id: str
    recorded_at: str
    temperature_c: float
    is_excursion: bool
    excursion_severity_tier: str
    created_at: str


class ImmunizationAppointment(TypedDict, total=False):
    id: str
    store_id: str
    patient_id: str
    vaccine_product_id: str
    state_protocol_id: str
    slot_start: str
    is_walk_in: bool
    dose_number: int
    status: str
    scheduled_dose_count_today: int
    created_at: str
    updated_at: str
    version: int


class PrescreeningQuestionnaire(TypedDict, total=False):
    id: str
    appointment_id: str
    answers: dict
    contraindication_detected: bool
    reviewed_by_pharmacist_id: Optional[str]
    review_outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImmunizationRecord(TypedDict, total=False):
    id: str
    appointment_id: str
    patient_id: str
    lot_id: str
    administered_by: str
    administered_at: str
    dose_number: int
    charge_cents: int
    billing_channel: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RegistrySubmission(TypedDict, total=False):
    id: str
    immunization_record_id: str
    payload_format: str
    payload: str
    due_at: str
    submitted_at: Optional[str]
    acknowledged_at: Optional[str]
    is_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ObservationSession(TypedDict, total=False):
    id: str
    immunization_record_id: str
    observer_id: str
    required_minutes: int
    started_at: str
    ended_at: Optional[str]
    adverse_reaction: bool
    reaction_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClinicEvent(TypedDict, total=False):
    id: str
    store_id: str
    employer_name: str
    event_start: str
    event_end: str
    mobile_lot_id: str
    doses_reserved: int
    doses_administered: int
    status: str
    created_at: str
    updated_at: str
    version: int
