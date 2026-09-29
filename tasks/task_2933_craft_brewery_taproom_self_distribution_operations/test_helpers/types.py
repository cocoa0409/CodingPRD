"""TypedDict shapes for every resource the API returns.

The common fields of §2.4 (``id``, ``created_at``, ``updated_at``, ``version``)
appear on every mutable resource. A taproom pour is the single exception: PRD
§2.4 and §3.5 state a pour carries only an ``id`` and a ``created_at``, has no
``updated_at`` and no ``version``, so ``TaproomPour`` below omits both.
"""

from typing import Any, Dict, List, Optional, TypedDict


class Brewery(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    home_state_code: str
    ttb_brewers_notice_number: str
    notice_status: str
    notice_effective_utc: Optional[str]
    suspension_reason: Optional[str]
    carry_in_taproom_bbl: float
    carry_in_distribution_bbl: float
    taproom_bbl_ytd: float
    distribution_bbl_ytd: float
    total_bbl_ytd: float
    franchise_locked_state_codes: List[str]


class Beer(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    style: str
    abv_pct: float
    price_per_bbl_cents: int
    requires_formula: bool
    registration_state: str
    label_state: str
    cola_id: Optional[str]
    label_fields: Optional[Dict[str, Any]]
    ingredient_list: Optional[Any]
    taproom_sellable: bool
    distribution_sellable: bool


class Tank(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    code: str
    tank_type: str
    capacity_bbl: float
    status: str
    cip_cycle_count: int
    last_cip_utc: Optional[str]
    occupying_batch_id: Optional[str]


class Batch(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    beer_id: str
    tank_id: str
    batch_code: str
    planned_volume_bbl: float
    brew_start_utc: str
    brew_end_utc: str
    loss_basis: str
    state: str
    actual_yield_bbl: Optional[float]
    packaged_bbl: float
    remaining_bbl: float
    total_loss_bbl: Optional[float]
    dumped_reason: Optional[str]


class PackagingRun(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    batch_id: str
    run_code: str
    package_type: str
    destination: str
    units_planned: int
    units_produced: Optional[int]
    state: str
    reconciliation_state: str
    bbl_removed: float
    allocated_bbl: float
    shipped_bbl: float
    available_bbl: float
    loss_share_bbl: Optional[float]
    kegs_filled_count: int
    kegs_outstanding_count: int
    keg_shrinkage_oz: Optional[float]
    removed_at_utc: Optional[str]
    voided_at_utc: Optional[str]
    certified_by_user_id: Optional[str]


class KegAsset(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    keg_serial: str
    size_bbl: float
    packaging_run_id: Optional[str]
    filled_beer_id: Optional[str]
    state: str
    filled_volume_oz: float
    remaining_volume_oz: float
    poured_volume_oz: float
    returned_volume_oz: Optional[float]
    depletion_variance_oz: Optional[float]
    shrinkage_flagged: bool
    cycle_count: int
    last_cleaned_utc: Optional[str]
    tapped_at_utc: Optional[str]
    deployment_channel: Optional[str]


class TaproomPour(TypedDict, total=False):
    """An append-only pour record: id and created_at only (PRD §2.4)."""

    id: str
    created_at: str
    keg_asset_id: str
    container_type: str
    volume_oz: float
    price_cents: int
    poured_at_utc: str
    poured_by_user_id: str
    container_sanitized: Optional[bool]
    sanitizer_ppm: Optional[int]
    contact_time_seconds: Optional[int]
    attested_by_user_id: Optional[str]
    label_fields: Optional[Dict[str, Any]]
    sanitation_verdict: str


class StateLicense(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    state_code: str
    license_type: str
    annual_barrel_cap: float
    franchise_state: bool
    termination_notice_days: int
    effective_from_utc: str
    expires_at_utc: str
    status: str
    carry_in_barrels_ytd: float
    barrels_shipped_ytd: float
    active_appointment_count: int


class DistributorAppointment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    state_license_id: str
    distributor_name: str
    appointed_beer_id: Optional[str]
    brand_scope: str
    state: str
    good_cause_code: Optional[str]
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    activated_at_utc: Optional[str]
    termination_requested_at_utc: Optional[str]
    termination_effective_utc: Optional[str]
    terminated_at_utc: Optional[str]


class AllocationLine(TypedDict, total=False):
    packaging_run_id: str
    bbl: float


class DistributionOrder(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    beer_id: str
    state_license_id: str
    appointment_id: Optional[str]
    order_code: str
    bbl_requested: float
    ship_to_state_code: str
    distance_miles: int
    requested_ship_utc: str
    channel: str
    state: str
    allocation_lines: List[AllocationLine]
    allocated_bbl: float
    product_cents: int
    freight_cents: int
    franchise_fee_cents: int
    landed_cost_cents: int
    rejection_reason: Optional[str]
    cancel_reason: Optional[str]
    shipped_at_utc: Optional[str]


class ExciseReport(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    period_start_utc: str
    period_end_utc: str
    taproom_basis: str
    amends_report_id: Optional[str]
    state: str
    taproom_bbl: float
    distribution_bbl: float
    total_taxable_bbl: float
    ytd_bbl_before_period: float
    federal_tax_cents: int
    state_tax_cents: int
    total_tax_due_cents: int
    prepared_by_user_id: str
    filed_by_user_id: Optional[str]
    filed_at_utc: Optional[str]


class EventPermit(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    featured_beer_id: str
    event_name: str
    permit_type: str
    venue_state_code: str
    event_start_utc: str
    event_end_utc: str
    requested_bbl: float
    state: str
    submission_count: int
    info_request_note: Optional[str]
    denial_reason: Optional[str]
    decided_at_utc: Optional[str]
