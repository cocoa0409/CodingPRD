"""Domain types: entity status enums and role enum for the CGM platform."""
from enum import Enum


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECEASED = "DECEASED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class PrescriberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PrescriberSpecialty(str, Enum):
    ENDOCRINOLOGY = "ENDOCRINOLOGY"
    PRIMARY_CARE = "PRIMARY_CARE"
    OTHER = "OTHER"


class PayerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class BenefitRoute(str, Enum):
    PHARMACY = "PHARMACY"
    DME = "DME"


class CoveragePolicy(str, Enum):
    STRICT = "STRICT"
    STANDARD = "STANDARD"
    LENIENT = "LENIENT"


class SensorProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ReaderChannel(str, Enum):
    READER = "READER"
    APP = "APP"
    HYBRID = "HYBRID"


class LotComplaintPosture(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    HOLD = "HOLD"


class PrescriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class InsulinUse(str, Enum):
    INTENSIVE = "INTENSIVE"
    BASAL_ONLY = "BASAL_ONLY"
    NONE = "NONE"


class VerificationDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    DIAGNOSIS_NOT_COVERED = "DIAGNOSIS_NOT_COVERED"
    INSUFFICIENT_INSULIN_USE = "INSUFFICIENT_INSULIN_USE"
    MISSING_DOCUMENTATION = "MISSING_DOCUMENTATION"
    PAYER_INACTIVE = "PAYER_INACTIVE"


class SensorUnitStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    IN_HAND = "IN_HAND"
    ACTIVE = "ACTIVE"
    EXPIRED_WORN = "EXPIRED_WORN"
    FAILED_EARLY = "FAILED_EARLY"
    REPLACED = "REPLACED"
    SCRAPPED = "SCRAPPED"


class OrderFulfillmentStatus(str, Enum):
    PENDING_PICK = "PENDING_PICK"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    ADJUDICATED = "ADJUDICATED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class BindingChannel(str, Enum):
    READER = "READER"
    APP = "APP"


class DeviceBindingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED_NORMALLY = "ENDED_NORMALLY"
    ENDED_EARLY_FAILURE = "ENDED_EARLY_FAILURE"
    SUPERSEDED = "SUPERSEDED"


class FailureCategory(str, Enum):
    NO_READINGS = "NO_READINGS"
    INACCURATE = "INACCURATE"
    ADHESIVE_FAILURE = "ADHESIVE_FAILURE"
    SENSOR_ERROR = "SENSOR_ERROR"
    OTHER = "OTHER"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DATA_REVIEW = "DATA_REVIEW"
    MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class ReplacementShipmentStatus(str, Enum):
    PENDING_SHIP = "PENDING_SHIP"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class SupportEnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AdverseEventSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AdverseEventType(str, Enum):
    SKIN_IRRITATION = "SKIN_IRRITATION"
    INACCURACY_HARM = "INACCURACY_HARM"
    SENSOR_DETACHED = "SENSOR_DETACHED"
    ALLERGIC_REACTION = "ALLERGIC_REACTION"
    OTHER = "OTHER"


class AdverseEventStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    CLOSED_SUBSTANTIATED = "CLOSED_SUBSTANTIATED"
    CLOSED_UNSUBSTANTIATED = "CLOSED_UNSUBSTANTIATED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRESCRIBER = "Prescriber"
    COVERAGE_REVIEWER = "CoverageReviewer"
    FULFILLMENT_AGENT = "FulfillmentAgent"
    BILLING_AGENT = "BillingAgent"
    PATIENT = "Patient"
    WARRANTY_REVIEWER = "WarrantyReviewer"
    QUALITY_ENGINEER = "QualityEngineer"
    PATIENT_SUPPORT_AGENT = "PatientSupportAgent"
