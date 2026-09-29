"""Domain types: entity TypedDicts, status enums and the role enum.

Field names match the PRD exactly.  Entities carrying the common audit fields
expose id, created_at, updated_at and version; the one append-only entity
(ThemedRoom) exposes only id and created_at, because the PRD states it carries
no version and is never updated.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD 2.1) ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    VENUE_OPS_MANAGER = "VenueOpsManager"
    LICENSING_MANAGER = "LicensingManager"
    LICENSOR_REP = "LicensorRep"
    EXPERIENCE_PRODUCER = "ExperienceProducer"
    SAFETY_OFFICER = "SafetyOfficer"
    GUEST_SERVICES_AGENT = "GuestServicesAgent"
    GUEST = "Guest"


# ─── Status enums ───────────────────────────────────────────────────────────

class PopupVenueStatus(str, Enum):
    DRAFT = "DRAFT"
    PERMIT_UNDER_REVIEW = "PERMIT_UNDER_REVIEW"
    PERMIT_CONDITIONS = "PERMIT_CONDITIONS"
    PERMIT_ISSUED = "PERMIT_ISSUED"
    PERMIT_DENIED = "PERMIT_DENIED"
    LEASE_ACTIVE = "LEASE_ACTIVE"
    LEASE_ENDED = "LEASE_ENDED"


class LicenseAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class CreativeSubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    EXTENDED = "EXTENDED"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class ClearanceStatus(str, Enum):
    UNCLEARED = "UNCLEARED"
    CLEARED = "CLEARED"
    SUSPENDED = "SUSPENDED"


class TimedEntrySlotStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SOLD_OUT = "SOLD_OUT"
    HELD_FOR_BUYOUT = "HELD_FOR_BUYOUT"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    CLOSED_OUT = "CLOSED_OUT"


class GuestAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"


class TicketOrderStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    NO_SHOW = "NO_SHOW"
    REFUND_DUE = "REFUND_DUE"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class StaffMemberStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    TRAINING = "TRAINING"
    CLEARED = "CLEARED"
    SUSPENDED = "SUSPENDED"
    RELEASED = "RELEASED"


class StaffShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class SafetyInspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class InspectionOutcome(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class BuildKitStatus(str, Enum):
    READY = "READY"
    DEPLOYED = "DEPLOYED"
    IN_TRANSIT = "IN_TRANSIT"
    REFURB_REQUIRED = "REFURB_REQUIRED"
    RETIRED = "RETIRED"


class LocalizationStatus(str, Enum):
    PENDING = "PENDING"
    LOCALIZED = "LOCALIZED"


class RoyaltyStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_TRUEUP = "UNDER_TRUEUP"
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"
    SUPERSEDED = "SUPERSEDED"


# ─── Value enums ────────────────────────────────────────────────────────────

class ApprovalScope(str, Enum):
    CREATIVE_EXECUTION = "CREATIVE_EXECUTION"
    MERCHANDISE = "MERCHANDISE"
    MARKETING = "MARKETING"


class PricingTier(str, Enum):
    OFFPEAK = "OFFPEAK"
    STANDARD = "STANDARD"
    PEAK = "PEAK"
    PREMIUM = "PREMIUM"


class LoyaltyTier(str, Enum):
    VISITOR = "VISITOR"
    MEMBER = "MEMBER"
    PATRON = "PATRON"


class OrderType(str, Enum):
    SINGLE = "SINGLE"
    GROUP = "GROUP"
    PRIVATE_BUYOUT = "PRIVATE_BUYOUT"


class Accommodation(str, Enum):
    QUIET_ROUTE = "QUIET_ROUTE"
    WHEELCHAIR = "WHEELCHAIR"
    ASL_INTERPRETER = "ASL_INTERPRETER"
    LOW_STIM_HOURS = "LOW_STIM_HOURS"


class StaffRole(str, Enum):
    PERFORMER = "PERFORMER"
    AMBASSADOR = "AMBASSADOR"
    TECHNICIAN = "TECHNICIAN"


class Certification(str, Enum):
    SCRIPTED_INTERACTION = "SCRIPTED_INTERACTION"
    SENSORY_DEESCALATION = "SENSORY_DEESCALATION"
    ADA_ASSIST = "ADA_ASSIST"
    EVACUATION_MARSHAL = "EVACUATION_MARSHAL"
    RIGGING = "RIGGING"
    ELECTRICAL = "ELECTRICAL"


class Station(str, Enum):
    FLOOR = "FLOOR"
    BOOTH = "BOOTH"
    RIGGING = "RIGGING"
    ENTRY = "ENTRY"


class InspectionType(str, Enum):
    EGRESS = "EGRESS"
    CAPACITY = "CAPACITY"
    ACCESSIBILITY = "ACCESSIBILITY"
    SENSORY = "SENSORY"


class Severity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


# ─── Entity shapes ──────────────────────────────────────────────────────────
# Entities below carry the common audit fields: id, created_at, updated_at,
# version.  ThemedRoom is the sole exception and is declared last.

class PopupVenue(TypedDict):
    id: str
    city_code: str
    site_name: str
    lease_start_date: str
    lease_end_date: str
    lease_extension_option_days: int
    lease_extension_days_consumed: int
    base_monthly_rent_cents: int
    buildout_allowance_cents: int
    kit_reuse_credit_cents: int
    buildout_cap_cents: int
    allowance_drawn_cents: int
    kit_credit_drawn_cents: int
    operator_capex_cents: int
    buildout_spend_cents: int
    requested_occupancy_load: int
    permitted_occupancy_load: int
    egress_width_cm: float
    egress_capacity: int
    sprinklered: bool
    permit_submission_round: int
    permit_conditions_note: Optional[str]
    permit_denial_reason: Optional[str]
    permit_issued_at: Optional[str]
    lease_activated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict):
    id: str
    licensor_name: str
    ip_title: str
    licensor_rep_user_id: str
    royalty_rate_bps: int
    merch_royalty_rate_bps: int
    minimum_guarantee_cents: int
    approval_scopes: List[str]
    territory_city_codes: List[str]
    term_start_date: str
    term_end_date: str
    open_submission_count: int
    approved_submission_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CreativeSubmission(TypedDict):
    id: str
    license_agreement_id: str
    run_id: str
    scope: str
    asset_code: str
    title: str
    submitted_by_user_id: str
    revision_round: int
    change_note: Optional[str]
    decision_note: Optional[str]
    review_started_at: Optional[str]
    resubmitted_at: Optional[str]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    superseded_by_submission_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExperienceRun(TypedDict):
    id: str
    venue_id: str
    license_agreement_id: str
    build_kit_id: str
    run_name: str
    created_by_user_id: str
    scheduled_open_date: str
    scheduled_close_date: str
    base_ticket_price_cents: int
    timed_slot_minutes: int
    max_group_size: int
    effective_capacity: int
    effective_capacity_cap: int
    royalty_statement_count: int
    extension_days_granted: int
    demand_index: float
    demand_index_at_extension: Optional[float]
    opened_at: Optional[str]
    closing_started_at: Optional[str]
    closed_at: Optional[str]
    suspended_at: Optional[str]
    suspending_inspection_id: Optional[str]
    run_status: str
    clearance_status: str
    created_at: str
    updated_at: str
    version: int


class TimedEntrySlot(TypedDict):
    id: str
    run_id: str
    slot_start_utc: str
    slot_end_utc: str
    pricing_tier: str
    base_capacity: int
    released_capacity: int
    held_capacity: int
    sold_capacity: int
    available_capacity: int
    wheelchair_positions: int
    wheelchair_sold: int
    buyout_order_id: Optional[str]
    released_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GuestAccount(TypedDict):
    id: str
    email: str
    display_name: str
    loyalty_tier: str
    accommodation_profile: List[str]
    experience_credit_cents: int
    no_show_strikes: int
    visit_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TicketOrder(TypedDict):
    id: str
    slot_id: str
    run_id: str
    guest_account_id: str
    order_type: str
    party_size: int
    wheelchair_party_count: int
    sensory_accommodations: List[str]
    merch_amount_cents: int
    unit_price_cents: int
    per_guest_after_loyalty_cents: int
    gross_amount_cents: int
    group_discount_cents: int
    companion_waiver_cents: int
    discount_cents: int
    net_amount_cents: int
    net_collected_cents: int
    refunded_cents: int
    credit_issued_cents: int
    refund_pct: float
    checked_in_at: Optional[str]
    refund_settled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    run_id: str
    full_name: str
    staff_role: str
    certifications: List[str]
    incident_count: int
    training_score: int
    completed_rehearsal_count: int
    scheduled_rehearsal_count: int
    cert_coverage_pct: float
    readiness_score_preflight: float
    readiness_score_audit: float
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffShift(TypedDict):
    id: str
    staff_member_id: str
    run_id: str
    themed_room_id: Optional[str]
    shift_start_utc: str
    shift_end_utc: str
    station: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyInspection(TypedDict):
    id: str
    run_id: str
    inspection_type: str
    scheduled_for_utc: str
    measured_egress_width_cm: float
    findings_count: int
    severity: str
    outcome: Optional[str]
    findings_note: Optional[str]
    allowed_occupancy_cap: int
    finalized_by_user_id: Optional[str]
    finalized_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BuildKit(TypedDict):
    id: str
    kit_code: str
    origin_run_id: Optional[str]
    module_count: int
    initial_condition_score: float
    condition_score: float
    reuse_cycle_count: int
    refurb_count: int
    last_city_code: Optional[str]
    localization_language: str
    localization_cost_cents: int
    localization_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    run_id: str
    license_agreement_id: str
    period_start_date: str
    period_end_date: str
    ticket_base_cents: int
    merch_base_cents: int
    provisional_royalty_cents: int
    provisional_royalty_cents_prev: int
    truedown_cents: int
    final_royalty_cents: int
    mg_prorated_cents: int
    minimum_guarantee_shortfall_cents: int
    amount_due_cents: int
    superseded_by_statement_id: Optional[str]
    issued_at: Optional[str]
    settled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# A themed room is an immutable part of a run's design: the PRD gives it no
# version, no status and no update path, so it carries only id and created_at.
class ThemedRoom(TypedDict):
    id: str
    run_id: str
    room_sequence: int
    name: str
    room_occupancy_cap: int
    target_dwell_minutes: int
    min_dwell_minutes: int
    sensory_intensity_level: int
    has_quiet_bypass: bool
    wheelchair_accessible: bool
    throughput_per_slot: int
    created_at: str
