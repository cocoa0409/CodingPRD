"""
Response shapes for the Building Trades Hiring Hall Dispatch API.

Every TypedDict mirrors exactly the fields the PRD declares for that resource.
Per §2.4 most resources carry the full audit set (`id`, `created_at`,
`updated_at`, `version`), while a skill endorsement and a retention-ledger
entry are deliberately reduced to `id` and `created_at` only — those two
TypedDicts therefore omit `updated_at` and `version` on purpose.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ─── Envelope (§2.2) ──────────────────────────────────────────────────────────


class ResponseMeta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ErrorPayload(TypedDict):
    error_id: str
    message: str


# ─── Resources carrying id / created_at / updated_at / version (§2.4) ─────────


class Local(TypedDict):
    id: str
    local_number: int
    name: str
    kind: str
    reciprocity_factor_bp: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    home_local_id: str
    classification: str
    apprentice_period: Optional[int]
    local_hours_in_trade: int
    standing: str
    is_traveler: bool
    re_registration_eligible_at: Optional[str]
    refusal_strike_count: int
    dispatch_eligible: bool
    created_at: str
    updated_at: str
    version: int


class OutOfWorkList(TypedDict):
    id: str
    group_code: str
    priority_rank: int
    ordering_policy: str
    requires_local_hours: int
    accepts_travelers: bool
    registered_count: int
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    member_id: str
    list_id: str
    status: str
    registered_at: str
    last_renewed_at: str
    renewal_due_at: str
    credited_seniority_hours: int
    position_number: Optional[int]
    demotion_count: int
    priority_flag: bool
    removal_reason: Optional[str]
    predecessor_registration_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict):
    id: str
    name: str
    agreement_expires_at: str
    signatory_status: str
    created_at: str
    updated_at: str
    version: int


class JobRequest(TypedDict):
    id: str
    contractor_id: str
    job_site: str
    journeyworkers_requested: int
    apprentices_requested: int
    expected_duration_days: int
    duration_type: str
    report_at: str
    hourly_rate_cents: int
    required_skill_code: Optional[str]
    special_skill_slots_requested: int
    named_call_member_ids: List[str]
    named_call_allowance: int
    special_skill_allowance: int
    open_journeyworker_slots: int
    open_apprentice_slots: int
    accepted_journeyworker_count: int
    accepted_apprentice_count: int
    max_apprentices_allowed: int
    status: str
    suspended_from_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    job_request_id: str
    registration_id: str
    member_id: str
    slot_kind: str
    referral_kind: str
    status: str
    issued_at: str
    acceptance_deadline: str
    issued_by_user_id: str
    list_position_at_issue: Optional[int]
    variant_applied: str
    out_of_order_override: bool
    override_reason: Optional[str]
    refusal_good_cause_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict):
    id: str
    referral_id: str
    job_request_id: str
    member_id: str
    status: str
    start_at: str
    ended_at: Optional[str]
    hours_worked: int
    layoff_reason: Optional[str]
    recall_of_dispatch_id: Optional[str]
    recall_window_ends_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Grievance(TypedDict):
    id: str
    referral_id: str
    grievant_member_id: str
    claim_type: str
    narrative: str
    status: str
    filed_at: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    decision_note: Optional[str]
    remedy: str
    back_pay_variant: str
    back_pay_hours: int
    back_pay_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class RatioPolicy(TypedDict):
    id: str
    policy_code: str
    first_apprentice_at_jw_count: int
    then_every_n_jw: int
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── The two reduced-shape records: id + created_at only (§2.4) ───────────────


class SkillEndorsement(TypedDict):
    """No `updated_at` and no `version`: an endorsement is a sighting of a card."""

    id: str
    member_id: str
    skill_code: str
    certified_until: str
    verified: bool
    created_at: str


class DispatchLedgerEntry(TypedDict):
    """No `updated_at` and no `version`: an append-only audit row."""

    id: str
    event_code: str
    member_id: str
    referral_id: Optional[str]
    recorded_at: str
    retention_until: str
    purge_state: str
    snapshot_json: Optional[Dict[str, Any]]
    hours_delta: int
    created_at: str


# ─── Computed reads that persist nothing (§3.2, §3.4) ─────────────────────────


class DispatchOrderRead(TypedDict):
    variant: str
    candidate_count: int
    top_registration_id: str
    top_member_id: str
    top_list_group_code: str
    top_position_number: int
    top_credited_seniority_hours: int


class DispatchRunResult(TypedDict):
    run_at: str
    expired_referral_count: int
    demoted_registration_count: int
    removed_registration_count: int
    expired_registration_count: int
    purged_ledger_entry_count: int


class ClockState(TypedDict):
    current_utc: str


class ReciprocityCredit(TypedDict):
    sister_local_id: str
    raw_hours: int
