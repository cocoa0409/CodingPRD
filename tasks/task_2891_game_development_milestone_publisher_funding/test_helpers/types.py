"""TypedDict shapes for every persisted resource of the API.

Field sets follow the PRD: §2.4 fixes which resources carry the full
id / created_at / updated_at / version quartet, and states that a
PublisherReview "exposes only `id` and `created_at`".
"""

from typing import Any, Dict, List, Optional, TypedDict


class Studio(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    contact_email: str
    country_code: Optional[str]


class Publisher(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    contact_email: str
    country_code: Optional[str]


class PublisherUser(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    publisher_id: str
    display_name: str
    function: str


class DevelopmentAgreement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    studio_id: str
    publisher_id: str
    title: str
    advance_total_cents: int
    royalty_rate_bps: int
    recoupable_cost_cap_bps: int
    platform_fee_bps: int
    live_ops_quarterly_funding_cents: int
    ship_date_original: str
    ship_date_current: str
    schedule_slip_days: int
    status: str
    funding_posture: str
    recoupment_state: str
    uplift_funded_cents: int
    funding_pool_cents: int
    committed_cents: int
    available_funding_cents: int
    accepted_value_cents: int
    advance_disbursed_cents: int
    holdback_reserve_cents: int
    withheld_payment_cents: int
    advance_recouped_cents: int
    unrecouped_advance_cents: int
    royalties_paid_to_date_cents: int
    breach_count: int
    accepted_milestone_ratio: float
    sequel_rights_holder: str
    ip_reversion_state: str
    post_launch_support_state: str
    live_ops_drawn_cents: int
    terminated_at: Optional[str]


class Milestone(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    depends_on_milestone_id: Optional[str]
    sequence_index: int
    title: str
    gate_profile: str
    funded_amount_cents: int
    uplift_cents: int
    contractor_budget_cents: int
    acceptance_criteria: List[str]
    status: str
    content_threshold_relief_pct: float
    cure_count: int
    cure_deadline_at: Optional[str]
    open_condition_indexes: List[int]
    latest_build_number: int
    accepted_at: Optional[str]


class MilestoneBuild(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    milestone_id: str
    build_number: int
    feature_completeness_pct: float
    crash_free_sessions_pct: float
    content_completeness_pct: float
    known_blocker_count: int
    addressed_condition_indexes: List[int]
    readiness_score: float
    gate_state: str
    submitted_at: str


class PublisherReview(TypedDict):
    """PRD §2.4: a review "exposes only `id` and `created_at`" — it carries
    neither `updated_at` nor `version`."""

    id: str
    created_at: str
    build_id: str
    reviewer_user_id: str
    verdict: str
    conditions: List[int]
    cure_days: int
    review_window_start_at: str
    review_window_end_at: str
    cure_deadline_at: Optional[str]
    notes: Optional[str]
    decided_at: str


class MilestonePayment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    milestone_id: str
    authorized_by_user_id: Optional[str]
    scheduled_amount_cents: int
    contractor_overrun_cents: Optional[int]
    gross_amount_cents: Optional[int]
    holdback_bps: Optional[int]
    holdback_cents: Optional[int]
    net_amount_cents: Optional[int]
    status: str
    authorized_at: Optional[str]


class ChangeOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    target_milestone_id: str
    order_type: str
    requested_amount_cents: int
    ship_date_delta_days: int
    content_threshold_relief_pct: float
    rationale: str
    state: str
    decided_at: Optional[str]


class ContractorEngagement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    milestone_id: str
    studio_id: str
    vendor_code: str
    scope_summary: str
    committed_cents: int
    start_date: str
    end_date: str
    status: str
    approved_invoice_total_cents: int


class ContractorInvoice(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    engagement_id: str
    invoice_number: str
    amount_cents: int
    period_end_date: str
    status: str
    rejection_reason: Optional[str]
    decided_at: Optional[str]


class RevenueLine(TypedDict):
    platform_code: str
    gross_cents: int
    returns_cents: int


class RoyaltyStatement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    period_label: str
    revenue_lines: List[RevenueLine]
    recoupable_cost_cents: int
    distributable_total_cents: int
    cost_deduction_cents: int
    recoupment_base_cents: int
    recoup_applied_cents: int
    royalty_base_cents: int
    provisional_royalty_payable_cents: int
    final_royalty_payable_cents: Optional[int]
    state: str
    finalized_at: Optional[str]


class BudgetSummary(TypedDict):
    """PRD §3.8 budget summary read."""

    milestone_id: str
    contractor_budget_cents: int
    committed_basis_cents: int
    incurred_basis_cents: int
    available_committed_cents: int
    overrun_cents: int


class RecoupmentSummary(TypedDict):
    """PRD §3.9 recoupment-summary read."""

    agreement_id: str
    funding_pool_cents: int
    advance_disbursed_cents: int
    advance_recouped_cents: int
    unrecouped_advance_cents: int
    royalties_paid_to_date_cents: int
    recoupment_state: str
    accepted_milestone_ratio: float
    ip_reversion_state: str
    sequel_rights_holder: str
    post_launch_support_state: str
    live_ops_drawn_cents: int


Headers = Dict[str, str]
Payload = Dict[str, Any]
