"""TypedDicts and enum value sets for the Child Care Licensing Compliance API.

Every resource carries a server-minted ``id`` and a ``created_at``; almost every
resource additionally carries ``updated_at`` and ``version``.  The one exception
is ``ChecklistItem``, which is immutable configuration and carries only ``id``
and ``created_at`` (PRD §2.5).
"""

from typing import List, Optional, TypedDict


# ─── Role names (PRD §2.1) ─────────────────────────────────────────────
ROLE_AGENCY_ADMIN = "AgencyAdmin"
ROLE_APPLICANT = "Applicant"
ROLE_LICENSING_INSPECTOR = "LicensingInspector"
ROLE_COMPLAINT_INTAKE_SPECIALIST = "ComplaintIntakeSpecialist"
ROLE_COMPLAINT_INVESTIGATOR = "ComplaintInvestigator"
ROLE_LICENSING_SUPERVISOR = "LicensingSupervisor"
ROLE_BACKGROUND_CHECK_UNIT = "BackgroundCheckUnit"
ROLE_PUBLIC_PORTAL_READER = "PublicPortalReader"

ALL_ROLES = [
    ROLE_AGENCY_ADMIN,
    ROLE_APPLICANT,
    ROLE_LICENSING_INSPECTOR,
    ROLE_COMPLAINT_INTAKE_SPECIALIST,
    ROLE_COMPLAINT_INVESTIGATOR,
    ROLE_LICENSING_SUPERVISOR,
    ROLE_BACKGROUND_CHECK_UNIT,
    ROLE_PUBLIC_PORTAL_READER,
]

# ─── Enum value sets ───────────────────────────────────────────────────
AGE_GROUPS = ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"]
PROGRAM_TYPES = ["CENTER", "GROUP_HOME", "FAMILY_HOME"]
APPLICATION_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "CHECKS_CLEARED",
    "INITIAL_INSPECTION_PASSED",
    "LICENSED",
    "DENIED",
]
LICENSE_STATUSES = ["NONE", "PROVISIONAL", "FULL", "PROBATION", "SUSPENDED", "REVOKED"]
SEVERITIES = ["CRITICAL", "SERIOUS", "MODERATE", "MINOR"]
CHECKLIST_CATEGORIES = [
    "SUPERVISION",
    "SANITATION",
    "NUTRITION",
    "FIRE_SAFETY",
    "MEDICATION",
    "BACKGROUND_CHECK",
    "RATIO",
    "FACILITY",
    "RECORDS",
]
MEMBER_TYPES = ["DIRECTOR", "LEAD_TEACHER", "ASSISTANT", "VOLUNTEER", "HOUSEHOLD_MEMBER"]
SUPERVISING_MEMBER_TYPES = ["DIRECTOR", "LEAD_TEACHER", "ASSISTANT"]
LEAD_ELIGIBLE_MEMBER_TYPES = ["DIRECTOR", "LEAD_TEACHER"]
CLEARANCE_STATUSES = ["PENDING", "CLEARED", "BARRED", "WAIVER_PENDING"]
OFFENSE_TIERS = ["NONE", "TIER_1_PERMANENT", "TIER_2_FIVE_YEAR", "TIER_3_WAIVABLE"]
CHECK_TYPES = [
    "FBI_FINGERPRINT",
    "CHILD_ABUSE_REGISTRY",
    "STATE_CRIMINAL",
    "SEX_OFFENDER_REGISTRY",
]
CHECK_STATUSES = ["SUBMITTED", "CLEARED", "DISQUALIFIED", "WAIVER_PENDING", "WAIVED"]
INSPECTOR_STATUSES = ["ACTIVE", "ON_LEAVE"]
INSPECTION_TYPES = ["INITIAL", "ANNUAL", "COMPLAINT", "FOLLOW_UP", "AMENDMENT_PRE_MOVE"]
INSPECTION_STATUSES = [
    "SCHEDULED",
    "IN_PROGRESS",
    "PENDING_REVIEW",
    "FINALIZED",
    "VOIDED",
]
INSPECTION_OUTCOMES = ["PASS", "CONDITIONAL_PASS", "FAIL"]
VIOLATION_STATUSES = [
    "CITED",
    "CORRECTION_PENDING",
    "VERIFIED_CORRECTED",
    "UNCORRECTED",
    "VACATED",
]
VIOLATION_DISPOSITIONS = ["VERIFIED_CORRECTED", "UNCORRECTED", "VACATED"]
OPEN_VIOLATION_STATUSES = ["CITED", "CORRECTION_PENDING", "UNCORRECTED"]
INTAKE_CHANNELS = [
    "PHONE",
    "WEB",
    "MAIL",
    "WALK_IN",
    "MANDATED_REPORTER",
    "AGENCY_INCIDENT",
]
ALLEGATION_CATEGORIES = [
    "ABUSE",
    "SUPERVISION",
    "RATIO",
    "BACKGROUND",
    "FACILITY",
    "NUTRITION",
    "RECORDS",
]
COMPLAINT_STATUSES = [
    "RECEIVED",
    "SCREENED_IN",
    "SCREENED_OUT",
    "UNDER_INVESTIGATION",
    "DETERMINED",
    "CLOSED",
]
COMPLAINT_PRIORITIES = ["P1", "P2", "P3"]
DETERMINATIONS = ["SUBSTANTIATED", "UNSUBSTANTIATED", "INCONCLUSIVE"]
TIMELINESS_FLAGS = ["ON_TIME", "LATE"]
CAP_STATUSES = [
    "SUBMITTED",
    "APPROVED",
    "REJECTED",
    "COMPLETED",
    "FAILED",
    "SUPERSEDED",
]
ACTION_TYPES = ["WARNING", "PROBATION", "SUSPENSION", "REVOCATION"]
ENFORCEMENT_STATUSES = [
    "PROPOSED",
    "ISSUED",
    "EFFECTIVE",
    "APPEALED",
    "UPHELD",
    "VACATED",
    "WITHDRAWN",
]
APPEAL_DECISIONS = ["UPHELD", "VACATED"]
AMENDMENT_TYPES = [
    "CAPACITY_INCREASE",
    "CAPACITY_DECREASE",
    "SITE_MOVE",
    "AGE_GROUP_ADD",
    "DIRECTOR_CHANGE",
]
AMENDMENT_STATUSES = [
    "SUBMITTED",
    "PRE_INSPECTION_REQUIRED",
    "APPROVED",
    "DENIED",
    "WITHDRAWN",
    "SUPERSEDED",
]
INCIDENT_TYPES = [
    "FATALITY",
    "MISSING_CHILD",
    "SERIOUS_INJURY",
    "MEDICATION_ERROR",
    "COMMUNICABLE_DISEASE",
]
INCIDENT_STATUSES = ["REPORTED", "UNDER_REVIEW", "INVESTIGATION_OPENED", "CLOSED"]
REPORTING_TIMELINESS = ["TIMELY", "LATE_REPORT"]
POSTING_STATUSES = ["PENDING_REDACTION", "POSTED", "CORRECTED", "WITHDRAWN"]
ENFORCEMENT_BANNERS = ["NONE", "WARNING", "PROBATION", "SUSPENSION", "REVOCATION"]
RISK_TIERS = ["LOW", "MODERATE", "HIGH", "SEVERE"]


