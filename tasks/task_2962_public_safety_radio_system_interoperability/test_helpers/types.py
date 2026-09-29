"""TypedDict shapes for the eleven persisted resources plus the two computed
read projections.

Every persisted resource carries the same four system-managed properties
(`id`, `created_at`, `updated_at`, `version`), so they live on a shared
`CommonFields` base that each entity extends.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """PRD 2.5 — the four system-managed properties every resource carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class MemberAgency(CommonFields, total=False):
    name: str
    agency_code: str
    agency_type: str
    fee_basis: str
    interop_privilege: str
    console_position_count: int
    recorder_retention_days: int
    billing_status: str
    billable_subscriber_count: int
    last_assessed_fee_cents: int
    fee_balance_cents: int
    lifetime_assessed_cents: int
    lifetime_paid_cents: int
    active_patch_request_count: int
    last_assessment_period_start: Optional[str]
    last_assessment_period_end: Optional[str]
    payment_due_at: Optional[str]
    voting_eligible: bool
    governance_vote_weight: int


class Site(CommonFields, total=False):
    site_code: str
    name: str
    channel_capacity: int
    backup_power_type: str
    battery_runtime_minutes: int
    generator_fuel_hours: float
    migration_standard: str
    status: str
    capacity_mode: str
    coverage_class: str
    coverage_derate_tier: str
    coverage_reliability_pct: float
    covered_test_points: int
    total_test_points: int
    busy_talkpaths: int
    peak_talkpaths: int
    granted_request_count: int
    busied_request_count: int
    grade_of_service_pct: float


class RadioTemplate(CommonFields, total=False):
    template_name: str
    target_standard: str
    talkgroup_slot_count: int
    encryption_required: bool
    template_version: int
    supersedes_template_id: Optional[str]
    status: str
    deployed_unit_count: int
    created_by_user_id: str


class ProgrammingChangeRequest(CommonFields, total=False):
    template_id: str
    target_agency_id: str
    title: str
    status: str
    revision_count: int
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    review_comment: Optional[str]
    pinned_template_version: Optional[int]
    pinned_template_record_version: Optional[int]
    target_unit_count: int
    deployed_unit_count: int
    failed_unit_count: int
    deployment_started_at: Optional[str]
    deployed_at: Optional[str]


class SubscriberUnit(CommonFields, total=False):
    agency_id: str
    serial_number: str
    radio_id: int
    model: str
    priority_class: int
    emergency_button_enabled: bool
    provision_status: str
    key_status: str
    template_id: Optional[str]
    active_keyset_id: Optional[str]
    billable: bool
    days_in_service_last_period: int
    assigned_at: Optional[str]
    retired_at: Optional[str]
    last_otar_at: Optional[str]


class Keyset(CommonFields, total=False):
    keyset_name: str
    algorithm: str
    crypto_period_start: str
    crypto_period_end: str
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    compromised_at: Optional[str]
    loaded_unit_count: int


class OtarCampaign(CommonFields, total=False):
    keyset_id: str
    agency_id: str
    window_start: str
    window_end: str
    status: str
    target_unit_count: int
    rekeyed_unit_count: int
    failed_unit_count: int
    executed_at: Optional[str]


class Talkgroup(CommonFields, total=False):
    owner_agency_id: str
    home_site_id: str
    alias: str
    tg_decimal_id: int
    kind: str
    encryption_mode: str
    priority_level: int
    status: str
    lock_reason: str
    active_patch_count: int


class InteropPatch(CommonFields, total=False):
    source_talkgroup_id: str
    target_talkgroup_id: str
    requesting_agency_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    activated_at: Optional[str]
    released_at: Optional[str]
    duration_minutes: Optional[int]
    recorder_retention_days_at_activation: Optional[int]
    release_reason: str


class SiteEvent(CommonFields, total=False):
    site_id: str
    event_class: str
    cause: str
    window_start: Optional[str]
    window_end: Optional[str]
    status: str
    detected_at: str
    escalation_tier: int
    backup_minutes_remaining: Optional[int]
    restored_at: Optional[str]
    preempted_talkpath_count: int


class TalkpathRequest(CommonFields, total=False):
    site_id: str
    talkgroup_id: str
    unit_id: str
    site_event_id: Optional[str]
    request_kind: str
    outcome: str
    granted_at: Optional[str]
    released_at: Optional[str]
    hold_seconds: Optional[int]
    priority_class_at_grant: Optional[int]
    available_talkpaths_at_decision: int
    reserve_talkpaths_at_decision: int
    preempted_request_id: Optional[str]


class GovernanceStanding(TypedDict, total=False):
    """PRD 3.9 — the board-level standing read; not a persisted resource."""

    agency_id: str
    billing_status: str
    billable_subscriber_count: int
    governance_vote_weight: int
    voting_eligible: bool
    total_eligible_weight: int
    quorum_weight_required: int


class MigrationReadiness(TypedDict, total=False):
    """PRD 3.9 — a read-only projection that writes nothing."""

    basis: str
    agency_id: Optional[str]
    evaluated_unit_count: int
    ready_unit_count: int
    readiness_pct: float


class ClockReading(TypedDict, total=False):
    """PRD 2.5 — the logical-clock control response."""

    current_utc: str


Payload = Dict[str, Any]
Headers = Dict[str, str]
ResourceList = List[Dict[str, Any]]
