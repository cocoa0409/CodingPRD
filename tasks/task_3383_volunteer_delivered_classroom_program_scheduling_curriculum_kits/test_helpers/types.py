"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    AREA_DIRECTOR = "AreaDirector"
    PARTNERSHIP_MANAGER = "PartnershipManager"
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    FUNDER = "Funder"


class DistrictStatus(str, Enum):
    PROSPECT = "PROSPECT"
    PARTNER = "PARTNER"
    AT_RISK = "AT_RISK"
    CHURNED = "CHURNED"


class PartnerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class ScreeningStatus(str, Enum):
    INITIATED = "INITIATED"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    EXPIRED = "EXPIRED"


class TrainingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class EngagementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPARTED = "DEPARTED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"


class DeliveryStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class KitStatus(str, Enum):
    NONE = "NONE"
    RESERVED = "RESERVED"
    DISTRIBUTED = "DISTRIBUTED"
    RECONCILED = "RECONCILED"
    RELEASED = "RELEASED"


class SessionStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    SCHEDULED = "SCHEDULED"
    NEEDS_SUBSTITUTE = "NEEDS_SUBSTITUTE"
    DELIVERED = "DELIVERED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class CapstoneStatus(str, Enum):
    PLANNED = "PLANNED"
    READY = "READY"
    ROLES_ASSIGNED = "ROLES_ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SurveyStatus(str, Enum):
    NONE = "NONE"
    PRE_SUBMITTED = "PRE_SUBMITTED"
    PAIRED = "PAIRED"
    VALIDATED = "VALIDATED"
    EXCLUDED = "EXCLUDED"


class RecognitionTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class CapstoneFacility(str, Enum):
    SIMULATED_TOWN = "SIMULATED_TOWN"
    FINANCE_PARK = "FINANCE_PARK"
    NONE = "NONE"


# All twelve resource types carry the common set: id, created_at, updated_at,
# version (PRD §2.5).


class AreaOffice(TypedDict):
    id: str
    name: str
    region_code: str
    max_districts: int
    created_at: str
    updated_at: str
    version: int


class SchoolDistrict(TypedDict):
    id: str
    area_office_id: str
    name: str
    relationship_status: str
    created_at: str
    updated_at: str
    version: int


class School(TypedDict):
    id: str
    district_id: str
    name: str
    grade_band_low: int
    grade_band_high: int
    instructional_days: List[str]
    created_at: str
    updated_at: str
    version: int


class CorporatePartner(TypedDict):
    id: str
    name: str
    industry: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    corporate_partner_id: str
    full_name: str
    email: str
    screening_status: str
    screening_expires_on: Optional[str]
    training_status: str
    training_expires_on: Optional[str]
    engagement_status: str
    hours_contributed: float
    eligible: bool
    created_at: str
    updated_at: str
    version: int


class ProgramCatalog(TypedDict):
    id: str
    code: str
    title: str
    grade_band_low: int
    grade_band_high: int
    session_count: int
    minutes_per_session: int
    capstone_required: bool
    capstone_facility: str
    min_students: int
    max_students: int
    created_at: str
    updated_at: str
    version: int


class PartnershipAgreement(TypedDict):
    id: str
    school_id: str
    program_catalog_id: str
    sponsor_partner_id: str
    school_year: str
    funding_pledged_cents: int
    funding_received_cents: int
    pending_program_catalog_id: Optional[str]
    pending_funding_pledged_cents: Optional[int]
    status: str
    sponsor_volunteer_hours: float
    recognition_tier: str
    deliveries_completed_count: int
    created_at: str
    updated_at: str
    version: int


class ClassroomDelivery(TypedDict):
    id: str
    agreement_id: str
    program_catalog_id: str
    lead_volunteer_id: str
    classroom_label: str
    teacher_email: str
    teacher_confirmed: bool
    enrolled_count: int
    required_kits: int
    status: str
    kit_status: str
    kits_consumed: int
    sessions_delivered_count: int
    sessions_blocked_count: int
    created_at: str
    updated_at: str
    version: int


class DeliverySession(TypedDict):
    id: str
    delivery_id: str
    volunteer_id: str
    sequence_no: int
    scheduled_date: str
    start_minutes: int
    end_minutes: int
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class KitInventory(TypedDict):
    id: str
    area_office_id: str
    program_catalog_id: str
    assembled_count: int
    available_count: int
    reserved_count: int
    distributed_count: int
    written_off_count: int
    consumed_count: int
    created_at: str
    updated_at: str
    version: int


class CapstoneEvent(TypedDict):
    id: str
    delivery_id: str
    facility: str
    event_date: str
    start_minutes: int
    end_minutes: int
    rotation_slot_count: int
    status: str
    assigned_student_count: int
    created_at: str
    updated_at: str
    version: int


class StudentParticipant(TypedDict):
    id: str
    delivery_id: str
    capstone_event_id: Optional[str]
    full_name: str
    external_ref: str
    rotation_group: Optional[int]
    capstone_role: Optional[str]
    pre_score: Optional[int]
    post_score: Optional[int]
    survey_status: str
    created_at: str
    updated_at: str
    version: int