# ─── Common field groups (PRD §2.5) ────────────────────────────────────
class VersionedRecord(TypedDict):
    """id / created_at / updated_at / version — carried by every resource
    except the immutable checklist catalog."""

    id: str
    created_at: str
    updated_at: str
    version: int


# ─── Entities ──────────────────────────────────────────────────────────
class Provider(VersionedRecord):
    legal_name: str
    county_code: str
    site_address: str
    program_type: str
    requested_capacity: int
    capacity_ceiling: int
    licensed_capacity: int
    suspended_capacity: int
    application_status: str
    license_status: str
    license_number: Optional[str]
    licensed_at: Optional[str]
    provisional_started_at: Optional[str]
    open_violation_points: float
    resolved_violation_points: float
    lifetime_violation_points: float
    critical_open_count: int
    critical_violation_count_24mo: int
    substantiated_complaint_count_24mo: int
    inconclusive_complaint_count_24mo: int
    risk_score: float
    risk_tier: str
    current_ladder_step: int
    probation_cycle_count: int
    clearance_complete: bool
    decision_reason: Optional[str]


class Inspector(VersionedRecord):
    full_name: str
    county_code: str
    certified_age_groups: List[str]
    max_daily_visits: int
    status: str
    scheduled_visit_count: int


class ChecklistItem(TypedDict):
    """Immutable configuration: only ``id`` and ``created_at`` — it has neither
    ``updated_at`` nor ``version`` (PRD §2.5)."""

    id: str
    created_at: str
    code: str
    title: str
    category: str
    default_severity: str
    age_groups_applicable: List[str]
    infant_sensitive: bool


class StaffMember(VersionedRecord):
    provider_id: str
    full_name: str
    member_type: str
    role_title: Optional[str]
    date_of_birth: str
    qualified_age_groups: List[str]
    clearance_status: str
    supervision_eligible: bool
    barred_offense_tier: str


