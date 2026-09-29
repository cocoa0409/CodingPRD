"""
TypedDict shapes for every resource the Renewable Land Origination API returns.

Field names are the PRD's field names. Eleven of the twelve resource kinds carry
the full common set (id, created_at, updated_at, version); the OptionPayment
ledger row deliberately carries only id and created_at, because it is immutable
and "has no updated_at and no version".
"""

from typing import Any, Dict, List, Optional, TypedDict


# ─── Envelope ─────────────────────────────────────────

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


class ApiEnvelope(TypedDict, total=False):
    meta: ResponseMeta
    response_type: str
    data: Any


# ─── Common properties ────────────────────────────────

class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


# ─── Resources ────────────────────────────────────────

class Landowner(CommonFields, total=False):
    legal_name: str
    entity_type: str
    mailing_state: str
    contact_email: str
    w9_on_file: bool
    payment_hold: bool
    status: str
    total_paid_cents: int


class Parcel(CommonFields, total=False):
    apn: str
    county_fips: str
    landowner_id: str
    gross_acres: float
    interconnection_distance_km: float
    resource_capacity_factor: float
    slope_pct: float
    title_condition_grade: str
    zoning_code: str
    slope_excluded_acres: float
    raw_setback_acres: float
    consent_released_acres: float
    setback_encumbered_acres: float
    buildable_acres: float
    screen_mode: str
    screening_score: float
    screening_tier: str
    status: str
    blocking_curative_open_count: int
    waived_blocking_count: int
    curative_cost_cents: int


class SetbackRule(CommonFields, total=False):
    jurisdiction_code: str
    rule_type: str
    setback_feet: int
    encumbrance_rate_per_acre: float
    consent_waivable: bool


class NeighborConsent(CommonFields, total=False):
    parcel_id: str
    setback_rule_id: str
    neighbor_name: str
    consent_expiry_days: int
    requested_at: str
    consent_expiry_at: str
    granted_at: Optional[str]
    revoked_at: Optional[str]
    released_acres: float
    status: str


class TitleCurativeItem(CommonFields, total=False):
    parcel_id: str
    item_type: str
    severity: str
    curative_cost_cents: int
    blocks_item_id: Optional[str]
    created_by_user_id: str
    cleared_by_user_id: Optional[str]
    cleared_at: Optional[str]
    waiver_note: Optional[str]
    status: str


class OptionAgreement(CommonFields, total=False):
    parcel_id: str
    landowner_id: str
    option_term_days: int
    option_fee_per_acre_cents: int
    extension_count_allowed: int
    extension_fee_per_acre_cents: int
    rent_structure_type: str
    base_rent_per_acre_cents: int
    royalty_rate_bps: int
    escalator_pct_bps: int
    escalator_mode: str
    round_index: int
    extensions_used: int
    total_option_paid_cents: int
    executed_at: Optional[str]
    executed_by_user_id: Optional[str]
    option_expiry_at: Optional[str]
    exercised_at: Optional[str]
    exercise_notice_reference: Optional[str]
    withdraw_reason: Optional[str]
    status: str


class OptionPayment(TypedDict, total=False):
    """Immutable ledger row: only id and created_at from the common set."""
    id: str
    created_at: str
    option_agreement_id: str
    sequence_no: int
    payment_kind: str
    ledger_direction: str
    amount_cents: int
    acres_basis: float


class Corridor(CommonFields, total=False):
    route_name: str
    total_length_m: int
    voltage_class: str
    buffer_m: int
    granted_crossing_count: int
    permitted_at: Optional[str]
    status: str


class CrossingAgreement(CommonFields, total=False):
    corridor_id: str
    parcel_id: str
    crossing_kind: str
    station_start_m: int
    station_end_m: int
    occupancy_window_start: str
    occupancy_window_end: str
    occupied_m: int
    duration_days: int
    long_occupancy_surcharge_bps: int
    compensation_cents: int
    granted_at: Optional[str]
    status: str


class SiteAccessBooking(CommonFields, total=False):
    parcel_id: str
    purpose: str
    window_start: str
    window_end: str
    crew_count: int
    cancelled_at: Optional[str]
    status: str


class LeaseAgreement(CommonFields, total=False):
    option_agreement_id: str
    parcel_id: str
    landowner_id: str
    exercise_notice_reference: str
    term_start_date: str
    term_years: int
    acre_basis_at_exercise: float
    gross_security_cents: int
    admin_rate_bps: int
    admin_loading_cents: int
    total_security_required_cents: int
    security_posted_cents: int
    memo_submitted_at: Optional[str]
    recorded_at: Optional[str]
    recording_instrument_no: Optional[str]
    last_paid_invoice_year: int
    rent_status: str
    recording_status: str


class RentInvoice(CommonFields, total=False):
    lease_agreement_id: str
    period_year: int
    production_mwh: float
    rent_variant: str
    acre_basis: float
    per_acre_component_cents: int
    royalty_component_cents: int
    gross_rent_cents: int
    issued_at: Optional[str]
    due_at: Optional[str]
    paid_at: Optional[str]
    paid_amount_cents: Optional[int]
    void_reason: Optional[str]
    status: str


class RentProjection(TypedDict, total=False):
    lease_agreement_id: str
    period_year: int
    provisional_acre_basis: float
    provisional_gross_rent_cents: int
    final_acre_basis: float
    final_per_acre_component_cents: int
    final_royalty_component_cents: int
    final_gross_rent_cents: int
    variant_delta_cents: int


class ClockSweepResult(TypedDict, total=False):
    current_utc: str
    expired_option_count: int
    expired_consent_count: int
    completed_booking_count: int
    delinquent_lease_count: int


Payload = Dict[str, Any]
Headers = Dict[str, str]
ResourceList = List[Dict[str, Any]]
