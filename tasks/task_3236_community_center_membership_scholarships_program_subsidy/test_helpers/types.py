"""Typed shapes for every entity the Community Center Membership API returns.

Each TypedDict mirrors the field list the PRD declares for that resource.
Every resource carries the full common-field contract: a server-minted ``id``,
``created_at`` and ``updated_at`` timestamps, and an integer ``version``.
"""

from typing import List, Optional, TypedDict


class ResponseMeta(TypedDict, total=False):
    """The meta block that accompanies every response."""

    api_request_id: str
    api_request_timestamp: str
    response_type: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class Association(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    reciprocity_enabled: bool
    ami_base_cents: int
    campaign_year: int


class Branch(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    association_id: str
    code: str
    name: str
    branch_goal_cents: int
    scholarship_pool_received_cents: int
    scholarship_pool_obligated_cents: int
    scholarship_pool_available_cents: int
    active_membership_count: int


class MembershipCategory(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    branch_id: str
    name: str
    household_type: str
    joining_fee_cents: int
    monthly_dues_cents: int
    max_adults: int
    max_dependents: int
    hold_fee_cents: int


class Member(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    email: str
    birth_date: str
    home_branch_id: str
    visiting_association_name: Optional[str]


class Membership(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    branch_id: str
    category_id: str
    primary_member_id: str
    member_ids: List[str]
    status: str
    draft_status: str
    assistance_pct: float
    joining_fee_charged_cents: int
    anniversary_day: int
    hold_started_on: Optional[str]
    hold_until: Optional[str]
    lapsed_on: Optional[str]
    delinquent_since: Optional[str]
    hold_days_used_trailing_12mo: int
    lifetime_billed_cents: int


class BillingDraft(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    membership_id: str
    period_month: str
    amount_cents: int
    attempt_count: int
    status: str
    kind: str


class ScholarshipApplication(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    branch_id: str
    membership_id: str
    applicant_member_id: str
    household_size: int
    annual_income_cents: int
    documentation: List[str]
    income_ratio: float
    preview_award_pct: Optional[float]
    award_pct: Optional[float]
    award_obligation_cents: int
    status: str
    award_start_on: Optional[str]
    award_end_on: Optional[str]
    renews_application_id: Optional[str]


class Program(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    branch_id: str
    name: str
    kind: str
    member_only: bool
    member_priority_days: int
    min_age: int
    max_age: int
    base_fee_cents: int
    non_member_multiplier: float
    is_licensed_childcare: bool
    licensed_children_per_staff: Optional[int]


class ProgramSession(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    branch_id: str
    space_id: str
    start_on: str
    end_on: str
    time_start: str
    time_end: str
    capacity: int
    enrolled_count: int
    waitlist_count: int
    staff_member_ids: List[str]
    public_opens_on: str
    member_opens_on: str
    status: str


class Registration(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    session_id: str
    member_id: str
    participant_name: str
    participant_birth_date: str
    registrant_class: str
    fee_charged_cents: int
    waitlist_position: Optional[int]
    status: str


class FacilitySpace(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    branch_id: str
    name: str
    kind: str
    capacity: int
    dropin_capacity: int


class FacilityReservation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    space_id: str
    branch_id: str
    session_id: Optional[str]
    reservation_type: str
    start_at: str
    end_at: str
    buffer_minutes: int
    renter_member_id: Optional[str]
    status: str


class Campaign(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    association_id: str
    name: str
    goal_cents: int
    base_raised_cents: int
    match_pct: float
    matched_raised_cents: int
    status: str


class Donation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    campaign_id: str
    branch_id: str
    donor_member_id: Optional[str]
    amount_cents: int
    designation: str
    status: str
