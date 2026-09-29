"""Typed shapes and status enumerations for the Neighborhood Swim Club API.

Every field name and every enum member is transcribed from PRD.md. The
``CommonFields`` base carries the four attributes PRD §2.4 declares for all
sixteen entities: "``Season``, ``MembershipCategory``, ``Household``,
``WaitlistEntry``, ``Membership``, ``GuestVisit``, ``Lifeguard``,
``Certification``, ``GuardShift``, ``SwimTeamRegistration``, ``Meet``,
``VolunteerAssignment``, ``PartyReservation``, ``InspectionFinding``,
``ConductCase`` and ``CapitalProject`` all expose ``id``, ``created_at``,
``updated_at`` and ``version``."
"""

from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────

class Role:
    MEMBER = "Member"
    MEMBERSHIP_CHAIR = "MembershipChair"
    POOL_MANAGER = "PoolManager"
    SWIM_TEAM_COACH = "SwimTeamCoach"
    HEALTH_INSPECTOR = "HealthInspector"
    TREASURER = "Treasurer"
    BOARD_PRESIDENT = "BoardPresident"
    SYSTEM_OPERATOR = "SystemOperator"


ALL_ROLES = [
    Role.MEMBER,
    Role.MEMBERSHIP_CHAIR,
    Role.POOL_MANAGER,
    Role.SWIM_TEAM_COACH,
    Role.HEALTH_INSPECTOR,
    Role.TREASURER,
    Role.BOARD_PRESIDENT,
    Role.SYSTEM_OPERATOR,
]


# ─── Status / enum vocabularies ───────────────────────

class SeasonStatus:
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FacilityPosture:
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class ProrationBasis:
    CALENDAR_DAY = "CALENDAR_DAY"
    SWIM_WEEK = "SWIM_WEEK"


class GuestSettlementPolicy:
    PASS_FIRST = "PASS_FIRST"
    FEE_FIRST_ON_WEEKEND = "FEE_FIRST_ON_WEEKEND"


class CategoryCode:
    FAMILY = "FAMILY"
    COUPLE = "COUPLE"
    SINGLE = "SINGLE"
    SENIOR = "SENIOR"
    SWIM_TEAM_ONLY = "SWIM_TEAM_ONLY"


class Residency:
    IN_DISTRICT = "IN_DISTRICT"
    OUT_OF_DISTRICT = "OUT_OF_DISTRICT"


class HouseholdStanding:
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    EXPELLED = "EXPELLED"


class BondStatus:
    NONE = "NONE"
    INSTALLMENTS = "INSTALLMENTS"
    PAID = "PAID"
    TRANSFERRED = "TRANSFERRED"


class HouseholdPaymentAllocation:
    GUEST_FEES = "GUEST_FEES"
    PARTY_CHARGES = "PARTY_CHARGES"
    BOND = "BOND"


class PriorityTier:
    LEGACY = "LEGACY"
    SIBLING = "SIBLING"
    STANDARD = "STANDARD"


class WaitlistStatus:
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class WaitlistDecision:
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"
    WITHDRAW = "WITHDRAW"


class BondPaymentPlan:
    FULL = "FULL"
    INSTALLMENTS = "INSTALLMENTS"
    TRANSFERRED = "TRANSFERRED"


class DuesStatus:
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    DELINQUENT = "DELINQUENT"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class AccessStatus:
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class MembershipPaymentAllocation:
    DUES = "DUES"
    BOND = "BOND"


class GuestVisitStatus:
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class EmploymentStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CertType:
    LIFEGUARD = "LIFEGUARD"
    CPR_AED = "CPR_AED"
    WSI = "WSI"
    POOL_OPERATOR = "POOL_OPERATOR"


class CertificationStatus:
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class ShiftRole:
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    SUPERVISOR = "SUPERVISOR"


class GuardShiftStatus:
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    CANCELLED_BY_CLOSURE = "CANCELLED_BY_CLOSURE"


