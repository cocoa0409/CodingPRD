"""TypedDict shapes for the twelve SafeSport compliance resource types.

Every resource carries the four common properties described in PRD 2.4 -- a
server-minted ``id``, ``created_at``, ``updated_at`` and an integer ``version``
that starts at 1 and rises by exactly one on every mutation, including a
mutation that arrived as a cascade.
"""

from __future__ import annotations

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    """The four properties present on all twelve resource types."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Club(CommonFields, total=False):
    name: str
    state_code: str
    minor_athlete_program: bool
    roster_size_attested: int
    escrow_balance_cents: int
    total_funded_cents: int
    sanction_status: str
    compliance_posture: str
    compliance_score: Optional[float]
    open_finding_count: int
    critical_open_finding_count: int
    restricted_member_count: int
    active_assignment_count: int


class Member(CommonFields, total=False):
    club_id: str
    full_name: str
    email: str
    role_type: str
    has_minor_athlete_contact: bool
    date_of_birth: str
    jurisdiction_codes: List[str]
    screening_status: str
    membership_status: str
    training_status: str
    contact_eligibility: str
    risk_points: int
    required_tier: str
    screening_expires_at: Optional[str]
    eligible_through: Optional[str]
    last_renewed_at: Optional[str]
    records_retained_through: Optional[str]
    active_assignment_count: int


class ScreeningOrder(CommonFields, total=False):
    member_id: str
    status: str
    tier: str
    jurisdiction_count: int
    expedited: bool
    gross_subtotal_cents: int
    discount_cents: int
    expedite_cents: int
    charged_cents: int
    vendor_disposition: Optional[str]
    disposition: Optional[str]
    rationale: Optional[str]
    returned_at: Optional[str]
    adjudicated_at: Optional[str]
    expires_at: Optional[str]
    void_reason: Optional[str]


class TrainingCourse(CommonFields, total=False):
    code: str
    title: str
    validity_days: int
    delivery_mode: str
    required_for_tiers: List[str]
    pass_score: int


class TrainingAssignment(CommonFields, total=False):
    member_id: str
    course_code: str
    status: str
    assigned_at: str
    due_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    score: Optional[int]
    expires_at: Optional[str]


class CoachAssignment(CommonFields, total=False):
    member_id: str
    club_id: str
    team_name: str
    season_start: str
    season_end: str
    status: str
    activated_at: Optional[str]
    eligibility_snapshot_version: Optional[int]
    suspended_reason: Optional[str]
    electronic_comm_authorized: bool
    electronic_comm_channel_kind: Optional[str]
    parent_copy_required: Optional[bool]


class InvestigatingBody(CommonFields, total=False):
    name: str
    scope_categories: List[str]
    intake_status: str
    max_open_cases: int
    open_case_count: int


class Case(CommonFields, total=False):
    club_id: str
    reported_member_id: str
    allegation_category: str
    reporter_kind: str
    reporter_user_id: str
    narrative: str
    occurred_at: str
    intake_received_at: str
    report_timeliness: str
    status: str
    investigating_body_id: Optional[str]
    routed_at: Optional[str]
    closed_at: Optional[str]
    closure_reason: Optional[str]
    outcome: Optional[str]


class InterimMeasure(CommonFields, total=False):
    case_id: str
    member_id: str
    measure_kind: str
    status: str
    permanence: str
    effective_from: str
    effective_to: Optional[str]
    imposed_by_user_id: str
    converted_by_user_id: Optional[str]
    lifted_at: Optional[str]
    lift_reason: Optional[str]
    rationale: Optional[str]


class ClubAudit(CommonFields, total=False):
    club_id: str
    audit_period_start: str
    audit_period_end: str
    score_variant: str
    status: str
    sampled_member_ids: List[str]
    sampled_member_count: int
    compliant_member_count: Optional[int]
    denominator_count: Optional[int]
    compliance_score: Optional[float]
    sanction_fine_cents: Optional[int]
    finding_total_count: int
    open_finding_count: int
    remediated_finding_count: int
    waived_finding_count: int
    finalized_at: Optional[str]
    closed_at: Optional[str]
    resolution: Optional[str]


class AuditFinding(CommonFields, total=False):
    audit_id: str
    member_id: Optional[str]
    finding_code: str
    severity: str
    is_repeat: bool
    status: str
    fine_cents: Optional[int]
    evidence_note: Optional[str]
    decision_note: Optional[str]


class RoomStay(CommonFields, total=False):
    club_id: str
    occupant_kind: str
    member_id: Optional[str]
    minor_athlete_age: Optional[int]
    trip_label: str
    room_number: str
    check_in: str
    check_out: str
    status: str
    cancel_reason: Optional[str]


class EligibilityProjection(TypedDict, total=False):
    """Shape of the computed eligibility-projection read of PRD 3.5."""

    variant: str
    projected_eligible_through: Optional[str]
    screening_expiry: Optional[str]
    training_expiry: Optional[str]
    screening_status: str
    training_status: str
    membership_status: str
    contact_eligibility: str
    required_tier: str
    risk_points: int
    records_retained_through: Optional[str]
    blocking_reasons: List[str]


class ClockState(TypedDict, total=False):
    """Shape returned by the logical-clock repositioning endpoint."""

    current_utc: str
