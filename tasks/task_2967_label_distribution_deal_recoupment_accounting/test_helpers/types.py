"""
TypedDict shapes for every record type in the Label Distribution Recoupment API.

These exist to document the response shape the tests read; nothing here is
enforced at runtime. Note the deliberate split mandated by PRD Section 2.4:

  * The nine mutable record types carry `id`, `created_at`, `updated_at` and
    `version`.
  * The two append-only record types - StreamRateCard and DspRevenueLine -
    "carry neither `updated_at` nor `version`", so their TypedDicts omit both.

Percentage fields are annotated `Pct` because a conforming server may render a
four-decimal fraction as a JSON number or as a decimal string; compare them with
assertions.assert_pct_equals rather than with `==`.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, TypedDict, Union

# A four-decimal contractual percentage as it arrives in a response body.
Pct = Union[float, str, Decimal, None]
# Money is always an integer number of whole cents (PRD Section 2.6).
Cents = int
# A calendar date, "YYYY-MM-DD".
DateStr = str
# An ISO 8601 UTC instant with exactly three fractional digits.
InstantStr = str

JsonDict = Dict[str, Any]


class MutableCommonFields(TypedDict):
    id: str
    created_at: InstantStr
    updated_at: InstantStr
    version: int


class AppendOnlyCommonFields(TypedDict):
    id: str
    created_at: InstantStr


class Distributor(MutableCommonFields, total=False):
    name: str
    legal_entity: str
    default_returns_reserve_pct: Pct
    active_deal_count: int


class Artist(MutableCommonFields, total=False):
    legal_name: str
    email: str
    lifetime_paid_cents: Cents
    unrecouped_advance_total_cents: Cents


class DistributionDeal(MutableCommonFields, total=False):
    distributor_id: str
    deal_type: str
    distribution_fee_pct: Pct
    profit_share_label_pct: Pct
    services_fee_pct: Pct
    services_monthly_fee_cents: Optional[Cents]
    term_start_date: DateStr
    term_end_date: DateStr
    territory_codes: List[str]
    cross_collateralized: bool
    advance_amount_cents: Cents
    marketing_budget_cents: Cents
    objection_window_days: int
    post_term_collection_days: int
    status: str
    advance_payment_reference: Optional[str]
    executed_at: Optional[InstantStr]
    termination_effective_date: Optional[DateStr]
    post_term_collection_end_date: Optional[DateStr]
    recoupment_status: str
    advance_recouped_cents: Cents
    unrecouped_advance_cents: Cents
    net_receipts_to_date_cents: Cents
    post_recoupment_net_receipts_cents: Cents
    marketing_committed_cents: Cents


class Release(MutableCommonFields, total=False):
    deal_id: str
    primary_artist_id: str
    upc: str
    title: str
    planned_release_date: DateStr
    actual_release_date: Optional[DateStr]
    formats: List[str]
    advance_share_cents: Cents
    status: str
    reversion_eligible_date: Optional[DateStr]
    net_receipts_to_date_cents: Cents
    release_advance_recouped_cents: Cents
    unrecouped_advance_share_cents: Cents
    recoupable_marketing_applied_cents: Cents


class ArtistAgreement(MutableCommonFields, total=False):
    artist_id: str
    release_id: str
    royalty_rate_pct: Pct
    escalated_royalty_rate_pct: Pct
    advance_amount_cents: Cents
    recording_costs_cents: Cents
    recording_recoupable_pct: Pct
    marketing_recoup_share_pct: Pct
    supersedes_agreement_id: Optional[str]
    status: str
    active_royalty_rate_pct: Pct
    proposed_royalty_rate_pct: Pct
    proposed_advance_amount_cents: Optional[Cents]
    unrecouped_artist_advance_cents: Cents
    unrecouped_recording_cents: Cents
    post_term_collection_end_date: Optional[DateStr]


class MarketingSpend(MutableCommonFields, total=False):
    release_id: str
    category: str
    amount_cents: Cents
    vendor: str
    recoupability: str
    status: str
    requested_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    approved_at: Optional[InstantStr]
    settled_amount_cents: Optional[Cents]
    revision_note: Optional[str]


class StreamRateCard(AppendOnlyCommonFields, total=False):
    """Immutable: "there is no edit and no withdrawal, which is why they carry
    neither `updated_at` nor `version`"."""

    dsp_code: str
    territory_code: str
    tier: str
    rate_micros_per_stream: int
    effective_from: DateStr
    effective_to: Optional[DateStr]


