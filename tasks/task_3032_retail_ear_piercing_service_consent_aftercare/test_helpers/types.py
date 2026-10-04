"""Domain types: entity TypedDicts, status enums and the role enum.

Every entity in this API carries the four system-managed properties
``id``, ``created_at``, ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    INTAKE_ASSOCIATE = "IntakeAssociate"
    PIERCER = "Piercer"
    STORE_MANAGER = "StoreManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    STERILIZATION_TECHNICIAN = "SterilizationTechnician"
    CUSTOMER = "Customer"
    ANONYMOUS = "Anonymous"
    ANY_AUTHENTICATED = "AnyAuthenticated"


class JurisdictionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class StorePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class StoreStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class PiercerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class CertificationLevel(str, Enum):
    APPRENTICE = "APPRENTICE"
    STANDARD = "STANDARD"
    SENIOR = "SENIOR"
    INSTRUCTOR = "INSTRUCTOR"


class CertificationStatus(str, Enum):
    VALID = "VALID"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    RECERTIFICATION_PENDING = "RECERTIFICATION_PENDING"
    REVOKED = "REVOKED"


class SterilizationCycleStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"
    RELEASED = "RELEASED"


class CartridgeLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"
    DISCARDED = "DISCARDED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FLAGGED = "FLAGGED"
    CLOSED = "CLOSED"


class ConsentType(str, Enum):
    SELF = "SELF"
    GUARDIAN_PRESENT = "GUARDIAN_PRESENT"
    GUARDIAN_NOTARIZED = "GUARDIAN_NOTARIZED"
    COURT_ORDER = "COURT_ORDER"


class GuardianVerificationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class IdentificationType(str, Enum):
    GOVERNMENT_PHOTO_ID = "GOVERNMENT_PHOTO_ID"
    BIRTH_CERTIFICATE = "BIRTH_CERTIFICATE"
    PASSPORT = "PASSPORT"
    STATE_ID = "STATE_ID"
    NONE = "NONE"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    REJECTED = "REJECTED"


class IntakeType(str, Enum):
    SCHEDULED = "SCHEDULED"
    WALK_IN = "WALK_IN"


class SiteType(str, Enum):
    LOBE = "LOBE"
    UPPER_LOBE = "UPPER_LOBE"
    HELIX = "HELIX"
    TRAGUS = "TRAGUS"
    INDUSTRIAL = "INDUSTRIAL"
    NOSTRIL = "NOSTRIL"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    SCREENED = "SCREENED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    REFUSED = "REFUSED"


class ScreeningOutcome(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    REFUSED = "REFUSED"
    ESCALATED = "ESCALATED"


class ServiceStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class HealingStatus(str, Enum):
    HEALING = "HEALING"
    HEALED = "HEALED"
    FAILED = "FAILED"
    RE_PIERCED = "RE_PIERCED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    MEDICAL_EMERGENCY = "MEDICAL_EMERGENCY"


class EscalationStatus(str, Enum):
    LOGGED = "LOGGED"
    TRIAGED = "TRIAGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    REFUND_ISSUED = "REFUND_ISSUED"
    REOPENED = "REOPENED"


class RefundStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    DECLINED = "DECLINED"


class HealingResult(str, Enum):
    PENDING_ASSESSMENT = "PENDING_ASSESSMENT"
    HEALED = "HEALED"
    FAILED = "FAILED"
    DOWNGRADED = "DOWNGRADED"


class HealingOutcomeStatus(str, Enum):
    ASSESSED = "ASSESSED"
    RE_PIERCE_ELIGIBLE = "RE_PIERCE_ELIGIBLE"
    RE_PIERCED = "RE_PIERCED"
    DOWNGRADED = "DOWNGRADED"
    CLOSED = "CLOSED"


class Jurisdiction(TypedDict):
    id: str
    state_code: str
    min_age_self_consent: int
    min_age_with_guardian: int
    min_age_absolute: int
    permitted_sites: List[str]
    requires_guardian_presence: bool
    record_retention_years: int
    consent_form_version: str
    sterilization_protocol_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StoreLocation(TypedDict):
    id: str
    name: str
    jurisdiction_id: str
    piercing_room_count: int
    compliance_posture: str
    open_incident_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Piercer(TypedDict, total=False):
    id: str
    full_name: str
    home_store_id: str
    eligibility_score: int
    active_certification_id: Optional[str]
    assigned_session_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CertificationRecord(TypedDict):
    id: str
    piercer_id: str
    certification_level: str
    sterilization_protocol_code: str
    issued_at: str
    expires_at: str
    recertification_due_at: str
    attempted_practical_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SterilizationCycle(TypedDict):
    id: str
    store_location_id: str
    autoclave_unit_id: str
    protocol_code: str
    cycle_start_at: str
    cycle_end_at: str
    temperature_celsius: float
    biological_indicator_passed: bool
    quarantine_scope_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CartridgeLot(TypedDict):
    id: str
    store_location_id: str
    sterilization_cycle_id: str
    lot_number: str
    site_type: str
    units_received: int
    units_available: int
    units_consumed: int
    units_quarantined: int
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    guardian_name: str
    guardian_contact: str
    aftercare_credit_cents: int
    refunded_cents: int
    retained_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict):
    id: str
    customer_id: str
    jurisdiction_id: str
    consent_type: str
    guardian_verification_status: str
    identification_type: str
    required_identification_type: str
    identification_number_masked: str
    signed_at: str
    expires_at: Optional[str]
    consent_status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    store_location_id: str
    customer_id: str
    piercer_id: str
    jurisdiction_id: str
    intake_type: str
    site_requested: str
    slot_start_at: str
    slot_end_at: str
    reschedule_count: int
    governing_screening_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnatomyScreening(TypedDict):
    id: str
    appointment_id: str
    piercer_id: str
    anatomy_sites_examined: List[str]
    contraindication_codes: List[str]
    refusal_reason_code: Optional[str]
    outcome: str
    created_at: str
    updated_at: str
    version: int


class PiercingSession(TypedDict):
    id: str
    appointment_id: str
    piercer_id: str
    cartridge_lot_id: Optional[str]
    site_pierced: str
    base_fee_cents: int
    aftercare_kit_included: bool
    solution_lot_number: str
    follow_up_reminder_due_at: str
    follow_up_acknowledged: bool
    net_fee_cents: int
    service_status: str
    healing_status: str
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    session_id: str
    reported_at: str
    severity: str
    reaction_codes: List[str]
    escalation_status: str
    refund_amount_cents: int
    refund_status: str
    created_at: str
    updated_at: str
    version: int


class HealingOutcome(TypedDict):
    id: str
    session_id: str
    assessed_at: str
    healing_result: str
    downgrade_credited_cents: int
    re_pierce_eligible: bool
    re_pierce_claim_count: int
    status: str
    created_at: str
    updated_at: str
    version: int