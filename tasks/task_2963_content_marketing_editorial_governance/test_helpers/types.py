"""
TypedDict shapes for every entity the API exposes.

Field names and nullability follow the PRD. Two entities are deliberately
immutable and carry only ``id`` and ``created_at`` — an evidence row and a
measurement period have no ``updated_at`` and no ``version`` (PRD 2.4), so
their TypedDicts omit those two keys entirely.
"""

from typing import List, Optional, TypedDict


class Campaign(TypedDict):
    id: str
    code: str
    persona: str
    primary_funnel_stage: str
    quarter_code: str
    status: str
    governance_posture: str
    breached_gate_count: int
    expired_usage_count: int
    unsubstantiated_published_claim_count: int
    committed_points_total: int
    created_at: str
    updated_at: str
    version: int


class CalendarSlot(TypedDict):
    id: str
    campaign_id: str
    week_start_date: str
    funnel_stage: str
    capacity_points: int
    committed_points: int
    utilization_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SubjectMatterExpert(TypedDict):
    id: str
    full_name: str
    expertise_tags: List[str]
    weekly_capacity_hours: int
    status: str
    committed_hours_total: int
    created_at: str
    updated_at: str
    version: int


class ContentBrief(TypedDict):
    id: str
    campaign_id: str
    funnel_stage: str
    search_intent: str
    primary_keyword: str
    secondary_keywords: List[str]
    target_word_count: int
    required_expertise_tag: str
    requires_regulated_review: bool
    review_window_start: str
    review_window_end: str
    sme_expert_id: Optional[str]
    effort_points: int
    sme_reserved_hours: int
    state: str
    created_at: str
    updated_at: str
    version: int


class ContentItem(TypedDict):
    id: str
    brief_id: str
    slot_id: str
    campaign_id: str
    title: str
    planned_publish_at: str
    promotion_window_days: int
    effort_points: int
    commit_points: int
    capacity_tier_at_commit: str
    workflow_state: str
    revision_number: int
    created_by_user_id: str
    published_by_user_id: Optional[str]
    published_at: Optional[str]
    retracted_at: Optional[str]
    meta_description: Optional[str]
    url_slug: Optional[str]
    tags: List[str]
    accuracy_status: str
    last_audit_type: Optional[str]
    last_audit_verdict: Optional[str]
    last_audit_at: Optional[str]
    engaged_sessions_total: int
    conversions_total: int
    last_touch_pipeline_cents: int
    assisted_pipeline_cents: int
    decay_pct: float
    refresh_required: bool
    created_at: str
    updated_at: str
    version: int


class ReviewGate(TypedDict):
    id: str
    content_item_id: str
    gate_type: str
    state: str
    opened_at: str
    due_at: str
    sla_hours: int
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    decision_notes: Optional[str]
    turnaround_hours: Optional[float]
    sla_breached: bool
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    content_item_id: str
    claim_text: str
    claim_type: str
    substantiation_state: str
    scoring_variant: str
    required_score: float
    evidence_score: float
    evidence_valid_until: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Evidence(TypedDict):
    """Immutable row: ``id`` and ``created_at`` only, no version (PRD 2.4)."""

    id: str
    claim_id: str
    source_type: str
    citation: str
    collected_at: str
    valid_until: str
    weight: float
    submitted_by_user_id: str
    created_at: str


class Asset(TypedDict):
    id: str
    name: str
    asset_type: str
    license_start: str
    license_end: str
    licensed_channels: List[str]
    max_licensed_uses: int
    active_use_count: int
    remaining_licensed_uses: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AssetUsage(TypedDict):
    id: str
    content_item_id: str
    asset_id: str
    channel: str
    usage_state: str
    attached_at: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict):
    id: str
    content_item_id: str
    channel: str
    scheduled_at: str
    state: str
    went_live_at: Optional[str]
    suppression_reason: Optional[str]
    suppressed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceSnapshot(TypedDict):
    """Immutable row: ``id`` and ``created_at`` only, no version (PRD 2.4)."""

    id: str
    content_item_id: str
    period_start: str
    period_end: str
    engaged_sessions: int
    conversions: int
    influenced_opportunity_amount_cents: int
    touch_position: str
    created_at: str


class SweepTally(TypedDict):
    assets_expired: int
    usages_lapsed: int
    distributions_activated: int
    claims_expired: int
    distributions_suppressed: int
    items_flagged_refresh: int
    gates_breached: int
    campaigns_restricted: int
    campaigns_frozen: int


# Keys that every mutable entity carries and the two immutable ones do not.
MUTABLE_ONLY_FIELDS = ["updated_at", "version"]
