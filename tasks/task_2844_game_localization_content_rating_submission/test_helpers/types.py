"""Typed shapes for the twelve resources of the API.

Every entity carries the common properties of §2.4: a server-minted ``id``,
``created_at``, ``updated_at`` and an integer ``version``.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Title(CommonFields):
    title_code: str
    name: str
    source_language: str
    target_release_utc: str
    release_mode: str
    localization_state: str
    string_lock: bool
    release_gate_state: str
    extracted_key_count: int
    market_plan_count: int
    ready_market_count: int


class MarketPlan(CommonFields):
    title_id: str
    market_code: str
    rating_board: str
    target_rating: str
    scope_tier: Optional[str]
    cultural_adaptation_required: bool
    budget_cap_cents: int
    required_voice_line_count: int
    status: str
    blocked_reason: Optional[str]
    required_unit_count: int
    delivered_unit_count: int
    voice_recorded_line_count: int
    text_effort_units: float
    text_effort_variant: Optional[str]
    localization_cost_cents: int
    overage_cents: int


class StringKey(CommonFields):
    title_id: str
    key_name: str
    source_text: str
    source_char_count: int
    ui_surface: str
    display_char_limit: int
    tm_match_pct: int
    context_note: Optional[str]
    status: str


class TranslationUnit(CommonFields):
    market_plan_id: str
    string_key_id: str
    translation_status: str
    qa_status: str
    target_text: Optional[str]
    target_char_count: int
    applied_tm_match_pct: Optional[int]
    overflow_chars: int
    open_bug_count: int


class RecordingBooth(CommonFields):
    booth_code: str
    studio_city: str
    turnaround_buffer_minutes: int
    reserved_minutes_total: int


class VoiceTalent(CommonFields):
    talent_name: str
    language_code: str
    union_flag: bool
    max_daily_recording_minutes: int
    reserved_minutes_on_clock_date: int


class TalentContract(CommonFields):
    voice_talent_id: str
    title_id: str
    territory_scope: List[str]
    media_scope: str
    buyout_fee_cents: int
    per_line_rate_cents: int
    rights_start_utc: str
    rights_end_utc: str
    status: str
    signed_at_utc: Optional[str]
    committed_fee_cents: int


class VoiceSession(CommonFields):
    market_plan_id: str
    voice_talent_id: str
    recording_booth_id: str
    talent_contract_id: str
    start_utc: str
    end_utc: str
    occupied_end_utc: str
    duration_minutes: int
    planned_line_count: int
    recorded_line_count: Optional[int]
    line_fee_cents: int
    status: str


class QaPass(CommonFields):
    market_plan_id: str
    pass_type: str
    pass_index: int
    inspected_unit_count: int
    status: str
    opened_by_user_id: str
    reopen_count: int
    weighted_defect_points: int
    defect_density: float
    closed_at_utc: Optional[str]


class LqaBug(CommonFields):
    qa_pass_id: str
    translation_unit_id: Optional[str]
    bug_class: str
    severity: str
    severity_weight: int
    axis: str
    summary: str
    status: str
    logged_by_user_id: str
    verified_by_user_id: Optional[str]
    duplicate_of_bug_id: Optional[str]


class RatingSubmission(CommonFields):
    market_plan_id: str
    rating_board: str
    submission_round: int
    disclosed_content_codes: List[str]
    footage_asset_count: int
    target_rating: str
    assigned_rating: Optional[str]
    self_assessed_risk_score: Optional[int]
    board_adjusted_risk_score: Optional[int]
    projected_rating_band: Optional[str]
    status: str
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    submitted_at_utc: Optional[str]
    fee_cents: Optional[int]
    appeal_count: int


class ContentEdit(CommonFields):
    rating_submission_id: str
    edit_kind: str
    rationale: str
    affected_string_key_ids: List[str]
    removed_content_codes: List[str]
    status: str
    invalidated_unit_count: int
    applied_at_utc: Optional[str]


class LogicalClock(TypedDict):
    current_utc: str