class Squad:
    MINI = "MINI"
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"


class RegistrationStatus:
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    WITHDRAWN = "WITHDRAWN"
    REVOKED = "REVOKED"
    COMPLETED = "COMPLETED"


class MeetStatus:
    SCHEDULED = "SCHEDULED"
    STAFFED = "STAFFED"
    UNDERSTAFFED = "UNDERSTAFFED"
    HOSTED = "HOSTED"
    CANCELLED = "CANCELLED"


class JobCode:
    TIMER = "TIMER"
    STARTER = "STARTER"
    CONCESSIONS = "CONCESSIONS"
    MARSHAL = "MARSHAL"
    SCORER = "SCORER"


class AssignmentStatus:
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    RELEASED = "RELEASED"


class Zone:
    PAVILION = "PAVILION"
    SHALLOW_END = "SHALLOW_END"
    WHOLE_FACILITY = "WHOLE_FACILITY"


class ReservationStatus:
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED_BY_HOST = "CANCELLED_BY_HOST"
    CANCELLED_BY_CLOSURE = "CANCELLED_BY_CLOSURE"
    CANCELLED_BY_SUSPENSION = "CANCELLED_BY_SUSPENSION"


class FindingSeverity:
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class FindingStatus:
    OPEN = "OPEN"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    REOPENED = "REOPENED"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"


class CaseSeverity:
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class CaseStatus:
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SANCTIONED = "SANCTIONED"
    APPEALED = "APPEALED"
    DISMISSED = "DISMISSED"
    CLOSED = "CLOSED"


class SanctionType:
    WARNING = "WARNING"
    PROBATION = "PROBATION"
    SUSPENSION = "SUSPENSION"
    EXPULSION = "EXPULSION"


class ProjectKind:
    POOL_RESURFACING = "POOL_RESURFACING"
    PUMP_REPLACEMENT = "PUMP_REPLACEMENT"


class ProjectStatus:
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FUNDED = "FUNDED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ─── Entity shapes ────────────────────────────────────

