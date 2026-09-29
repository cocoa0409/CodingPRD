"""Typed shapes of the sixteen resource types, as the PRD narrative declares them.

Every dict is `total=False` because a payload built by a factory carries only the
fields that operation supplies, while a response carries the full row.

Territory, ComparableTitle and DistributionRun deliberately carry only `id` and
`created_at`: they have neither `updated_at` nor `version` at all.
"""

from typing import Any, Dict, List, Optional, TypedDict


class AuditedRow(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int


class ReferenceRow(TypedDict, total=False):
    id: str
    created_at: str


class Film(AuditedRow, total=False):
    title: str
    genre: str
    production_budget_usd: float
    principal_cast_score: int
    estimated_delivery_date: str
    theatrical_release_date: str
    completion_status: str
    sales_status: str
    total_mg_committed_usd: float
    total_mg_collected_usd: float
    financing_gap_usd: float
    published_territory_count: int
    licensed_territory_count: int


class SalesAgencyAgreement(AuditedRow, total=False):
    film_id: str
    commission_pct: float
    expense_cap_usd: float
    term_months: int
    term_start_date: str
    term_end_date: str
    status: str
    executed_by_user_id: Optional[str]
    expenses_incurred_usd: float
    expenses_recouped_usd: float
    commission_earned_usd: float
    gross_collected_usd: float


class Territory(ReferenceRow, total=False):
    code: str
    name: str
    region: str
    market_tier: int
    currency_code: str
    base_value_index: float


class ComparableTitle(ReferenceRow, total=False):
    territory_id: str
    name: str
    genre: str
    cast_score: int
    gross_license_fee_usd: float
    release_year: int
    verified: bool


class TerritoryValuation(AuditedRow, total=False):
    film_id: str
    territory_id: str
    method: str
    comp_sample_size: int
    comp_median_usd: float
    cast_multiplier: float
    estimate_usd: float
    ask_price_usd: float
    floor_price_usd: float
    status: str
    published_by_user_id: Optional[str]
    published_at: Optional[str]


class Buyer(AuditedRow, total=False):
    territory_id: str
    company_name: str
    credit_rating: str
    exposure_limit_usd: float
    status: str
    outstanding_exposure_usd: float
    net_unpaid_exposure_usd: float


class Market(AuditedRow, total=False):
    name: str
    city: str
    start_date: str
    end_date: str
    screening_room_count: int
    meeting_table_count: int
    status: str


class ScreeningSlot(AuditedRow, total=False):
    market_id: str
    film_id: str
    room_number: int
    start_at: str
    end_at: str
    slot_type: str
    capacity: int
    status: str


class BuyerMeeting(AuditedRow, total=False):
    market_id: str
    buyer_id: str
    film_id: str
    table_number: int
    start_at: str
    end_at: str
    duration_minutes: int
    status: str
    outcome: Optional[str]


class PreSaleContract(AuditedRow, total=False):
    film_id: str
    buyer_id: str
    territory_id: str
    minimum_guarantee_usd: float
    counter_minimum_guarantee_usd: Optional[float]
    license_term_months: int
    holdback_days: int
    negotiation_status: str
    delivery_status: str
    collection_status: str
    negotiation_round: int
    milestone_pct_total: float
    unpaid_amount_usd: float
    received_amount_usd: float
    license_start_date: Optional[str]
    license_end_date: Optional[str]
    holdback_release_date: Optional[str]
    offered_by_user_id: Optional[str]
    executed_by_user_id: Optional[str]


class PaymentMilestone(AuditedRow, total=False):
    contract_id: str
    label: str
    pct_of_mg: float
    due_date: str
    amount_usd: float
    status: str
    received_amount_usd: float
    received_at: Optional[str]
    received_by_user_id: Optional[str]
    accrued_commission_usd: float


class DeliverablePackage(AuditedRow, total=False):
    contract_id: str
    technical_items_count: int
    legal_items_count: int
    revision_round: int
    status: str
    qc_result: str
    rejection_reason: Optional[str]
    cure_deadline: Optional[str]
    submitted_at: str
    submitted_by_user_id: str


class BankingFacility(AuditedRow, total=False):
    film_id: str
    lender_name: str
    discount_rate_pct: float
    advance_rate_pct: float
    facility_cap_usd: float
    completion_bond_required: bool
    completion_bond_posted: bool
    bond_provider: Optional[str]
    bond_amount_usd: Optional[float]
    status: str
    eligible_collateral_usd: float
    advance_amount_usd: float
    drawn_amount_usd: float
    outstanding_debt_usd: float
    approved_by_user_id: Optional[str]


class CollectionAccount(AuditedRow, total=False):
    film_id: str
    bank_name: str
    account_reference: str
    status: str
    balance_usd: float
    total_receipts_usd: float
    total_distributed_usd: float
    run_count: int


class WaterfallTier(AuditedRow, total=False):
    account_id: str
    tier_order: int
    tier_type: str
    recipient_name: str
    pct_of_available: float
    cap_usd: Optional[float]
    recouped_usd: float
    status: str


class Allocation(TypedDict, total=False):
    tier_id: str
    tier_type: str
    recipient_name: str
    amount_usd: float


class DistributionRun(ReferenceRow, total=False):
    account_id: str
    run_index: int
    amount_in_usd: float
    amount_allocated_usd: float
    residual_usd: float
    run_by_user_id: str
    allocations: List[Allocation]


Payload = Dict[str, Any]
Headers = Dict[str, str]
