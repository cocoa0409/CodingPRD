"""Domain types: entity status enums and role enum."""
from enum import Enum


class Track(str, Enum):
    IMPROV = "IMPROV"
    SKETCH = "SKETCH"
    STANDUP = "STANDUP"
    CONSERVATORY = "CONSERVATORY"


class CurriculumLevelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TermStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULING = "SCHEDULING"
    ENROLLMENT_OPEN = "ENROLLMENT_OPEN"
    IN_SESSION = "IN_SESSION"
    CLOSED = "CLOSED"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class CourseSectionStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StudentStanding(str, Enum):
    GOOD = "GOOD"
    FINANCIAL_HOLD = "FINANCIAL_HOLD"
    SUSPENDED = "SUSPENDED"


class PlacementDecision(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"


class PlacementVariant(str, Enum):
    AUDITION_BYPASS = "AUDITION_BYPASS"
    PORTFOLIO_REVIEW = "PORTFOLIO_REVIEW"


class EnrollmentStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    DROPPED_EARLY = "DROPPED_EARLY"
    DROPPED_LATE = "DROPPED_LATE"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"
    COMPLETED = "COMPLETED"
    CREDITED = "CREDITED"


class PriorityTier(str, Enum):
    RETURNING = "RETURNING"
    NEW = "NEW"


class ShowcaseStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    STAGED = "STAGED"
    ARCHIVED = "ARCHIVED"
    CANCELLED = "CANCELLED"


class VenueSlotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class CohortProgramStatus(str, Enum):
    FORMING = "FORMING"
    AUDITIONING = "AUDITIONING"
    CASTED = "CASTED"
    ACTIVE = "ACTIVE"
    GRADUATED = "GRADUATED"
    DISSOLVED = "DISSOLVED"


class CohortKind(str, Enum):
    CONSERVATORY = "CONSERVATORY"
    INTENSIVE = "INTENSIVE"


class AuditionTargetKind(str, Enum):
    COHORT = "COHORT"
    ENSEMBLE = "ENSEMBLE"
    TOURING = "TOURING"


class AuditionOutcome(str, Enum):
    SCHEDULED = "SCHEDULED"
    EVALUATED = "EVALUATED"
    SELECTED = "SELECTED"
    WAITLISTED = "WAITLISTED"
    REJECTED = "REJECTED"


class SourcePolicy(str, Enum):
    PIPELINE_ONLY = "PIPELINE_ONLY"
    OPEN_CALL = "OPEN_CALL"
    MIXED = "MIXED"


class EnsembleCastStatus(str, Enum):
    OPEN_ROLES = "OPEN_ROLES"
    CASTING = "CASTING"
    REHEARSING = "REHEARSING"
    RUNNING = "RUNNING"
    CLOSED = "CLOSED"


class TouringAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    ON_TOUR = "ON_TOUR"
    RETURNED = "RETURNED"
    REPLACED = "REPLACED"


class ScholarshipKind(str, Enum):
    NEED_BASED = "NEED_BASED"
    DIVERSITY = "DIVERSITY"
    MERIT = "MERIT"


class ScholarshipStatus(str, Enum):
    APPLIED = "APPLIED"
    AWARDED = "AWARDED"
    DENIED = "DENIED"
    DISBURSED = "DISBURSED"
    REVOKED = "REVOKED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    TRANSFERRED = "TRANSFERRED"
    VOID = "VOID"


class UserRole(str, Enum):
    PROGRAM_DIRECTOR = "ProgramDirector"
    REGISTRAR = "Registrar"
    PLACEMENT_OFFICER = "PlacementOfficer"
    CASTING_DIRECTOR = "CastingDirector"
    FINANCE_OFFICER = "FinanceOfficer"
    STUDENT = "Student"
