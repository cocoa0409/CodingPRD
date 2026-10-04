"""Domain types: entity status enums and role enum."""
from enum import Enum


class OutreachMode(str, Enum):
    PUSH = "PUSH"
    SELF_SERVE = "SELF_SERVE"


class RiskCategory(str, Enum):
    AVERAGE = "AVERAGE"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECEASED = "DECEASED"
    OPTED_OUT = "OPTED_OUT"


class ProviderChannel(str, Enum):
    ORDERING = "ORDERING"
    TELEHEALTH = "TELEHEALTH"


class CohortStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    OUTREACH_SENT = "OUTREACH_SENT"
    ORDERED = "ORDERED"
    SCREENED = "SCREENED"
    EXCLUDED = "EXCLUDED"


class OrderStatus(str, Enum):
    PENDING_ELIGIBILITY = "PENDING_ELIGIBILITY"
    ELIGIBLE = "ELIGIBLE"
    REJECTED_INELIGIBLE = "REJECTED_INELIGIBLE"
    KIT_ORDERED = "KIT_ORDERED"
    KIT_SHIPPED = "KIT_SHIPPED"
    KIT_RETURNED = "KIT_RETURNED"
    IN_LAB = "IN_LAB"
    RESULTED = "RESULTED"
    CANCELLED = "CANCELLED"
    ABANDONED = "ABANDONED"
    RECOLLECTION_REQUESTED = "RECOLLECTION_REQUESTED"


class QualityOutcome(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    ADHERENT_NEGATIVE = "ADHERENT_NEGATIVE"
    ADHERENT_POSITIVE_NAVIGATED = "ADHERENT_POSITIVE_NAVIGATED"
    POSITIVE_NAVIGATION_PENDING = "POSITIVE_NAVIGATION_PENDING"
    POSITIVE_NAVIGATION_LAPSED = "POSITIVE_NAVIGATION_LAPSED"


class ContactChannel(str, Enum):
    MAIL = "MAIL"
    SMS = "SMS"
    PHONE = "PHONE"


class ReminderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    SKIPPED = "SKIPPED"


class KitStatus(str, Enum):
    ORDERED = "ORDERED"
    SHIPPED = "SHIPPED"
    RETURNED = "RETURNED"
    IN_PROCESSING = "IN_PROCESSING"
    CONSUMED = "CONSUMED"
    EXPIRED_STABILIZATION = "EXPIRED_STABILIZATION"
    CANCELLED = "CANCELLED"


class SpecimenStatus(str, Enum):
    ACCESSIONED = "ACCESSIONED"
    PROCESSING = "PROCESSING"
    ADEQUATE = "ADEQUATE"
    INADEQUATE = "INADEQUATE"
    RESULTED = "RESULTED"


class Adequacy(str, Enum):
    PENDING = "PENDING"
    ADEQUATE = "ADEQUATE"
    INADEQUATE = "INADEQUATE"


class ResultOutcome(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class NavigationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    LAPSED = "LAPSED"


class RecommendedChannel(str, Enum):
    HOME_KIT_OK = "HOME_KIT_OK"
    CLINIC = "CLINIC"


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    PROVIDER = "Provider"
    FULFILLMENT_AGENT = "FulfillmentAgent"
    LAB_TECHNICIAN = "LabTechnician"
    NAVIGATOR = "Navigator"
