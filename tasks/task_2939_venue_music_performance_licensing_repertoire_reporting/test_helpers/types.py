"""
Row shapes of the Venue Music Licensing API, as declared by the PRD.

These ``TypedDict`` definitions document what each read returns; they are
annotations for readability, not runtime validators.

Note the split PRD §2.5 draws.  ``Society``, ``RateSchedule``, ``Venue``,
``LicenseApplication``, ``License``, ``CoverageWindow``, ``PerformanceReport``,
``AuditCase`` and ``FeeAssessment`` carry the full audit triplet
(``created_at``, ``updated_at``, ``version``).  ``RepertoireWork`` and
``SetlistEntry`` are "immutable registry rows and are deliberately thinner":
each "carry only ``id`` and ``created_at``", so their TypedDicts below
deliberately omit ``updated_at`` and ``version``.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing shim for older interpreters
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore


class VersionedRow(TypedDict, total=False):
    """The audit triplet shared by the nine versioned resources of PRD §2.5."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableRow(TypedDict, total=False):
    """The thin registry row of PRD §2.5: ``id`` and ``created_at`` only."""

    id: str
    created_at: str


class Society(VersionedRow, total=False):
    society_code: str
    display_name: str
    repertoire_share_bp: int
    rate_court_supervised: bool
    licensed_venue_count: int


class RepertoireWork(ImmutableRow, total=False):
    society_id: str
    title: str
    writer_name: str
    iswc: Optional[str]


class RateSchedule(VersionedRow, total=False):
    society_id: str
    venue_category: str
    effective_from: str
    rate_court_order_ref: Optional[str]
    adjustment_bp: int
    min_annual_fee_cents: int
    max_annual_fee_cents: int
    schedule_version: int
    status: str
    pinned_license_count: int


class Venue(VersionedRow, total=False):
    legal_name: str
    venue_category: str
    seating_capacity: int
    standing_capacity: int
    occupancy_limit: int
    music_use_profile: str
    weekly_live_performance_nights: int
    annual_cover_revenue_cents: int
    gross_square_feet: Optional[int]
    speaker_count: Optional[int]
    max_speakers_per_room: Optional[int]
    has_cover_charge: bool
    retransmission_only: bool
    uses_licensed_bgm_service: bool
    bgm_service_provider: Optional[str]
    status: str
    bgm_exemption_status: str
    bgm_exemption_reason: Optional[str]
    covered_share_bp: int
    coverage_posture: str
    gap_risk_score: float
    audit_hold: bool
    lifetime_assessed_cents: int
    outstanding_balance_cents: int
    settled_amount_cents: int
    voided_amount_cents: int


class LicenseApplication(VersionedRow, total=False):
    venue_id: str
    society_id: str
    requested_license_type: str
    declared_seating: int
    declared_standing: int
    declared_cover_revenue_cents: int
    declared_live_nights: int
    declared_music_use_profile: str
    requested_term_start: str
    status: str
    revision_round: int
    return_reason: Optional[str]
    decline_reason: Optional[str]
    assigned_license_type: Optional[str]
    provisional_annual_fee_cents: Optional[int]


class License(VersionedRow, total=False):
    venue_id: str
    society_id: str
    application_id: Optional[str]
    rate_schedule_id: str
    pinned_schedule_version: int
    license_type: str
    coverage_status: str
    billing_status: str
    term_start: str
    term_end: str
    renewal_of_license_id: Optional[str]
    provisional_annual_fee_cents: int
    annual_fee_cents: int
    verified_fee_delta_cents: int
    reporting_required: bool
    accepted_report_count: int
    renewal_issued_at: Optional[str]
    suspension_reason: Optional[str]


class CoverageWindow(VersionedRow, total=False):
    license_id: str
    window_kind: str
    window_start: str
    window_end: str
    covered_day_count: int
    rider_fee_cents: int
    status: str


class PerformanceReport(VersionedRow, total=False):
    license_id: str
    period_start: str
    period_end: str
    status: str
    reported_entry_count: int
    matched_entry_count: int
    uncovered_entry_count: int
    unmatched_share_pct: float
    uncovered_share_pct: float
    gap_exposure_cents: int
    review_round: int
    rejection_reason: Optional[str]


class SetlistEntry(ImmutableRow, total=False):
    performance_report_id: str
    work_title: str
    writer_name: str
    society_affiliation: str
    performance_datetime: str
    use_type: str
    duration_seconds: int
    is_matched: bool
    matched_work_id: Optional[str]
    is_covered: bool


class AuditCase(VersionedRow, total=False):
    venue_id: str
    audit_trigger: str
    lookback_start: str
    lookback_end: str
    society_ids: List[str]
    status: str
    unlicensed_month_count: int
    back_license_exposure_cents: int
    penalty_cents: int
    pre_credit_total_cents: int
    goodwill_credit_cents: int
    settlement_total_cents: int
    settlement_floor_cents: int
    offered_amount_cents: Optional[int]
    payment_plan_months: Optional[int]
    dispute_round: int
    findings_issued_by_user_id: Optional[str]
    settlement_proposed_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]
    closed_reason: Optional[str]


class FeeAssessment(VersionedRow, total=False):
    venue_id: str
    license_id: Optional[str]
    audit_case_id: Optional[str]
    assessment_kind: str
    amount_cents: int
    paid_amount_cents: int
    status: str
    due_date: str


# A convenience alias for the many helpers that return whatever ``data`` held.
Row = Dict[str, Any]