class DspRevenueReport(MutableCommonFields, total=False):
    deal_id: str
    dsp_code: str
    period_start: DateStr
    period_end: DateStr
    status: str
    submitted_by_user_id: Optional[str]
    gross_receipts_cents: Cents
    distributor_share_cents: Cents
    net_receipts_cents: Cents
    advance_applied_cents: Cents
    accepted_at: Optional[InstantStr]
    dispute_reason: Optional[str]


class DspRevenueLine(AppendOnlyCommonFields, total=False):
    """Immutable append-only line: no `updated_at`, no `version`."""

    report_id: str
    release_id: str
    territory_code: str
    tier: str
    stream_count: int
    applied_rate_micros_per_stream: Optional[int]
    resolved_revenue_cents: Optional[Cents]
    net_receipts_cents: Optional[Cents]


class PhysicalRun(MutableCommonFields, total=False):
    release_id: str
    distributor_id: str
    units_planned: int
    unit_manufacturing_cost_cents: Cents
    window_start: DateStr
    window_end: DateStr
    returns_reserve_pct: Pct
    status: str
    reserve_status: str
    units_manufactured: Optional[int]
    units_shipped: Optional[int]
    units_returned: int
    wholesale_unit_price_cents: Optional[Cents]
    returns_rate: Pct
    effective_reserve_pct: Pct
    reserve_initial_cents: Cents
    reserve_held_cents: Cents
    reserve_liquidated_cents: Cents
    manufacturing_cost_cents: Cents
    physical_net_receipts_cents: Cents


class ArtistStatement(MutableCommonFields, total=False):
    artist_agreement_id: str
    period_start: DateStr
    period_end: DateStr
    basis_variant: str
    status: str
    audit_status: str
    prepared_by_user_id: Optional[str]
    issued_by_user_id: Optional[str]
    issued_at: Optional[InstantStr]
    objection_deadline: Optional[InstantStr]
    finalized_at: Optional[InstantStr]
    applied_royalty_rate_pct: Pct
    digital_royalty_base_cents: Cents
    physical_royalty_base_cents: Cents
    gross_royalty_cents: Cents
    advance_applied_cents: Cents
    recording_applied_cents: Cents
    marketing_applied_cents: Cents
    reserve_withheld_cents: Cents
    net_payable_cents: Cents
    objection_reason_code: Optional[str]
    objection_disputed_amount_cents: Optional[Cents]
    objection_narrative: Optional[str]
    objection_filed_at: Optional[InstantStr]
    objection_resolution: Optional[str]
    objection_adjustment_cents: Optional[Cents]
    audit_scope_period_start: Optional[DateStr]
    audit_scope_period_end: Optional[DateStr]
    auditor_name: Optional[str]
    audit_findings_adjustment_cents: Optional[Cents]
    audit_cost_bearer: Optional[str]
    revision_count: int


class RecoupmentReleaseBreakdown(TypedDict, total=False):
    """One entry of the projection's `release_breakdown` array."""

    release_id: str
    advance_share_cents: Cents
    net_receipts_cents: Cents
    advance_applied_cents: Cents
    unrecouped_advance_share_cents: Cents


class RecoupmentSummary(TypedDict, total=False):
    """Computed, non-persisting projection returned by
    GET /distribution-deals/{id}/recoupment-summary."""

    variant: str
    pool_net_receipts_cents: Cents
    advance_amount_cents: Cents
    advance_applied_cents: Cents
    unrecouped_advance_cents: Cents
    post_recoupment_net_receipts_cents: Cents
    recoupment_status: str
    release_breakdown: List[RecoupmentReleaseBreakdown]
