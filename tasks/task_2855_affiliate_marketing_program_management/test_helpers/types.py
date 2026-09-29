"""Typed shapes for the fourteen resources of the affiliate program API.

PRD §2.4 splits them in two.  Ten are mutable and carry `updated_at` and
`version` on top of `id` and `created_at`: "The mutable resources are the
network, the partner, the application, the commission policy, the tracking
link, the order, the violation case, the tax document, the payout batch and
the payout line."  Four are append-only: "Four resources are append-only
records of something that happened and are never edited after creation: the
click event, the attribution decision, the monitoring scan, and the commission
ledger entry. These four carry only `id` and `created_at`."  The append-only
shapes below therefore deliberately omit both fields.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing_extensions is only needed on older runtimes
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore


class MutableResource(TypedDict, total=False):
    """Common fields of a mutable row (§2.4)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyResource(TypedDict, total=False):
    """Common fields of an append-only row (§2.4): `id` and `created_at` only."""

    id: str
    created_at: str


class Network(MutableResource, total=False):
    name: str
    statement_currency: str
    fee_model: str
    fee_bps: int
    flat_fee_cents: int


class Affiliate(MutableResource, total=False):
    legal_name: str
    contact_email: str
    payout_currency: str
    network_id: str
    partner_type: str
    parent_affiliate_id: Optional[str]
    sub_affiliate_depth: int
    status: str
    suspension_cause: str
    fraud_risk_score: int
    fraud_risk_score_trailing: float
    incrementality_score_bps: int
    incrementality_tier: str
    attributed_conversion_count: int
    new_customer_attributed_count: int
    coupon_assisted_conversion_count: int
    accrued_balance_cents: int
    reserved_balance_cents: int
    lifetime_paid_cents: int
    open_violation_case_count: int
    tracking_link_count: int
    tax_document_status: str


class AffiliateApplication(MutableResource, total=False):
    affiliate_id: str
    site_url: str
    primary_traffic_source: str
    monthly_traffic_estimate: int
    declared_promo_methods: List[str]
    product_categories: List[str]
    review_state: str
    screening_outcome: str
    site_quality_score: Optional[float]
    brand_suitability_score: Optional[float]
    revision_round_count: int
    screened_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision_notes: Optional[str]
    conditional_requirements: List[str]


class CommissionPolicy(MutableResource, total=False):
    policy_code: str
    product_category: str
    partner_type_scope: List[str]
    new_customer_rate_bps: int
    returning_customer_rate_bps: int
    effective_from: str
    effective_to: str
    status: str
    superseded_by_policy_id: Optional[str]


class TrackingLink(MutableResource, total=False):
    affiliate_id: str
    landing_url: str
    sub_id: str
    cookie_window_days: int
    device_graph_enabled: bool
    status: str
    disabled_reason: Optional[str]


class ClickEvent(AppendOnlyResource, total=False):
    tracking_link_id: str
    occurred_at: str
    device_id: str
    household_id: Optional[str]
    click_type: str
    referrer_domain: str
    paid_search_keyword: Optional[str]
    is_trademark_term: bool


class Conversion(MutableResource, total=False):
    order_ref: str
    order_total_cents: int
    product_category: str
    customer_ref: str
    is_new_customer: bool
    placed_at: str
    device_id: str
    household_id: Optional[str]
    coupon_code_used: Optional[str]
    other_channel_touch: str
    other_channel_touch_at: Optional[str]
    attribution_status: str
    validation_status: str
    attributed_affiliate_id: Optional[str]
    attributed_click_id: Optional[str]
    commission_policy_id: Optional[str]
    candidate_click_count: int
    gross_commission_cents: int
    payable_commission_cents: int
    clawed_back_cents: int
    returned_amount_cents: int


class AttributionDecision(AppendOnlyResource, total=False):
    conversion_id: str
    algorithm_variant: str
    selected: bool
    candidate_click_count: int
    winning_click_occurred_at: Optional[str]
    device_match_mode: str
    credit_share_bps: int
    computed_commission_cents: int
    dedup_reason: str
    evaluated_at: str


class MonitoringScan(AppendOnlyResource, total=False):
    affiliate_id: str
    engine: str
    window_start: str
    window_end: str
    trademark_hits: int
    forced_click_ratio_bps: int
    cookie_stuffing_index: int
    unauthorized_coupon_hits: int
    opened_case_count: int


class PolicyViolationCase(MutableResource, total=False):
    affiliate_id: str
    violation_type: str
    evidence_ref: Optional[str]
    detected_at: str
    source_scan_id: Optional[str]
    opened_by_user_id: Optional[str]
    state: str
    severity_weight: int
    failed_verification_count: int
    remediation_evidence_ref: Optional[str]
    last_note: Optional[str]


class TaxDocument(MutableResource, total=False):
    affiliate_id: str
    form_type: str
    tax_id_last4: str
    treaty_withholding_bps: int
    expires_on: str
    status: str
    verified_by_user_id: Optional[str]


class CommissionLedgerEntry(AppendOnlyResource, total=False):
    affiliate_id: str
    conversion_id: Optional[str]
    entry_type: str
    amount_cents: int
    memo: str
    payout_batch_id: Optional[str]


class PayoutBatch(MutableResource, total=False):
    network_id: str
    period_start: str
    period_end: str
    state: str
    prepared_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    gross_commission_cents: int
    clawback_cents: int
    network_fee_cents: int
    withholding_cents: int
    net_payable_cents: int
    line_count: int
    reconciliation_status: Optional[str]
    network_fee_variance_cents: int
    network_fee_variance_bps: int
    payment_reference: Optional[str]
    void_reason: Optional[str]


class PayoutLine(MutableResource, total=False):
    payout_batch_id: str
    affiliate_id: str
    state: str
    hold_reason: Optional[str]
    gross_cents: int
    clawback_cents: int
    net_before_fees_cents: int
    conversion_count: int
    network_fee_cents: int
    withholding_bps: int
    withholding_cents: int
    net_cents: int
    released_by_user_id: Optional[str]


#: Resources PRD §2.4 declares mutable — they must expose `updated_at`/`version`.
MUTABLE_RESOURCE_NAMES = (
    "Network",
    "Affiliate",
    "AffiliateApplication",
    "CommissionPolicy",
    "TrackingLink",
    "Conversion",
    "PolicyViolationCase",
    "TaxDocument",
    "PayoutBatch",
    "PayoutLine",
)

#: Resources PRD §2.4 declares append-only — no `updated_at`, no `version`.
APPEND_ONLY_RESOURCE_NAMES = (
    "ClickEvent",
    "AttributionDecision",
    "MonitoringScan",
    "CommissionLedgerEntry",
)

JsonDict = Dict[str, Any]