class CommonFields(TypedDict):
    """PRD §2.4: every entity exposes these four. There are no exceptions."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Season(CommonFields):
    year: int
    open_date: str
    close_date: str
    dues_due_date: str
    baseline_bather_load: int
    bather_load_capacity: int
    proration_basis: str
    guest_settlement_policy: str
    status: str
    facility_posture: str
    open_critical_finding_count: int
    open_major_finding_count: int
    closure_started_at: Optional[str]
    reserve_contributions_cents: int
    reserve_unallocated_cents: int


class MembershipCategory(CommonFields):
    code: str
    label: str
    bond_cents: int
    initiation_fee_cents: int
    seasonal_dues_cents: int
    guest_pass_allotment: int
    max_household_size: int
    volunteer_credits_required: int
    waitlist_required: bool
    proration_allowed: bool
    party_privileges: bool


class Household(CommonFields):
    primary_contact_name: str
    address_line: str
    residency: str
    member_count: int
    prior_member: bool
    transferred_from_household_id: Optional[str]
    standing: str
    conduct_points: int
    bond_status: str
    bond_paid_cents: int
    guest_pass_allotment_granted: int
    guest_passes_consumed: int
    guest_pass_balance: int
    guest_fee_owed_cents: int
    party_charges_owed_cents: int
    account_credit_cents: int


class WaitlistEntry(CommonFields):
    household_id: str
    membership_category_id: str
    priority_tier: str
    priority_tier_rank: int
    status: str
    deferral_count: int
    queue_key_at: str
    offered_at: Optional[str]
    offer_expires_at: Optional[str]
    requeued_at: Optional[str]


class Membership(CommonFields):
    household_id: str
    membership_category_id: str
    season_id: str
    join_date: str
    bond_payment_plan: Optional[str]
    dues_status: str
    access_status: str
    assessed_dues_cents: int
    initiation_fee_cents: int
    bond_installment_cents: int
    swim_team_fee_cents: int
    late_penalty_cents: int
    invoice_total_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    volunteer_buyout_cents: int
    volunteer_credits_required: int
    volunteer_credits_earned: int
    invoiced_at: Optional[str]


class GuestVisit(CommonFields):
    membership_id: str
    sponsor_name: str
    guest_count: int
    visit_start_iso: str
    is_weekend: bool
    settlement_variant: str
    passes_used: int
    fee_charged_cents: int
    status: str
    voided_at: Optional[str]


class Lifeguard(CommonFields):
    full_name: str
    hire_date: str
    employment_status: str
    has_valid_lifeguard_cert: bool
    has_valid_cpr_cert: bool
    scheduled_hours: float


class Certification(CommonFields):
    lifeguard_id: str
    cert_type: str
    issued_on: str
    expires_on: str
    status: str
    revoked_reason: Optional[str]


class GuardShift(CommonFields):
    lifeguard_id: str
    season_id: str
    shift_role: str
    start_iso: str
    end_iso: str
    duration_hours: float
    counts_toward_ratio: bool
    status: str


class SwimTeamRegistration(CommonFields):
    membership_id: str
    season_id: str
    swimmer_name: str
    swimmer_birthdate: str
    squad: str
    squad_seq: int
    assessed_fee_cents: int
    status: str


class Meet(CommonFields):
    season_id: str
    name: str
    start_iso: str
    end_iso: str
    expected_swimmers: int
    volunteer_slots_required: int
    volunteer_slots_filled: int
    roster_closed_at: Optional[str]
    understaffed_penalty_cents: int
    status: str


class VolunteerAssignment(CommonFields):
    meet_id: str
    swim_team_registration_id: str
    job_code: str
    credit_value: int
    status: str


class PartyReservation(CommonFields):
    membership_id: str
    zone: str
    start_iso: str
    end_iso: str
    guest_count: int
    host_party_size: int
    projected_bather_load: int
    required_guard_count: int
    duration_hours_ceil: int
    lifeguard_surcharge_cents: int
    base_facility_fee_cents: int
    guest_overage_fee_cents: int
    subtotal_cents: int
    member_discount_cents: int
    total_charge_cents: int
    refunded_cents: int
    status: str


class InspectionFinding(CommonFields):
    season_id: str
    inspected_on: str
    inspector_name: str
    finding_code: str
    severity: str
    narrative: str
    status: str
    recorded_by_user_id: str
    reopen_count: int
    remediation_note: Optional[str]
    remediation_submitted_at: Optional[str]
    verified_by_user_id: Optional[str]


class ConductCase(CommonFields):
    household_id: str
    subject_name: str
    severity: str
    narrative: str
    status: str
    reported_by_user_id: str
    decided_by_user_id: Optional[str]
    sanction_type: Optional[str]
    sanctioned_at: Optional[str]
    points_assessed: int
    appeal_count: int


class CapitalProject(CommonFields):
    funding_season_id: str
    project_kind: str
    title: str
    budget_cents: int
    funded_cents: int
    status: str
    requested_by_user_id: str
    approved_by_user_id: Optional[str]


class StaffingWindow(TypedDict):
    """PRD §3.8: the computed read "returns an object rather than a stored entity"."""

    season_id: str
    at_iso: str
    bather_load: int
    required_guard_count: int
    scheduled_guard_count: int
    compliant: bool


ALL_ENTITY_NAMES: List[str] = [
    "Season",
    "MembershipCategory",
    "Household",
    "WaitlistEntry",
    "Membership",
    "GuestVisit",
    "Lifeguard",
    "Certification",
    "GuardShift",
    "SwimTeamRegistration",
    "Meet",
    "VolunteerAssignment",
    "PartyReservation",
    "InspectionFinding",
    "ConductCase",
    "CapitalProject",
]
