"""Shape declarations for the resources of PRD sections 3.1 to 3.10.

These TypedDicts document the field set each read is expected to expose; they are
used for editor support and as the single place where a field name is spelled.
``BondedMovement`` deliberately lacks ``updated_at`` and ``version``, because the
PRD states a movement "carries `id` and `created_at` only, and has neither
`updated_at` nor `version`."
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing_extensions is only needed on older runtimes
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore


class Versioned(TypedDict):
    """The identity fields every resource except a movement carries (PRD 2.5)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Terminal(Versioned):
    iata_code: str
    name: str
    country_code: str
    sealed_bag_regime: str
    liquid_limit_ml: int
    traveler_nationality_mix: Dict[str, int]
    scanned_itinerary_count_30d: int
    unaccounted_duty_liability_cents: int


class Brand(Versioned):
    name: str
    category: str
    status: str
    suspended_at: Optional[str]


class ExclusivityGrant(Versioned):
    brand_id: str
    terminal_id: str
    category: str
    scope: str
    effective_from: str
    effective_to: str
    status: str
    revoked_at: Optional[str]


class AllowanceRule(Versioned):
    destination_country: str
    category: str
    allowance_units: int
    advisory_text: str
    status: str
    superseded_at: Optional[str]


class Product(Versioned):
    brand_id: str
    sku: str
    category: str
    unit_price_cents: int
    duty_rate_bps: int
    vat_rate_bps: int
    target_nationality_code: str
    is_liquid: bool
    liquid_ml: Optional[int]
    required_nationality_share_bps: int
    assortment_status: str
    listed_at: Optional[str]


class BondedStockItem(Versioned):
    terminal_id: str
    product_id: str
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    duty_suspended_value_cents: int
    last_reconciled_at: Optional[str]


class BondedMovement(TypedDict):
    """An immutable ledger entry: identity plus ``created_at`` only (PRD 2.5)."""

    id: str
    created_at: str
    stock_item_id: str
    movement_type: str
    qty_delta: int
    affects: str
    reversed: bool
    reversal_of_movement_id: Optional[str]
    source_ref_type: str
    source_ref_id: Optional[str]
    posted_by_user_id: str
    agreement_period_code: Optional[str]


class PassengerItinerary(Versioned):
    passenger_ref: str
    nationality_code: str
    boarding_pass_barcode: str
    departure_terminal_id: str
    departure_utc: str
    destination_country: str
    final_destination_country: str
    has_connection: bool
    connection_country: Optional[str]
    connection_departure_utc: Optional[str]
    is_international: bool
    scan_status: str
    scanned_at: Optional[str]
    amend_count: int


class Sale(Versioned):
    itinerary_id: str
    terminal_id: str
    agreement_id: str
    channel: str
    fulfillment_status: str
    duty_status: str
    gross_amount_cents: int
    exempt_amount_cents: int
    duty_liability_cents: int
    effective_destination_country: Optional[str]
    eligibility_variant: Optional[str]
    arrival_advisory: List[str]
    sealed_bag_required: bool
    cleared_at: Optional[str]
    picked_up_at: Optional[str]
    voided_at: Optional[str]


class SaleLine(Versioned):
    sale_id: str
    product_id: str
    qty: int
    unit_price_cents: int
    line_total_cents: int
    allowance_excess_qty: int
    line_exempt_cents: int
    line_duty_cents: int


class SealedBag(Versioned):
    sale_id: str
    terminal_id: str
    seal_number: str
    total_liquid_ml: int
    status: str
    issued_at: str
    expires_at: str
    verified_at: Optional[str]


class PreOrder(Versioned):
    itinerary_id: str
    stock_item_id: str
    qty: int
    program: str
    reservation_window_start: str
    reservation_window_end: str
    status: str
    converted_sale_id: Optional[str]
    closed_at: Optional[str]


class ConcessionAgreement(Versioned):
    terminal_id: str
    period_code: str
    period_start_utc: str
    period_end_utc: str
    rent_pct_bps: int
    minimum_guarantee_cents: int
    status: str
    gross_sales_cents: int
    percentage_rent_cents: int
    final_rent_cents: Optional[int]
    marketing_credit_cents: Optional[int]
    net_rent_cents: Optional[int]
    rent_basis: Optional[str]
    closed_at: Optional[str]


class CustomsAudit(Versioned):
    terminal_id: str
    stock_item_id: str
    period_code: str
    preparer_user_id: str
    auditor_user_id: Optional[str]
    counted_qty: Optional[int]
    expected_qty_snapshot: Optional[int]
    shrinkage_qty: int
    assessable_qty: int
    assessed_duty_cents: int
    round_count: int
    info_request_note: Optional[str]
    status: str
    closed_at: Optional[str]


RentProjection = Dict[str, Any]
NationalityMix = Dict[str, Any]
