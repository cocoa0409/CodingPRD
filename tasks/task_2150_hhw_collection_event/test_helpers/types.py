"""Domain types for the Household Hazardous Waste collection programme API.

Entity TypedDicts, status enums and the role enum, named exactly as the PRD
names them. Every entity in this contract carries the full quartet of `id`,
`created_at`, `updated_at` and `version`.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role ─────────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    EVENT_COORDINATOR = "EventCoordinator"
    CONTAINMENT_INSPECTOR = "ContainmentInspector"
    ELIGIBILITY_CLERK = "EligibilityClerk"
    RESIDENT = "Resident"
    UNLOAD_TECH = "UnloadTech"
    PACKING_CONTRACTOR = "PackingContractor"
    ANONYMOUS = "Anonymous"


# ─── Program ──────────────────────────────────────────

class Posture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PostureOverride(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"


# ─── Site ─────────────────────────────────────────────

class SiteStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SiteAction(str, Enum):
    APPROVE = "APPROVE"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    RETIRE = "RETIRE"


# ─── MaterialCategory ─────────────────────────────────

class AcceptancePolicy(str, Enum):
    ACCEPTED_WITH_LIMIT = "ACCEPTED_WITH_LIMIT"
    REJECTED_ALWAYS = "REJECTED_ALWAYS"


class CompatibilityClass(str, Enum):
    FLAMMABLE = "FLAMMABLE"
    CORROSIVE_ACID = "CORROSIVE_ACID"
    CORROSIVE_BASE = "CORROSIVE_BASE"
    OXIDIZER = "OXIDIZER"
    TOXIC = "TOXIC"
    AEROSOL = "AEROSOL"
    UNIVERSAL_WASTE = "UNIVERSAL_WASTE"


# ─── Resident ─────────────────────────────────────────

class EligibilityStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE_OUT_OF_JURISDICTION = "INELIGIBLE_OUT_OF_JURISDICTION"
    SUSPENDED = "SUSPENDED"


class EligibilityAction(str, Enum):
    VERIFY = "VERIFY"
    REINSTATE = "REINSTATE"


# ─── CollectionEvent ──────────────────────────────────

class LifecycleStatus(str, Enum):
    PLANNED = "PLANNED"
    SITE_CONFIRMED = "SITE_CONFIRMED"
    OPEN_FOR_REGISTRATION = "OPEN_FOR_REGISTRATION"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class ContainmentStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"
    REMEDIATED = "REMEDIATED"


class EventAction(str, Enum):
    CONFIRM_SITE = "CONFIRM_SITE"
    OPEN_REGISTRATION = "OPEN_REGISTRATION"
    START = "START"
    CLOSE = "CLOSE"
    RECONCILE = "RECONCILE"
    CANCEL = "CANCEL"


class FindingOrigin(str, Enum):
    SITE = "SITE"
    EVENT = "EVENT"


# ─── Staffer / LaneAssignment ─────────────────────────

class StafferRoleCode(str, Enum):
    TRAFFIC = "TRAFFIC"
    UNLOAD = "UNLOAD"
    CHEMIST = "CHEMIST"
    SUPERVISOR = "SUPERVISOR"


class StafferStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class LaneAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


# ─── Appointment ──────────────────────────────────────

class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CHECKED_IN = "CHECKED_IN"
    UNLOADING = "UNLOADING"
    COMPLETED = "COMPLETED"
    REFERRED_OUT = "REFERRED_OUT"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class WaitlistReason(str, Enum):
    CAPACITY = "CAPACITY"
    CONTAINMENT_DEFICIENCY = "CONTAINMENT_DEFICIENCY"


class CancelReason(str, Enum):
    RESIDENT_REQUEST = "RESIDENT_REQUEST"
    SUPERSEDED = "SUPERSEDED"
    RESIDENT_SUSPENDED = "RESIDENT_SUSPENDED"
    EVENT_CANCELLED = "EVENT_CANCELLED"


class WasteOrigin(str, Enum):
    HOUSEHOLD = "HOUSEHOLD"
    BUSINESS = "BUSINESS"


class AppointmentAction(str, Enum):
    CONFIRM = "CONFIRM"
    WAITLIST = "WAITLIST"
    PROMOTE = "PROMOTE"
    CANCEL = "CANCEL"
    CHECK_IN = "CHECK_IN"
    START_UNLOAD = "START_UNLOAD"
    COMPLETE_UNLOAD = "COMPLETE_UNLOAD"
    REFER_BUSINESS = "REFER_BUSINESS"
    NO_SHOW = "NO_SHOW"


# ─── DropoffLine ──────────────────────────────────────

class Disposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED_PROHIBITED = "REJECTED_PROHIBITED"
    REJECTED_OVER_ANNUAL_LIMIT = "REJECTED_OVER_ANNUAL_LIMIT"
    REJECTED_OVER_EVENT_LIMIT = "REJECTED_OVER_EVENT_LIMIT"
    REFERRED_BUSINESS = "REFERRED_BUSINESS"


class RejectionReasonCode(str, Enum):
    PROHIBITED_MATERIAL = "PROHIBITED_MATERIAL"
    ANNUAL_LIMIT = "ANNUAL_LIMIT"
    EVENT_LIMIT = "EVENT_LIMIT"
    BUSINESS_GENERATOR = "BUSINESS_GENERATOR"


# ─── PackedContainer / Manifest ───────────────────────

class ContainerStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    MANIFESTED = "MANIFESTED"
    SHIPPED = "SHIPPED"
    DISPOSED = "DISPOSED"


class ContainerAction(str, Enum):
    SEAL = "SEAL"
    UNSEAL = "UNSEAL"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    DISCREPANCY = "DISCREPANCY"
    VOIDED = "VOIDED"


class ManifestAction(str, Enum):
    SIGN = "SIGN"
    SHIP = "SHIP"
    RECEIVE = "RECEIVE"
    REJECT = "REJECT"
    REOPEN = "REOPEN"


# ─── Entity shapes ────────────────────────────────────

class Program(TypedDict):
    id: str
    name: str
    fiscal_year: int
    budget_cents: int
    cost_per_participant_ceiling_cents: int
    staff_hourly_rate_cents: int
    eligible_jurisdiction_codes: List[str]
    posture: str
    posture_override: str
    posture_override_expires_utc: Optional[str]
    budget_encumbered_cents: int
    budget_in_transit_cents: int
    budget_spent_cents: int
    open_containment_deficiency_count: int
    budget_alert_count: int
    participant_count_ytd: int
    tonnage_ytd_kg: float
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    program_id: str
    replaces_site_id: Optional[str]
    name: str
    address: str
    impervious_surface: bool
    secondary_containment_liters: int
    storm_drain_distance_m: float
    lane_count: int
    status: str
    approved_by_user_id: Optional[str]
    last_inspection_result: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialCategory(TypedDict):
    id: str
    program_id: str
    code: str
    display_name: str
    acceptance_policy: str
    compatibility_class: str
    dot_hazard_class: str
    max_kg_per_resident_per_event: float
    max_kg_per_resident_per_year: float
    disposal_rate_cents_per_kg: int
    business_referral_program_code: str
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    program_id: str
    full_name: str
    street_address: str
    claimed_jurisdiction_code: str
    eligibility_status: str
    verified_jurisdiction_code: Optional[str]
    annual_quantity_reserved_kg: float
    annual_quantity_settled_kg: float
    no_show_strike_count: int
    completed_visit_count: int
    created_at: str
    updated_at: str
    version: int


class CollectionEvent(TypedDict):
    id: str
    program_id: str
    site_id: str
    window_start_utc: str
    window_end_utc: str
    min_viable_registrations: int
    event_date: str
    window_duration_hours: float
    lifecycle_status: str
    containment_status: str
    containment_findings: List[dict]
    open_lane_count: int
    certified_staff_hours: float
    staffing_cost_cents: int
    slot_capacity: int
    reserved_slot_count: int
    participant_count: int
    accepted_tonnage_kg: float
    rejected_tonnage_kg: float
    tonnage_reported_kg: float
    projected_cost_per_participant_cents: int
    discrepancy_container_count: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Staffer(TypedDict):
    id: str
    program_id: str
    full_name: str
    role_code: str
    hazwoper_expires_on: str
    status: str
    assigned_hours: float
    created_at: str
    updated_at: str
    version: int


class LaneAssignment(TypedDict):
    id: str
    event_id: str
    staffer_id: str
    lane_number: int
    start_utc: str
    end_utc: str
    duration_hours: float
    status: str
    released_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    event_id: str
    resident_id: str
    slot_start_utc: str
    waste_origin: str
    declared_total_kg: float
    declared_category_ids: List[str]
    vehicle_count: int
    status: str
    waitlist_reason: Optional[str]
    cancel_reason: Optional[str]
    referral_program_code: Optional[str]
    referral_packet_code: Optional[str]
    queue_seq: int
    reserved_kg: float
    settled_kg: float
    check_in_utc: Optional[str]
    unload_complete_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DropoffLine(TypedDict):
    id: str
    appointment_id: str
    material_category_id: str
    container_id: Optional[str]
    declared_kg: float
    net_weight_kg: float
    disposition: str
    rejection_reason_code: Optional[str]
    estimated_disposal_cost_cents: int
    screened_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class PackedContainer(TypedDict):
    id: str
    event_id: str
    manifest_id: Optional[str]
    container_code: str
    compatibility_class: str
    capacity_kg: float
    status: str
    line_count: int
    net_weight_kg: float
    estimated_disposal_cost_cents: int
    sealed_by_user_id: Optional[str]
    discrepancy_flag: bool
    created_at: str
    updated_at: str
    version: int


class Manifest(TypedDict):
    id: str
    event_id: str
    manifest_tracking_number: str
    tsdf_epa_id: str
    status: str
    container_ids: List[str]
    net_weight_kg: float
    estimated_disposal_cost_cents: int
    blended_rate_cents_per_kg: float
    invoiced_disposal_cost_cents: int
    prepared_by_user_id: str
    signed_by_user_id: Optional[str]
    signed_at_utc: Optional[str]
    discrepancy_code: Optional[str]
    superseded_by_manifest_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
