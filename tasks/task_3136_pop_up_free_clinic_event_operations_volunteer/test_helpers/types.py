"""Domain types: entity TypedDicts, status enums, role enum for the clinic API."""

from enum import Enum
from typing import Optional, TypedDict


class Posture(str, Enum):
    PLANNING = "PLANNING"
    SITE_LOCKED = "SITE_LOCKED"
    STAFFING = "STAFFING"
    READY = "READY"
    IN_SERVICE = "IN_SERVICE"
    TEARDOWN = "TEARDOWN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SiteStatus(str, Enum):
    PROSPECT = "PROSPECT"
    VETTED = "VETTED"
    RETIRED = "RETIRED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    NEGOTIATING = "NEGOTIATING"
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class VolunteerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    VERIFIED = "VERIFIED"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED_REVIEW = "EXPIRED_REVIEW"


class AssignmentStatus(str, Enum):
    ROSTERED = "ROSTERED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    NO_SHOW = "NO_SHOW"
    RELEASED = "RELEASED"


class StationStatus(str, Enum):
    PLANNED = "PLANNED"
    SET_UP = "SET_UP"
    STERILIZATION_CLEARED = "STERILIZATION_CLEARED"
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    DISMANTLED = "DISMANTLED"


class TicketStatus(str, Enum):
    QUEUED = "QUEUED"
    CALLED = "CALLED"
    IN_SERVICE = "IN_SERVICE"
    SERVED = "SERVED"
    NO_SHOW = "NO_SHOW"
    TURNED_AWAY = "TURNED_AWAY"
    WITHDRAWN = "WITHDRAWN"


class EncounterStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class ManifestStatus(str, Enum):
    PACKED = "PACKED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    UNPACKED = "UNPACKED"
    REPACKED = "REPACKED"


class CycleStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class HandoffStatus(str, Enum):
    DRAFT = "DRAFT"
    PACKET_ASSEMBLED = "PACKET_ASSEMBLED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"


class Discipline(str, Enum):
    DENTAL = "DENTAL"
    VISION = "VISION"
    MEDICAL = "MEDICAL"
    GENERAL = "GENERAL"


class StationType(str, Enum):
    TRIAGE = "TRIAGE"
    DENTAL = "DENTAL"
    VISION = "VISION"
    MEDICAL = "MEDICAL"
    GLASSES_LAB = "GLASSES_LAB"
    DENTURE_LAB = "DENTURE_LAB"


class UserRole(str, Enum):
    EVENT_DIRECTOR = "EventDirector"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
    CREDENTIALING_OFFICER = "CredentialingOfficer"
    QUEUE_MARSHAL = "QueueMarshal"
    STATION_LEAD = "StationLead"
    STERILIZATION_TECH = "SterilizationTech"
    COMMUNITY_PARTNER_REP = "CommunityPartnerRep"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---


class ClinicEvent(TypedDict, total=False):
    id: str
    event_code: str
    name: str
    host_state_code: str
    service_date: str
    doors_open_utc: str
    total_patient_capacity: int
    posture: str
    confirmed_site_agreement_id: Optional[str]
    dental_chair_count: int
    vision_lane_count: int
    medical_bay_count: int
    verified_volunteer_count: int
    tickets_issued_count: int
    tickets_served_count: int
    unmet_demand_count: int
    projected_servable_patients: float
    sterilization_cycles_completed: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict, total=False):
    id: str
    site_name: str
    site_type: str
    state_code: str
    square_footage: int
    has_loading_dock: bool
    power_capacity_kw: float
    sterilization_capable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SiteAgreement(TypedDict, total=False):
    id: str
    clinic_event_id: str
    site_id: str
    host_org_name: str
    liability_cap_cents: int
    insurance_certificate_ref: str
    cost_share_cents: int
    status: str
    supersedes_agreement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    discipline: str
    license_number: str
    license_state_code: str
    license_expiry_date: str
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LicenseVerification(TypedDict, total=False):
    id: str
    volunteer_id: str
    clinic_event_id: str
    reviewer_notes: str
    attempt_sequence: int
    status: str
    denial_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisciplineAssignment(TypedDict, total=False):
    id: str
    clinic_event_id: str
    volunteer_id: str
    station_id: Optional[str]
    shift_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceStation(TypedDict, total=False):
    id: str
    clinic_event_id: str
    station_label: str
    station_type: str
    chair_count: int
    minutes_per_patient: int
    requires_sterilization: bool
    service_window_open_utc: str
    service_window_close_utc: str
    status: str
    served_count: int
    created_at: str
    updated_at: str
    version: int


class PatientTicket(TypedDict, total=False):
    id: str
    clinic_event_id: str
    patient_ref: str
    arrival_utc: str
    requested_service: str
    priority_tier: str
    queue_position: int
    status: str
    turn_away_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PatientEncounter(TypedDict, total=False):
    id: str
    clinic_event_id: str
    ticket_id: str
    station_id: str
    volunteer_id: str
    encounter_type: str
    findings_summary: str
    requires_followup: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# ReferralRecord: common_fields false — only id + created_at (no updated_at, no version)
class ReferralRecord(TypedDict, total=False):
    id: str
    encounter_id: str
    clinic_event_id: str
    referral_type: str
    partner_org_name: str
    urgency: str
    notes: str
    created_at: str


class EquipmentManifest(TypedDict, total=False):
    id: str
    clinic_event_id: str
    manifest_label: str
    item_count: int
    weight_kg: float
    requires_loading_dock: bool
    contains_sterilizer: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SterilizationCycle(TypedDict, total=False):
    id: str
    clinic_event_id: str
    cycle_sequence: int
    instrument_batch_size: int
    started_utc: str
    completed_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# UnmetDemandReport: common_fields false — only id + created_at
class UnmetDemandReport(TypedDict, total=False):
    id: str
    clinic_event_id: str
    generated_at_utc: str
    turned_away_count: int
    estimated_unserved_beyond_queue: int
    projected_shortfall_patients: int
    report_variant: str
    created_at: str


class CommunityHandoff(TypedDict, total=False):
    id: str
    clinic_event_id: str
    partner_org_name: str
    referral_packet_count: int
    teardown_checklist_complete: bool
    status: str
    created_at: str
    updated_at: str
    version: int