class BackgroundCheck(VersionedRecord):
    staff_member_id: str
    check_type: str
    status: str
    disqualifying_offense_tier: str
    submitted_at: str
    decided_at: Optional[str]
    expires_at: Optional[str]
    waiver_requested_at: Optional[str]
    waiver_rationale: Optional[str]
    waiver_decided_at: Optional[str]


class AgeGroupRoster(VersionedRecord):
    provider_id: str
    age_group: str
    requested_group_size: int
    approved_group_size: int
    enrolled_count: int
    staff_assigned_count: int
    lead_staff_member_id: Optional[str]
    required_staff_count: int
    ratio_compliant: bool
    group_size_compliant: bool
    supervision_compliant: bool
    last_verified_at: Optional[str]


class Inspection(VersionedRecord):
    provider_id: str
    inspector_id: str
    complaint_id: Optional[str]
    inspection_type: str
    status: str
    scheduled_for: str
    duration_minutes: int
    visit_window_end: str
    started_at: Optional[str]
    submitted_at: Optional[str]
    finalized_at: Optional[str]
    target_age_groups: List[str]
    age_groups_observed: Optional[List[str]]
    outcome: Optional[str]
    preliminary_compliance_score: Optional[float]
    final_compliance_score: Optional[float]
    raw_deduction_points: Optional[float]
    violation_count: int
    cap_required: bool
    reopen_count: int


class Violation(VersionedRecord):
    inspection_id: str
    checklist_item_id: str
    repeat_of_violation_id: Optional[str]
    primary_age_group: str
    severity_override: Optional[str]
    severity: str
    repeat_chain_depth: int
    infant_exposure: bool
    assessed_points: float
    status: str
    correction_due_date: Optional[str]
    narrative: str
    corrected_at: Optional[str]
    vacated_reason: Optional[str]
    auto_generated: bool


class Complaint(VersionedRecord):
    provider_id: str
    assigned_investigator_id: Optional[str]
    intake_channel: str
    allegation_category: str
    alleged_serious_harm: bool
    affected_age_group: str
    complainant_name: Optional[str]
    anonymous: bool
    narrative: str
    priority: str
    status: str
    received_at: str
    screened_at: Optional[str]
    investigation_due_at: str
    determination: Optional[str]
    determined_at: Optional[str]
    timeliness_flag: Optional[str]
    closure_note: Optional[str]


class CorrectiveActionPlan(VersionedRecord):
    provider_id: str
    inspection_id: str
    violation_ids: List[str]
    narrative: str
    proposed_completion_date: str
    status: str
    review_cycle_count: int
    submitted_at: str
    reviewed_at: Optional[str]
    approved_at: Optional[str]
    completed_at: Optional[str]
    due_at: str
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]


class EnforcementAction(VersionedRecord):
    provider_id: str
    source_inspection_id: Optional[str]
    requested_action_type: Optional[str]
    action_type: str
    ladder_step: int
    status: str
    basis_points: float
    fine_amount_cents: int
    proposed_at: str
    issued_at: Optional[str]
    effective_at: Optional[str]
    appeal_deadline_at: Optional[str]
    appealed_at: Optional[str]
    appeal_note: Optional[str]
    resolved_at: Optional[str]
    appeal_decision: Optional[str]
    issued_by_user_id: Optional[str]
    capacity_held_slots: int
    rationale: Optional[str]


class LicenseAmendment(VersionedRecord):
    provider_id: str
    pre_move_inspection_id: Optional[str]
    new_director_staff_member_id: Optional[str]
    amendment_type: str
    requested_capacity: Optional[int]
    new_site_address: Optional[str]
    new_age_group: Optional[str]
    new_group_size: Optional[int]
    requires_inspection: bool
    status: str
    submitted_at: str
    decided_at: Optional[str]
    decision_rationale: Optional[str]
    effective_capacity_delta: int


class SeriousIncidentReport(VersionedRecord):
    provider_id: str
    generated_complaint_id: Optional[str]
    incident_type: str
    occurred_at: str
    reported_at: str
    affected_child_age_group: str
    narrative: str
    reporting_deadline_at: str
    reporting_timeliness: str
    late_report_violation_created: bool
    status: str
    reviewed_at: Optional[str]
    closed_at: Optional[str]
    agency_note: Optional[str]


class PublicReportPosting(VersionedRecord):
    inspection_id: str
    provider_id: str
    posting_status: str
    redaction_complete: bool
    consumer_summary: str
    display_score: Optional[float]
    enforcement_banner: str
    posted_at: Optional[str]
    expires_at: Optional[str]
    corrected_at: Optional[str]
    withdrawn_at: Optional[str]
    revision_note: Optional[str]
    correction_count: int
