"""TypedDict shapes for every resource the API persists.

PRD 2.4 splits the resources in two.  Branch, RateCard, InventoryPosition,
InventoryPlan, Customer, ExchangeTransaction, BuybackContract, NoteAssessment,
ComplianceReport and CashShipment carry the full audit set (id, created_at,
updated_at, version).  CurrencyProfile, WholesaleRate, TravelCorridor and
ArmoredRoute are immutable reference data and carry only id and created_at -
no updated_at and no version at all.
"""

from typing import List, Optional, TypedDict


class DenominationRequest(TypedDict):
    denomination_minor_units: int
    note_count: int


class DenominationMixEntry(TypedDict):
    denomination_minor_units: int
    available_note_count: int
    quarantined_note_count: int
    written_off_note_count: int


class TargetLine(TypedDict):
    currency_code: str
    baseline_daily_minor_units: int


class ComputedTarget(TypedDict):
    currency_code: str
    target_minor_units: int


class Branch(TypedDict):
    id: str
    code: str
    name: str
    region_code: str
    home_currency_code: str
    status: str
    vault_limit_usd_cents: int
    vault_usd_equivalent_cents: int
    vault_utilization_bps: int
    posture: str
    buyback_liability_usd_cents: int
    repatriation_pending: bool
    created_at: str
    updated_at: str
    version: int


class CurrencyProfile(TypedDict):
    id: str
    iso_code: str
    display_name: str
    minor_unit_digits: int
    currency_class: str
    standard_denominations: List[int]
    export_limit_minor_units: Optional[int]
    buyback_eligible: bool
    damaged_note_recovery_bps: int
    created_at: str


class WholesaleRate(TypedDict):
    id: str
    currency_code: str
    mid_rate_micros: int
    effective_at: str
    source_code: str
    created_at: str


class TravelCorridor(TypedDict):
    id: str
    code: str
    origin_country_code: str
    destination_country_code: str
    destination_currency_code: str
    season: str
    season_start_date: str
    season_end_date: str
    demand_index_bps: int
    created_at: str


class ArmoredRoute(TypedDict):
    id: str
    code: str
    carrier_name: str
    region_code: str
    daily_capacity_usd_cents: int
    status: str
    created_at: str


class RateCard(TypedDict):
    id: str
    branch_id: str
    currency_code: str
    wholesale_rate_id: str
    buy_spread_bps: int
    sell_spread_bps: int
    buy_rate_micros: int
    sell_rate_micros: int
    board_display_label: str
    disclosure_text_version: int
    commission_schedule_code: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    published_at: Optional[str]
    superseded_by_rate_card_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryPosition(TypedDict):
    id: str
    branch_id: str
    currency_code: str
    denomination_mix: List[DenominationMixEntry]
    total_minor_units: int
    quarantined_minor_units: int
    usd_equivalent_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryPlan(TypedDict):
    id: str
    branch_id: str
    travel_corridor_id: str
    season_days: int
    target_lines: List[TargetLine]
    computed_targets: List[ComputedTarget]
    status: str
    revision_count: int
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    nationality_code: str
    home_branch_id: Optional[str]
    id_document_type: Optional[str]
    id_document_number: Optional[str]
    id_document_expiry: Optional[str]
    travel_document_reference: Optional[str]
    rolling_30d_settled_usd_cents: int
    calendar_month_settled_usd_cents: int
    near_threshold_txn_count: int
    distinct_branch_count: int
    structuring_risk_score: int
    structuring_risk_tier: str
    compliance_hold_active: bool
    created_at: str
    updated_at: str
    version: int


class ExchangeTransaction(TypedDict):
    id: str
    branch_id: str
    customer_id: str
    rate_card_id: str
    currency_code: str
    direction: str
    requested_denominations: List[DenominationRequest]
    fx_gross_minor_units: int
    applied_rate_micros: int
    quoted_usd_gross_cents: int
    quoted_commission_cents: int
    quoted_total_charge_cents: int
    settled_usd_gross_cents: Optional[int]
    settled_commission_cents: Optional[int]
    settled_total_charge_cents: Optional[int]
    price_adjustment_cents: Optional[int]
    settlement_status: str
    compliance_status: str
    quote_expires_at: str
    quoted_by_user_id: str
    authorized_at: Optional[str]
    authorized_by_user_id: Optional[str]
    settled_at: Optional[str]
    settled_by_user_id: Optional[str]
    reversed_at: Optional[str]
    buyback_contract_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuybackContract(TypedDict):
    id: str
    customer_id: str
    origin_transaction_id: str
    branch_id: str
    currency_code: str
    locked_buy_rate_micros: int
    locked_fx_minor_units: int
    remaining_fx_minor_units: int
    fee_usd_cents: int
    liability_usd_cents: int
    rate_lock_expires_at: str
    status: str
    redemption_count: int
    superseded_by_contract_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NoteAssessment(TypedDict):
    id: str
    branch_id: str
    inventory_position_id: str
    exchange_transaction_id: str
    currency_code: str
    denomination_minor_units: int
    note_count: int
    face_fx_minor_units: int
    defect_type: str
    outcome: Optional[str]
    recovery_usd_cents: Optional[int]
    serial_reference: Optional[str]
    status: str
    assessed_by_user_id: Optional[str]
    assessment_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict):
    id: str
    customer_id: Optional[str]
    branch_id: str
    report_type: str
    triggering_transaction_id: Optional[str]
    note_assessment_id: Optional[str]
    window_start: str
    window_end: str
    aggregate_usd_cents: int
    transaction_count: int
    status: str
    filing_reference: Optional[str]
    filed_at: Optional[str]
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class CashShipment(TypedDict):
    id: str
    branch_id: str
    currency_code: str
    direction: str
    manifest_denominations: List[DenominationRequest]
    manifest_minor_units: int
    manifest_usd_equivalent_cents: int
    armored_route_id: Optional[str]
    window_start: Optional[str]
    window_end: Optional[str]
    delivered_minor_units: Optional[int]
    variance_minor_units: Optional[int]
    written_off_minor_units: Optional[int]
    exception_reason: Optional[str]
    status: str
    auto_generated: bool
    created_at: str
    updated_at: str
    version: int


class RateBoardLine(TypedDict):
    currency_code: str
    board_display_label: str
    buy_rate_micros: int
    sell_rate_micros: int
    disclosure_text_version: int


class RateBoard(TypedDict):
    branch_id: str
    as_of: str
    line_count: int
    min_disclosure_text_version: int
    lines: List[RateBoardLine]


class ClockState(TypedDict):
    current_utc: str
    expired_contract_count: int
